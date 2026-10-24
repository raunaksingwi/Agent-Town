"""Runs: the owner opens a chat, the sandbox (played here by the test) fetches its setup with the
run token, reads the owner's messages and posts back what the agent did."""

import pytest

from app import runs as lifecycle
from app import sandbox

from .conftest import AGENT_MD, FakeProvider, box, fake_sandbox  # noqa: F401  (re-exported for the other test modules)

OAT = "sk-ant-oat01-" + "x" * 40


@pytest.fixture(autouse=True)
def use_fake_sandbox(fake_sandbox):   # every test here runs against the fake provider
    return fake_sandbox


def setup_agent(c, with_key=True):
    a = c.post("/api/agents", json={"markdown": AGENT_MD, "files": [{"path": "notes.md", "content": "hi\n"}]}).json()
    if with_key:
        r = c.post("/api/account/credentials", json={"provider": "anthropic", "kind": "subscription", "secret": OAT})
        assert r.status_code == 200, r.text
    return a


def test_run_round_trip(make_user, client, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    r = alice.post(f"/api/agents/{a['id']}/runs")
    assert r.status_code == 202 and r.json()["status"] == "starting"
    run_id = r.json()["id"]
    [(started_id, token)] = fake_sandbox.started
    assert started_id == run_id and token.startswith("rt_")

    sb = box(client, token)
    setup = sb.get("/api/runtime/setup").json()
    assert setup["credential"] == {"provider": "anthropic", "kind": "subscription", "secret": OAT,
                                   "model": "claude-sonnet-5-5", "thinking": ""}
    assert setup["manifest"]["instructions"].startswith("# Reel writer")
    assert OAT not in str(setup["manifest"])  # the manifest itself stays secret-free

    assert sb.post("/api/runtime/events", json={"events": [{"kind": "status", "data": {"status": "ready"}}]}).status_code == 200
    assert alice.get(f"/api/runs/{run_id}").json()["status"] == "ready"

    sent = alice.post(f"/api/runs/{run_id}/messages", json={"text": "write a hook"}).json()
    inbox = sb.get("/api/runtime/inbox?after=0").json()
    assert inbox["messages"] == [{"id": sent["id"], "text": "write a hook"}]
    assert sb.get(f"/api/runtime/inbox?after={sent['id']}").json()["messages"] == []

    sb.post("/api/runtime/events", json={"events": [
        {"kind": "tool", "data": {"name": "Read", "input": "notes.md"}},
        {"kind": "text", "data": {"text": "POV: you finally…"}},
        {"kind": "done", "data": {"ok": True}}]})
    kinds = [e["kind"] for e in alice.get(f"/api/runs/{run_id}/events").json()["events"]]
    assert kinds == ["status", "user", "tool", "text", "done"]
    after = alice.get(f"/api/runs/{run_id}/events?after={sent['id']}").json()["events"]
    assert [e["kind"] for e in after] == ["tool", "text", "done"]

    # a subscription token is verified by its first successful turn
    cred = alice.get("/api/account/credentials").json()["credentials"][0]
    assert cred["status"] == "valid"

    # the sandbox can't post as the owner
    assert sb.post("/api/runtime/events", json={"events": [{"kind": "user", "data": {"text": "x"}}]}).status_code == 422

    # stopping ends the token at once and tears the box down
    assert alice.delete(f"/api/runs/{run_id}").json()["status"] == "stopped"
    assert fake_sandbox.stopped == [f"fake-{run_id}"]
    assert sb.get("/api/runtime/inbox").status_code == 401
    assert alice.post(f"/api/runs/{run_id}/messages", json={"text": "hi"}).status_code == 409


def test_rejected_credential_is_marked_invalid(make_user, client, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    alice.post(f"/api/agents/{a['id']}/runs")
    sb = box(client, fake_sandbox.started[0][1])
    sb.post("/api/runtime/events", json={"events": [{"kind": "done", "data": {"ok": False, "auth_failed": True}}]})
    alice.headers.pop("Authorization", None)
    assert alice.get("/api/account/credentials").json()["credentials"][0]["status"] == "invalid"


def test_open_run_is_reused(make_user, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    assert alice.get(f"/api/agents/{a['id']}/runs/active").json() is None  # looking starts nothing
    assert fake_sandbox.started == []
    first = alice.post(f"/api/agents/{a['id']}/runs").json()
    assert alice.get(f"/api/agents/{a['id']}/runs/active").json()["id"] == first["id"]
    assert make_user("bob").get(f"/api/agents/{a['id']}/runs/active").status_code == 404
    assert alice.post(f"/api/agents/{a['id']}/runs").json()["id"] == first["id"]
    assert len(fake_sandbox.started) == 1


def test_run_needs_a_model_credential(make_user):
    alice = make_user("alice")
    a = setup_agent(alice, with_key=False)
    assert alice.post(f"/api/agents/{a['id']}/runs").status_code == 422


def test_runner_can_end_its_own_run(make_user, client, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    sb = box(client, fake_sandbox.started[0][1])
    sb.post("/api/runtime/events", json={"events": [{"kind": "status", "data": {"status": "stopped", "detail": "idle"}}]})
    r = alice.get(f"/api/runs/{run_id}").json()
    assert r["status"] == "stopped" and r["ended_at"]
    assert sb.get("/api/runtime/setup").status_code == 401


def test_provider_failure_is_reported(make_user, monkeypatch):
    class Broken(FakeProvider):
        def start(self, run_id, token):
            raise RuntimeError("no capacity")
    monkeypatch.setattr(sandbox, "provider", lambda name=None: Broken())
    alice = make_user("alice")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    r = alice.get(f"/api/runs/{run_id}").json()
    assert r["status"] == "error" and "no capacity" in r["detail"]


def test_runs_are_private(make_user, client, fake_sandbox):
    alice, bob = make_user("alice"), make_user("bob")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    assert bob.post(f"/api/agents/{a['id']}/runs").status_code == 404
    assert bob.get(f"/api/runs/{run_id}").status_code == 404
    assert bob.get(f"/api/runs/{run_id}/events").status_code == 404
    assert bob.post(f"/api/runs/{run_id}/messages", json={"text": "hi"}).status_code == 404
    assert bob.delete(f"/api/runs/{run_id}").status_code == 404

    # a run token is not an API token, and an API token is not a run token
    sb = box(client, fake_sandbox.started[0][1])
    assert sb.get("/api/agents").status_code == 401
    at = alice.post("/api/account/tokens", json={"name": "cli"}).json()["token"]
    alice.cookies.clear()
    alice.headers["Authorization"] = f"Bearer {at}"
    assert alice.get("/api/runtime/setup").status_code == 401
    assert alice.get(f"/api/runs/{run_id}").status_code == 200  # but the owner's token can watch the run


def test_sandbox_that_dies_while_starting_is_reported(make_user, fake_sandbox, db_session):
    from datetime import datetime, timedelta, timezone

    from app.models import Run
    alice = make_user("alice")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    FakeProvider.dead = {f"fake-{run_id}"}
    with db_session() as s:
        s.get(Run, run_id).created_at = datetime.now(timezone.utc) - timedelta(seconds=20)
        s.commit()
    r = alice.get(f"/api/runs/{run_id}").json()
    FakeProvider.dead = set()
    assert r["status"] == "error" and "before it could reach Agent Town" in r["detail"]


def test_unreachable_public_url_fails_fast(make_user, monkeypatch):
    monkeypatch.setattr(lifecycle, "reachable_problem", lambda: "nothing answers there")
    alice = make_user("alice")
    a = setup_agent(alice)
    r = alice.post(f"/api/agents/{a['id']}/runs")
    assert r.status_code == 503 and "nothing answers" in r.json()["detail"]


def test_silent_sandbox_is_reaped(make_user, client, fake_sandbox, db_session):
    from datetime import datetime, timedelta, timezone

    from app.models import Run
    alice = make_user("alice")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    sb = box(client, fake_sandbox.started[0][1])
    sb.post("/api/runtime/events", json={"events": [{"kind": "status", "data": {"status": "ready"}}]})
    with db_session() as s:
        s.get(Run, run_id).last_seen_at = datetime.now(timezone.utc) - lifecycle.SILENCE - timedelta(seconds=5)
        s.commit()
    r = alice.get(f"/api/runs/{run_id}").json()
    assert r["status"] == "error" and "stopped responding" in r["detail"]
    assert fake_sandbox.stopped == [f"fake-{run_id}"]


def test_sandbox_gets_the_teams_tool_credentials(make_user, client, fake_sandbox, monkeypatch):
    from app import mcp_client
    from app.routers import mcp as mcp_router
    monkeypatch.setattr(mcp_router.mcp_client, "check", lambda *a, **k: mcp_client.CheckResult("connected", "ok", "s", "1", [{"name": "t"}]))
    alice = make_user("alice")
    lead = setup_agent(alice)
    member = alice.post("/api/agents", json={"markdown": "---\nname: helper\n---\nHelp."}).json()
    conn = alice.post("/api/mcp", json={"name": "mail", "url": "https://mail.example/mcp", "auth_header": "Bearer m"}).json()
    alice.put(f"/api/agents/{member['id']}/grants", json={"grants": [{"connection_id": conn["id"], "tool_name": None}]})
    alice.put(f"/api/agents/{lead['id']}/team", json={"member_ids": [member["id"]]})
    alice.post(f"/api/agents/{lead['id']}/runs")
    setup = box(client, fake_sandbox.started[0][1]).get("/api/runtime/setup").json()
    assert [t["slug"] for t in setup["manifest"]["team"]] == ["helper"]
    assert [t["server"] for t in setup["manifest"]["tools"]] == ["mail"]   # the lead itself has only mail…
    assert setup["secrets"] == {str(conn["id"]): {"headers": {"Authorization": "Bearer m"}, "env": {}}}   # …but its teammate's come along


def test_deleting_the_account_stops_its_sandboxes(make_user, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    assert alice.request("DELETE", "/api/account", json={"password": "correct horse battery"}).status_code == 200
    assert fake_sandbox.stopped == [f"fake-{run_id}"]


def test_changing_apps_or_team_ends_the_open_chat(make_user, fake_sandbox, monkeypatch):
    from app import mcp_client
    from app.routers import mcp as mcp_router
    monkeypatch.setattr(mcp_router.mcp_client, "check", lambda *a, **k: mcp_client.CheckResult("connected", "ok", "s", "1", [{"name": "t"}]))
    alice = make_user("alice")
    a = setup_agent(alice)
    conn = alice.post("/api/mcp", json={"name": "mail", "url": "https://mail.example/mcp"}).json()
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    alice.put(f"/api/agents/{a['id']}/grants", json={"grants": [{"connection_id": conn["id"], "tool_name": None}]})
    r = alice.get(f"/api/runs/{run_id}").json()
    assert r["ended_at"] and "apps changed" in r["detail"]
    run2 = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    alice.put(f"/api/agents/{a['id']}/grants", json={"grants": [{"connection_id": conn["id"], "tool_name": None}]})   # no change
    assert alice.get(f"/api/runs/{run2}").json()["ended_at"] is None


def test_awake_lists_only_your_open_runs(make_user, fake_sandbox):
    alice, bob = make_user("alice"), make_user("bob")
    a = setup_agent(alice)
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    assert alice.get("/api/runs/active").json() == [{"agent_id": a["id"], "run_id": run_id, "status": "starting"}]
    assert bob.get("/api/runs/active").json() == []
    alice.delete(f"/api/runs/{run_id}")
    assert alice.get("/api/runs/active").json() == []


def test_each_agent_has_its_own_model_and_thinking(make_user, client, fake_sandbox):
    alice = make_user("alice")
    a, b = setup_agent(alice), alice.post("/api/agents", json={"markdown": "---\nname: Quick\n---\nBe brief.\n"}).json()
    run_id = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    r = alice.patch(f"/api/agents/{a['id']}", json={"model": "claude-opus-5-5", "thinking": "max"})
    assert r.status_code == 200 and (r.json()["model"], r.json()["thinking"]) == ("claude-opus-5-5", "max")
    assert r.json()["brain"] == {"provider": "anthropic", "model": "claude-opus-5-5", "thinking": "max"}  # draws its character
    assert alice.get(f"/api/agents/{b['id']}").json()["brain"]["model"] == "claude-sonnet-5-5"
    assert OAT not in str(alice.get("/api/city").json())
    assert "thinks differently" in alice.get(f"/api/runs/{run_id}").json()["detail"]   # applies from the next chat
    assert alice.patch(f"/api/agents/{a['id']}", json={"thinking": "extreme"}).status_code == 422
    assert alice.patch(f"/api/agents/{a['id']}", json={"model": "opus; rm -rf /"}).status_code == 422

    alice.post(f"/api/agents/{a['id']}/runs")
    alice.post(f"/api/agents/{b['id']}/runs")
    (_, ta), (_, tb) = fake_sandbox.started[1:]
    cred = box(client, ta).get("/api/runtime/setup").json()["credential"]
    assert (cred["model"], cred["thinking"]) == ("claude-opus-5-5", "max")
    cred = box(client, tb).get("/api/runtime/setup").json()["credential"]
    assert (cred["model"], cred["thinking"]) == ("claude-sonnet-5-5", "")              # the other one keeps the defaults


def test_runner_passes_model_and_effort_to_the_clis(tmp_path, monkeypatch):
    from .conftest import load_runner
    runner = load_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "emit", lambda *a, **k: None)
    cmds = []
    monkeypatch.setattr(runner, "stream", lambda cmd, *a: (cmds.append(cmd), (0, ""))[1])
    m = {"agent": {"name": "A", "description": ""}, "instructions": "hi", "tools": [], "team": [], "shared": [], "public": []}
    monkeypatch.setattr(runner, "system_prompt", lambda *a: "sys")

    runner.Claude(m, {"kind": "api_key", "secret": "k", "model": "claude-opus-5-5", "thinking": "xhigh"}, {}, []).turn("hi")
    runner.Claude(m, {"kind": "api_key", "secret": "k", "model": "", "thinking": ""}, {}, []).turn("hi")
    runner.Codex(m, {"kind": "api_key", "secret": "k", "model": "", "thinking": "max"}, {}, []).turn("hi")
    claude, plain, codex = cmds
    assert claude[claude.index("--model") + 1] == "claude-opus-5-5" and claude[claude.index("--effort") + 1] == "xhigh"
    assert "--model" not in plain and "--effort" not in plain
    assert 'model_reasoning_effort="xhigh"' in codex                                   # Codex has no "max"


def test_agent_remembers_between_chats(make_user, client, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    first = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    sb = box(client, fake_sandbox.started[0][1])
    alice.post(f"/api/runs/{first}/messages", json={"text": "I'm vegetarian, plan dinner"})
    sb.post("/api/runtime/events", json={"events": [
        {"kind": "tool", "data": {"name": "Read", "input": "notes.md"}},
        {"kind": "text", "data": {"text": "Lentil curry it is."}}]})
    empty = sb.get("/api/runtime/memory").json()["tag"]
    assert sb.put("/api/runtime/memory", json={"content": "- vegetarian\n", "base": empty}).status_code == 200
    assert sb.put("/api/runtime/memory", json={"content": "x" * 20_001, "base": empty}).status_code == 422
    alice.delete(f"/api/runs/{first}")

    alice.post(f"/api/agents/{a['id']}/runs")
    m = box(client, fake_sandbox.started[1][1]).get("/api/runtime/setup").json()["manifest"]
    assert m["memory"] == "- vegetarian\n"
    [chat] = m["recent_chats"]                                       # words only, not its tool calls
    assert [(x["who"], x["text"]) for x in chat["messages"]] == [
        ("owner", "I'm vegetarian, plan dinner"), ("agent", "Lentil curry it is.")]
    old = {"Authorization": f"Bearer {fake_sandbox.started[0][1]}"}
    assert client.put("/api/runtime/memory", json={"content": "x", "base": empty}, headers=old).status_code == 401   # an ended run's token

    client.headers.pop("Authorization", None)
    assert alice.get(f"/api/agents/{a['id']}").json()["memory"] == "- vegetarian\n"
    assert alice.patch(f"/api/agents/{a['id']}", json={"memory": ""}).json()["memory"] == ""   # the owner can make it forget


def test_owners_edit_mid_chat_wins(make_user, client, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    alice.post(f"/api/agents/{a['id']}/runs")
    sb = box(client, fake_sandbox.started[0][1])
    start = sb.get("/api/runtime/inbox").json()["memory"]
    assert start == sb.get("/api/runtime/memory").json()["tag"]

    client.headers.pop("Authorization", None)
    alice.patch(f"/api/agents/{a['id']}", json={"memory": "- call me Al\n"})          # the owner, from the Diary
    sb = box(client, fake_sandbox.started[0][1])
    assert sb.get("/api/runtime/inbox").json()["memory"] != start                        # the sandbox can tell
    r = sb.put("/api/runtime/memory", json={"content": "- agent's older edit\n", "base": start})
    assert r.status_code == 409
    assert sb.get("/api/runtime/memory").json()["content"] == "- call me Al\n"


def test_agent_files_cant_clash_with_memory(make_user):
    alice = make_user("alice")
    a = setup_agent(alice)
    for path in (".agent-town/memory.md", ".agent-town/recent-chats.md"):
        assert alice.put(f"/api/agents/{a['id']}/files", json={"path": path, "content": "x"}).status_code == 422
        assert alice.put("/api/files", json={"path": path, "content": "x"}).status_code == 422


def test_memory_stays_private(make_user, client, fake_sandbox):
    alice = make_user("alice")
    a = setup_agent(alice)
    alice.patch(f"/api/agents/{a['id']}", json={"memory": "- lives at 1 Example St\n"})
    alice.post("/api/public", json={"kind": "agent", "agent_id": a["id"]})
    bob = make_user("bob")
    assert "memory" not in bob.get(f"/api/agents/{a['id']}").json()
    assert "Example St" not in str(bob.get("/api/city").json())


def test_recent_chats_fit_a_budget(make_user, db_session):
    from datetime import datetime, timedelta, timezone

    from app.manifest import RECENT_SAID, recent_chats
    from app.models import Agent, Run, RunEvent
    alice = make_user("alice")
    agent_id = setup_agent(alice)["id"]
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with db_session() as s:
        a = s.get(Agent, agent_id)
        for i in range(8):
            r = Run(agent_id=a.id, owner_id=a.owner_id, provider="fake", token_hash=f"h{i}",
                    created_at=t0 + timedelta(days=i), ended_at=t0 + timedelta(days=i, hours=1))
            s.add(r)
            s.flush()
            for j in range(10):
                s.add(RunEvent(run_id=r.id, kind="user", data={"text": f"chat {i} message {j} " + "x" * 3_000}))
        s.add(Run(agent_id=a.id, owner_id=a.owner_id, provider="fake", token_hash="open"))   # still running: not shown
        s.commit()
        chats = recent_chats(s, a)
    assert chats[0]["messages"][0]["text"].startswith("chat 7 message 0")                     # newest first
    assert all(len(x["text"]) <= RECENT_SAID + 2 for c in chats for x in c["messages"])
    assert sum(len(x["text"]) for c in chats for x in c["messages"]) <= 30_000
    assert chats[-1]["cut"] and chats[-1]["messages"][-1]["text"].startswith(f"chat {8 - len(chats)} message 9")


def test_runner_keeps_memory_in_step(tmp_path, monkeypatch):
    import importlib
    import io
    import sys
    import urllib.error
    monkeypatch.setenv("AGENTTOWN_API_URL", "http://x")
    monkeypatch.setenv("AGENTTOWN_RUN_TOKEN", "rt_x")
    monkeypatch.syspath_prepend(str(__import__("pathlib").Path(__file__).parents[1] / "runner"))
    sys.modules.pop("runner", None)
    runner = importlib.import_module("runner")
    monkeypatch.setattr(runner, "WORK", tmp_path)
    server = {"memory": "- likes tea\n"}
    calls = []

    def api(method, path, body=None):
        calls.append((method, body))
        if method == "GET":
            return {"content": server["memory"]}
        if body["base"] != runner.tag(server["memory"]):
            raise urllib.error.HTTPError("http://x", 409, "conflict", {}, io.BytesIO())
        server["memory"] = body["content"]
        return {}
    monkeypatch.setattr(runner, "api", api)

    m = {"agent": {"name": "A"}, "instructions": "hi", "public": [], "team": [],
         "recent_chats": [{"started_at": "2026-10-09T14:02:00+00:00", "cut": True,
                           "messages": [{"who": "owner", "text": "hello"}, {"who": "agent", "text": "hi there"}]}]}
    runner.write_recent(m)
    chats = (tmp_path / ".agent-town/recent-chats.md").read_text()
    assert "## 2026-10-09 14:02 UTC" in chats and "**They:** hello" in chats and "**You:** hi there" in chats
    assert ".agent-town/memory.md" in runner.system_prompt(m, []) and ".agent-town/recent-chats.md" in runner.system_prompt(m, [])
    assert "about-us.md is what" in runner.system_prompt(m, ["about-us.md"]) and "about-us" not in runner.system_prompt(m, [])

    mem = runner.Memory(server["memory"])
    notes = tmp_path / ".agent-town/memory.md"
    assert notes.read_text() == "- likes tea\n"
    mem.save()
    assert calls == []                                                        # unchanged: nothing sent
    notes.write_text("- likes green tea\n")                                   # the agent edits its notes
    mem.save()
    assert server["memory"] == "- likes green tea\n"
    mem.check(runner.tag(server["memory"]))
    assert mem.tell("hi") == "hi"                                             # in step: nothing to say

    server["memory"] = "- call me Al\n"                                       # the owner edits between turns
    mem.check(runner.tag(server["memory"]))
    assert notes.read_text() == "- call me Al\n" and "edited" in mem.tell("hi") and mem.tell("hi") == "hi"

    notes.write_text("- agent's edit\n")                                      # both edit during one turn
    server["memory"] = "- owner's edit\n"
    mem.save()
    assert server["memory"] == "- owner's edit\n" and notes.read_text() == "- owner's edit\n"
    assert "weren't kept" in mem.tell("next")

    notes.unlink()
    mem.save()
    assert server["memory"] == "- owner's edit\n"                              # deleted: keep what was saved


def test_first_chat_interviews_until_about_me_exists(make_user, client, fake_sandbox):
    alice = make_user("alice")
    md = AGENT_MD.replace("description:", "ask: Who do you write for? | Paste a reel you liked.\ndescription:")
    a = alice.post("/api/agents", json={"markdown": md}).json()
    alice.post("/api/account/credentials", json={"provider": "anthropic", "kind": "subscription", "secret": OAT})
    first = alice.post(f"/api/agents/{a['id']}/runs").json()["id"]
    sb = box(client, fake_sandbox.started[0][1])
    assert sb.get("/api/runtime/setup").json()["manifest"]["interview"] == ["Who do you write for?", "Paste a reel you liked."]

    assert sb.put("/api/runtime/about-me", json={"content": "  \n"}).status_code == 422      # never wiped
    assert sb.put("/api/runtime/about-me", json={"content": "# About me\n\nFounders on LinkedIn.\n"}).status_code == 200
    files = alice.get(f"/api/agents/{a['id']}").json()["files"]
    assert any(f["path"] == "about-me.md" and "Founders" in f["content"] for f in files)   # the owner sees it
    alice.delete(f"/api/runs/{first}")

    alice.post(f"/api/agents/{a['id']}/runs")
    m = box(client, fake_sandbox.started[1][1]).get("/api/runtime/setup").json()["manifest"]
    assert m["interview"] == [] and any(f["path"] == "about-me.md" for f in m["files"])


def test_runner_interviews_and_keeps_about_me(tmp_path, monkeypatch):
    import importlib
    import sys
    monkeypatch.setenv("AGENTTOWN_API_URL", "http://x")
    monkeypatch.setenv("AGENTTOWN_RUN_TOKEN", "rt_x")
    monkeypatch.syspath_prepend(str(__import__("pathlib").Path(__file__).parents[1] / "runner"))
    sys.modules.pop("runner", None)
    runner = importlib.import_module("runner")
    monkeypatch.setattr(runner, "WORK", tmp_path)
    calls = []
    monkeypatch.setattr(runner, "api", lambda method, path, body=None: calls.append((path, body)) or {})

    m = {"agent": {"name": "A"}, "instructions": "hi", "public": [], "team": [], "interview": ["Who do you write for?"]}
    prompt = runner.system_prompt(m, ["about-us.md"])
    assert "- Who do you write for?" in prompt and "Read about-us.md first" in prompt and "write them to about-me.md" in prompt
    assert "Who do you write for" not in runner.system_prompt({**m, "interview": []}, [])

    about = runner.AboutMe()
    about.save()
    assert calls == []                                       # nothing written: nothing sent
    (tmp_path / "about-me.md").write_text("# About me\n- founders\n")
    about.save()
    about.save()
    assert calls == [("/api/runtime/about-me", {"content": "# About me\n- founders\n"})]   # once, not every turn
    (tmp_path / "about-me.md").unlink()
    about.save()
    assert len(calls) == 1                                   # deleted in the sandbox: keep what was saved
