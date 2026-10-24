"""Routines: an agent's job on a schedule, started by the scheduler as a run nobody is watching, and
the Today page that shows what they did and what's waiting on the person."""

from datetime import datetime, timedelta, timezone

import pytest

from app import routines
from app.models import Routine, RunEvent

from .conftest import AGENT_MD
from .test_runs import FakeProvider, box, fake_sandbox, setup_agent  # noqa: F401  (fake_sandbox: autouse fixture)

UTC = timezone.utc


@pytest.fixture(autouse=True)
def launch_inline(monkeypatch):
    """Start the (fake) box right away instead of in a thread, so tests can see it."""
    monkeypatch.setattr(routines, "launch", lambda start, *args: start(*args))


def at(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_next_time_follows_days_and_local_time():
    # Monday 13 Oct 2026, 07:00 UTC
    mon = at(2026, 10, 12, 7, 0)
    assert routines.next_time("01234", "08:00", "UTC", mon) == at(2026, 10, 12, 8, 0)
    assert routines.next_time("01234", "08:00", "UTC", at(2026, 10, 12, 8, 0)) == at(2026, 10, 13, 8, 0)  # strictly after
    assert routines.next_time("01234", "08:00", "UTC", at(2026, 10, 16, 9, 0)) == at(2026, 10, 19, 8, 0)  # Fri → Mon
    assert routines.next_time("4", "16:00", "UTC", mon) == at(2026, 10, 16, 16, 0)
    assert routines.next_time("", "08:00", "UTC", mon) is None
    # 08:00 in New York is 12:00 UTC in summer time and 13:00 UTC after the clocks go back (1 Nov 2026)
    ny = "America/New_York"
    assert routines.next_time("0123456", "08:00", ny, at(2026, 10, 31, 0, 0)) == at(2026, 10, 31, 12, 0)
    assert routines.next_time("0123456", "08:00", ny, at(2026, 11, 1, 0, 0)) == at(2026, 11, 1, 13, 0)


def make_routine(c, agent_id, **kw):
    body = {"agent_id": agent_id, "name": "Morning brief", "prompt": "Brief me.", "days": "0123456", "at": "08:00",
            "timezone": "Europe/London", **kw}
    r = c.post("/api/routines", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_crud_and_validation(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    a = setup_agent(alice)
    r = make_routine(alice, a["id"], days="10")
    assert r["days"] == "01" and r["when"] == "Mon, Tue at 08:00" and r["enabled"] and r["next_run_at"]
    assert r["agent"] == "reel-writer" and r["last_run"] is None

    for bad in ({"timezone": "Mars/Base"}, {"days": "7"}, {"days": ""}, {"at": "8am"}, {"at": "24:00"}):
        assert alice.post("/api/routines", json={"agent_id": a["id"], "name": "x", "prompt": "y", **bad}).status_code == 422
    # someone else's agent or routine: not found, as if it didn't exist
    assert bob.post("/api/routines", json={"agent_id": a["id"], "name": "x", "prompt": "y"}).status_code == 404
    assert bob.patch(f"/api/routines/{r['id']}", json={"enabled": False}).status_code == 404
    assert bob.get("/api/routines").json() == []

    off = alice.patch(f"/api/routines/{r['id']}", json={"enabled": False}).json()
    assert off["enabled"] is False and off["next_run_at"] is None
    on = alice.patch(f"/api/routines/{r['id']}", json={"enabled": True, "days": "56"}).json()
    assert on["when"] == "Weekends at 08:00" and on["next_run_at"]
    assert alice.delete(f"/api/routines/{r['id']}").status_code == 200
    assert alice.get("/api/routines").json() == []


def due(db_session, routine_id, ago=timedelta(minutes=1)):
    with db_session() as db:
        db.get(Routine, routine_id).next_run_at = datetime.now(UTC) - ago
        db.commit()


def test_due_routine_starts_a_run_that_ends_itself(make_user, client, db_session, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    r = make_routine(alice, a["id"], prompt="Summarize my inbox.")
    due(db_session, r["id"])

    with db_session() as db:
        [run] = routines.tick(db)
        assert run.routine_id == r["id"] and run.agent_id == a["id"]
        nxt = db.get(Routine, r["id"]).next_run_at
        assert nxt.replace(tzinfo=UTC) > datetime.now(UTC)          # moved on to the next time
        assert routines.tick(db) == []                              # and not started twice
    [(run_id, token)] = fake_sandbox.started
    assert run_id == run.id

    sb = box(client, token)
    [first] = sb.get("/api/runtime/inbox?after=0").json()["messages"]
    assert first["text"].startswith('[From Agent Town: this is your routine "Morning brief"')
    assert first["text"].endswith("Summarize my inbox.")

    # A chat with the same agent is its own run: it doesn't join the routine's
    assert alice.get(f"/api/agents/{a['id']}/runs/active").json() is None

    post = lambda *evs: sb.post("/api/runtime/events", json={"events": [{"kind": k, "data": d} for k, d in evs]})
    post(("status", {"status": "ready"}))                           # booted: not finished yet
    assert alice.get(f"/api/runs/{run.id}").json()["status"] == "ready"
    post(("status", {"status": "busy"}), ("tool", {"name": "mcp__gmail__search_emails"}),
         ("tool", {"name": "mcp__gmail__search_emails"}), ("tool", {"name": "Task", "input": '{"subagent_type": "emma", "prompt": "…"}'}),
         ("text", {"text": "Working on it"}), ("text", {"text": "**3 things need you today.**"}),
         ("done", {"ok": True, "cost_usd": 0.04, "duration_ms": 41000}))
    assert alice.get(f"/api/runs/{run.id}").json()["ended_at"] is None   # still saving its notes
    post(("status", {"status": "ready"}))
    ended = alice.get(f"/api/runs/{run.id}").json()
    assert ended["status"] == "stopped" and ended["detail"] == "Finished" and ended["ended_at"]
    assert fake_sandbox.stopped == [f"fake-{run.id}"]

    today = alice.get("/api/today").json()
    [res] = today["results"]
    assert res["routine"] == "Morning brief" and res["agent"]["name"] == "reel-writer"
    assert res["report"] == "**3 things need you today.**"           # its last words are the report
    assert res["steps"] == [{"tool": "gmail: search emails", "count": 2}, {"tool": "asked emma", "count": 1}]
    assert res["done"] == {"ok": True, "cost_usd": 0.04, "duration_ms": 41000}
    assert today["routines"][0]["last_run"]["id"] == run.id


def test_skips_a_run_it_missed_by_hours(make_user, db_session, fake_sandbox):
    alice = make_user("alice")
    r = make_routine(alice, setup_agent(alice)["id"])
    due(db_session, r["id"], ago=timedelta(hours=5))               # the server was down at 08:00
    with db_session() as db:
        assert routines.tick(db) == []
        assert db.get(Routine, r["id"]).next_run_at.replace(tzinfo=UTC) > datetime.now(UTC)
    assert fake_sandbox.started == []


def test_without_an_ai_the_failure_shows_on_today(make_user, db_session, fake_sandbox):
    alice = make_user("alice")
    r = make_routine(alice, setup_agent(alice, with_key=False)["id"])
    due(db_session, r["id"])
    with db_session() as db:
        [run] = routines.tick(db)
    assert fake_sandbox.started == []
    [res] = alice.get("/api/today").json()["results"]
    assert res["run"]["status"] == "error" and "model key" in res["run"]["detail"]


def test_run_now_once_at_a_time(make_user, fake_sandbox):
    alice = make_user("alice")
    r = make_routine(alice, setup_agent(alice)["id"])
    first = alice.post(f"/api/routines/{r['id']}/run")
    assert first.status_code == 202 and first.json()["routine_id"] == r["id"]
    assert alice.post(f"/api/routines/{r['id']}/run").status_code == 409
    assert alice.get("/api/routines").json()[0]["next_run_at"] == r["next_run_at"]   # schedule unchanged


def test_today_waiting_and_suggestions(make_user, db_session, fake_sandbox):
    alice, bob = make_user("alice"), make_user("bob")
    a = setup_agent(alice)
    run = alice.post(f"/api/agents/{a['id']}/runs").json()        # a chat, not a routine
    with db_session() as db:
        for state in ("pending", "sent"):
            db.add(RunEvent(run_id=run["id"], kind="approval",
                            data={"to": "sam@example.com", "subject": "Hi", "body": "…", "state": state}))
        db.commit()
    today = alice.get("/api/today").json()
    [w] = today["waiting"]
    assert w["run_id"] == run["id"] and w["event"]["data"]["to"] == "sam@example.com" and w["routine"] is None
    assert today["results"] == []                                  # chats aren't routine results
    assert bob.get("/api/today").json()["waiting"] == []           # nobody else's

    # The founder team's Maya gets a ready-made morning brief, until it's added
    maya = alice.post("/api/agents", json={"markdown": AGENT_MD.replace("reel-writer", "maya"), "files": []}).json()
    [s] = alice.get("/api/today").json()["suggested"]
    assert s["slug"] == "maya" and s["agent_id"] == maya["id"] and s["name"] == "Morning brief"
    make_routine(alice, maya["id"], name="Morning brief")
    assert alice.get("/api/today").json()["suggested"] == []
