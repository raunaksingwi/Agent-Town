"""A run's life (app/runs.py): heartbeats during a turn, the sweeps that notice a dead box, the
limits on a run's length, and what the scheduler and a click can't do twice."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app import runs as lifecycle
from app.models import Run

from .conftest import AGENT_MD, FakeProvider, box
from .test_runs import OAT, setup_agent

UTC = timezone.utc


@pytest.fixture(autouse=True)
def use_fake_sandbox(fake_sandbox):
    return fake_sandbox


def running(make_user, client, status="ready"):
    alice = make_user("alice")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    sb = box(client, FakeProvider.started[0][1])
    sb.post("/api/runtime/events", json={"events": [{"kind": "status", "data": {"status": status}}]})
    return alice, sb, a, run_id


def age(db_session, run_id, **fields):
    with db_session() as s:
        r = s.get(Run, run_id)
        for k, v in fields.items():
            setattr(r, k, datetime.now(UTC) - v)
        s.commit()


def test_a_busy_run_is_given_longer_than_an_idle_one(make_user, client, db_session):
    alice, sb, a, run_id = running(make_user, client, "busy")
    age(db_session, run_id, last_seen_at=timedelta(minutes=3))        # a long tool call: no inbox polls
    assert alice.get(f"/api/runs/{run_id}").json()["status"] == "busy"
    age(db_session, run_id, last_seen_at=timedelta(minutes=12))
    r = alice.get(f"/api/runs/{run_id}").json()
    assert r["status"] == "error" and "stopped responding" in r["detail"]


def test_ping_is_the_heartbeat_during_a_turn(make_user, client, db_session):
    alice, sb, a, run_id = running(make_user, client, "busy")
    age(db_session, run_id, last_seen_at=timedelta(minutes=9))
    assert sb.get("/api/runtime/ping").json() == {"ok": True}
    age(db_session, run_id, created_at=timedelta(minutes=1))          # only to touch the row again
    with db_session() as s:
        assert datetime.now(UTC) - s.get(Run, run_id).last_seen_at.replace(tzinfo=UTC) < timedelta(seconds=30)
    assert alice.get(f"/api/runs/{run_id}").json()["status"] == "busy"


def test_a_run_never_outlives_the_maximum(make_user, client, db_session):
    alice, sb, a, run_id = running(make_user, client)
    age(db_session, run_id, created_at=timedelta(hours=5), last_seen_at=timedelta(seconds=1))
    r = alice.get(f"/api/runs/{run_id}").json()
    assert r["status"] == "stopped" and "maximum" in r["detail"]
    assert FakeProvider.stopped == [f"fake-{run_id}"]


def test_a_box_that_never_starts_is_given_up_on(make_user, db_session):
    alice = make_user("alice")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    age(db_session, run_id, created_at=timedelta(minutes=11))
    r = alice.get(f"/api/runs/{run_id}").json()
    assert r["status"] == "error" and "never started" in r["detail"]


def test_the_scheduler_sweep_notices_a_dead_box(make_user, client, db_session):
    alice, sb, a, run_id = running(make_user, client)
    age(db_session, run_id, last_seen_at=timedelta(minutes=5))
    with db_session() as db:
        lifecycle.reap_all(db)                                        # nobody has the app open
    assert alice.get(f"/api/runs/{run_id}").json()["status"] == "error"


def test_a_run_ended_while_booting_has_its_box_stopped(make_user, db_session, monkeypatch):
    """The owner stops the run (or it's reaped) between the provider starting the box and the run
    remembering its id: the box is stopped anyway, instead of running on forgotten."""
    class Slow(FakeProvider):
        def start(self, run_id, token):
            with db_session() as s:
                lifecycle.end(s, s.get(Run, run_id), "stopped", "Stopped by you")
            return super().start(run_id, token)
    from app import sandbox
    monkeypatch.setattr(sandbox, "provider", lambda name=None: Slow())
    alice = make_user("alice")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    assert FakeProvider.stopped == [f"fake-{run_id}"]
    with db_session() as s:
        assert s.get(Run, run_id).sandbox_id == ""


def test_reusing_an_open_chat_answers_200(make_user):
    alice = make_user("alice")
    a = setup_agent(alice)
    assert alice.post(f"/api/agents/{a['id']}/runs").status_code == 202
    assert alice.post(f"/api/agents/{a['id']}/runs").status_code == 200


def test_an_oversized_event_is_kept_as_a_stub(make_user, client):
    alice, sb, a, run_id = running(make_user, client)
    big = {"name": "Read", "ok": True, "input": "x" * 200_000}
    assert sb.post("/api/runtime/events", json={"events": [{"kind": "tool", "data": big}]}).status_code == 200
    [e] = [e for e in alice.get(f"/api/runs/{run_id}/events").json()["events"] if e["kind"] == "tool"]
    assert e["data"] == {"truncated": True, "name": "Read", "ok": True}


def test_a_stop_in_the_middle_of_a_batch_keeps_the_rest(make_user, client):
    alice, sb, a, run_id = running(make_user, client)
    sb.post("/api/runtime/events", json={"events": [
        {"kind": "text", "data": {"text": "Done."}},
        {"kind": "status", "data": {"status": "stopped", "detail": "Stopped after being idle"}},
        {"kind": "error", "data": {"detail": "late news"}}]})
    r = alice.get(f"/api/runs/{run_id}/events").json()
    assert r["run"]["status"] == "stopped" and r["run"]["detail"] == "Stopped after being idle"
    assert [e["kind"] for e in r["events"]][-3:] == ["text", "error", "status"]   # stored, then ended


def test_a_routine_can_have_one_open_run(make_user, db_session):
    """The database allows one open run per routine, whichever process asks first."""
    alice = make_user("alice")
    a = setup_agent(alice)
    r = alice.post("/api/routines", json={"agent_id": a["id"], "name": "x", "prompt": "y"}).json()
    with db_session() as s:
        for _ in range(2):
            s.add(Run(agent_id=a["id"], owner_id=1, routine_id=r["id"], provider="fake", token_hash=f"h{_}"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        s.add(Run(agent_id=a["id"], owner_id=1, routine_id=r["id"], provider="fake", token_hash="h3",
                  ended_at=datetime.now(UTC)))                        # an ended one doesn't count
        s.add(Run(agent_id=a["id"], owner_id=1, routine_id=r["id"], provider="fake", token_hash="h4"))
        s.commit()


def test_deleting_an_agent_or_its_app_stops_its_box(make_user, client, monkeypatch):
    from app import mcp_client
    from app.routers import mcp as mcp_router
    monkeypatch.setattr(mcp_router.mcp_client, "check", lambda *a, **k: mcp_client.CheckResult("connected", "ok", "s", "1", [{"name": "t"}]))
    alice, sb, a, run_id = running(make_user, client)
    conn = alice.post("/api/mcp", json={"name": "mail", "url": "https://mail.example/mcp"}).json()
    alice.put(f"/api/agents/{a['id']}/grants", json={"grants": [{"connection_id": conn["id"], "tool_name": None}]})
    assert "apps changed" in alice.get(f"/api/runs/{run_id}").json()["detail"]
    second = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    alice.delete(f"/api/mcp/{conn['id']}")
    assert "removed" in alice.get(f"/api/runs/{second}").json()["detail"]
    third = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    alice.delete(f"/api/agents/{a['id']}")
    assert f"fake-{third}" in FakeProvider.stopped


def test_dates_say_their_offset_on_sqlite(make_user):
    """SQLite drops the time zone; the API must still say +00:00, or the browser reads local time."""
    alice = make_user("alice")
    a = setup_agent(alice)
    assert a["files"][0]["updated_at"].endswith("+00:00")
    run = alice.post(f"/api/agents/{a['id']}/runs").json()
    assert run["created_at"].endswith("+00:00")


def test_names_that_slug_the_same_in_one_request(make_user, db_session):
    from app.models import User
    from app.routers.agents import new_agent
    make_user("alice")
    with db_session() as s:
        u = s.scalar(select(User))
        one = new_agent(s, u, AGENT_MD.replace("reel-writer", "Writer"), "Writer")
        two = new_agent(s, u, AGENT_MD.replace("reel-writer", "writer"), "writer")
        s.commit()
        assert (one.slug, two.slug) == ("writer", "writer-2") and one.color != two.color


def test_the_map_is_a_handful_of_queries_however_many_agents(make_user, db_session):
    alice = make_user("alice")
    for i in range(10):
        alice.post("/api/agents", json={"markdown": AGENT_MD.replace("reel-writer", f"agent-{i}"),
                                        "files": [{"path": "notes.md", "content": "hi\n"}]})
    alice.post("/api/account/credentials", json={"provider": "anthropic", "kind": "subscription", "secret": OAT})
    count = [0]
    engine = db_session.kw["bind"]

    def tally(*a):
        count[0] += 1
    event.listen(engine, "before_cursor_execute", tally)
    try:
        assert len(alice.get("/api/city").json()["agents"]) == 10
    finally:
        event.remove(engine, "before_cursor_execute", tally)
    assert count[0] < 15, count[0]


def test_migrations_build_an_empty_database(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    env = {"AGENTTOWN_DATABASE_URL": f"sqlite:///{tmp_path / 'fresh.db'}", "PATH": __import__("os").environ["PATH"]}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=Path(__file__).parents[1],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=Path(__file__).parents[1],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "No new upgrade operations" in r.stdout + r.stderr, r.stdout + r.stderr


def test_a_new_routine_without_its_essentials_is_a_normal_422(make_user):
    alice = make_user("alice")
    r = alice.post("/api/routines", json={"name": "x"})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
    assert {d["loc"][-1] for d in r.json()["detail"]} == {"agent_id", "prompt"}


def test_a_shared_agent_has_its_own_public_address(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    a = setup_agent(alice, with_key=False)
    assert bob.get(f"/api/public/agents/{a['id']}").status_code == 404
    alice.post("/api/public", json={"kind": "agent", "agent_id": a["id"]})
    pub = bob.get(f"/api/public/agents/{a['id']}").json()
    assert pub["name"] == "reel-writer" and "memory" not in pub
    assert bob.get(f"/api/agents/{a['id']}").json()["name"] == "reel-writer"   # the old address still works
