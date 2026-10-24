"""Each user reaches only their own town. Bob tries every endpoint against Alice's things,
with his session and with his API token, and must always get 404 (or see nothing)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import account as account_router

from .conftest import AGENT_MD


@pytest.fixture
def alice_things(make_user):
    alice = make_user("alice")
    agent = alice.post("/api/agents", json={"markdown": AGENT_MD,
                                            "files": [{"path": "notes.md", "content": "private\n"}]}).json()
    conn = alice.post("/api/mcp", json={"name": "gmail", "transport": "stdio", "command": "npx gmail"}).json()
    token = alice.post("/api/account/tokens", json={"name": "cli"}).json()
    return alice, agent, conn, token


def bob_clients(make_user):
    bob = make_user("bob")
    tok = bob.post("/api/account/tokens", json={"name": "bob-cli"}).json()["token"]
    bearer = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    return [bob, bearer]


def test_bob_cannot_touch_alices_things(alice_things, make_user):
    _, agent, conn, token = alice_things
    a, c, f = agent["id"], conn["id"], agent["files"][1]["id"]
    for bob in bob_clients(make_user):
        assert bob.get("/api/city").json()["agents"] == []
        assert bob.get("/api/city").json()["connections"] == []
        assert bob.get("/api/agents").json() == []
        assert bob.get("/api/mcp").json() == []
        for method, path, body in [
            ("GET", f"/api/agents/{a}", None),
            ("PATCH", f"/api/agents/{a}", {"name": "x"}),
            ("DELETE", f"/api/agents/{a}", None),
            ("PUT", f"/api/agents/{a}/files", {"path": "x.md", "content": "x"}),
            ("DELETE", f"/api/agents/{a}/files/{f}", None),
            ("PUT", f"/api/agents/{a}/grants", {"grants": []}),
            ("GET", f"/api/agents/{a}/manifest", None),
            ("PATCH", f"/api/mcp/{c}", {"name": "x"}),
            ("POST", f"/api/mcp/{c}/check", None),
            ("DELETE", f"/api/mcp/{c}", None),
            ("POST", "/api/public", {"kind": "agent", "agent_id": a}),
            ("POST", "/api/public", {"kind": "file", "file_id": f}),
        ]:
            r = bob.request(method, path, json=body)
            assert r.status_code == 404, (bob.headers.get("authorization", "session"), method, path, r.status_code)


def test_bob_cannot_use_alices_connection_or_token(alice_things, make_user):
    _, _, conn, token = alice_things
    bob = make_user("bob")
    b = bob.post("/api/agents", json={"markdown": AGENT_MD}).json()
    assert bob.put(f"/api/agents/{b['id']}/grants", json={"grants": [{"connection_id": conn["id"]}]}).status_code == 404
    assert bob.delete(f"/api/account/tokens/{token['id']}").status_code == 404


def test_api_token_reads_only_its_owners_town(alice_things):
    _, agent, _, token = alice_things
    cli = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    city = cli.get("/api/city").json()
    assert city["me"]["username"] == "alice"
    assert [x["id"] for x in city["agents"]] == [agent["id"]]
    assert cli.get(f"/api/agents/{agent['id']}/manifest").status_code == 200
    # and it can write, no cookie needed (and no Origin check: there's no ambient credential)
    assert cli.patch(f"/api/agents/{agent['id']}", json={"description": "via token"}).status_code == 200


def test_bad_tokens_fail_loudly(client):
    for header in ("Bearer at_not-a-real-token", "Bearer something", "Basic dXNlcjpwYXNz"):
        r = TestClient(app, headers={"Authorization": header}).get("/api/city")
        assert r.status_code == 401, header
        assert r.headers.get("www-authenticate") == "Bearer"


def test_revoked_and_expired_tokens(alice_things, db_session):
    alice, _, _, token = alice_things
    cli = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    assert cli.get("/api/city").status_code == 200
    listed = alice.get("/api/account/tokens").json()
    assert listed[0]["last_used_at"] and "token" not in listed[0]
    alice.delete(f"/api/account/tokens/{token['id']}")
    assert cli.get("/api/city").status_code == 401

    short = alice.post("/api/account/tokens", json={"name": "short", "expires_days": 1}).json()
    from datetime import datetime, timedelta, timezone

    from app.models import ApiToken
    s = db_session()
    t = s.get(ApiToken, short["id"])
    t.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    s.commit()
    assert TestClient(app, headers={"Authorization": f"Bearer {short['token']}"}).get("/api/city").status_code == 401


def test_tokens_cannot_manage_tokens_or_keys(alice_things):
    _, _, _, token = alice_things
    cli = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    assert cli.post("/api/account/tokens", json={"name": "escalate"}).status_code == 403
    assert cli.get("/api/account/tokens").status_code == 403
    assert cli.get("/api/account/credentials").status_code == 403


# ---- model credentials ----------------------------------------------------------------------

def fake_provider(monkeypatch, status="valid"):
    from app.model_check import Checked
    monkeypatch.setattr(account_router.model_check, "check",
                        lambda provider, kind, secret, client=None: Checked(status, "ok") if kind == "api_key"
                        else Checked("unverified", "later"))


def test_credentials_are_private_and_never_returned(monkeypatch, make_user):
    fake_provider(monkeypatch)
    alice, bob = make_user("alice"), make_user("bob")
    key = "sk-ant-api03-" + "x" * 40 + "WXYZ"
    c = alice.post("/api/account/credentials", json={"provider": "anthropic", "secret": key}).json()
    assert c["status"] == "valid" and c["hint"] == "WXYZ" and c["is_default"]
    assert key not in str(alice.get("/api/account/credentials").json())

    assert bob.get("/api/account/credentials").json()["credentials"] == []
    assert bob.post(f"/api/account/credentials/{c['id']}/check").status_code == 404
    assert bob.delete(f"/api/account/credentials/{c['id']}").status_code == 404
    b = bob.post("/api/agents", json={"markdown": AGENT_MD}).json()
    assert bob.patch(f"/api/agents/{b['id']}", json={"model_credential_id": c["id"]}).status_code == 404

    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    m = alice.get(f"/api/agents/{a['id']}/manifest").json()
    assert m["model"]["provider"] == "anthropic" and m["model"]["credential_id"] == c["id"]
    assert key not in str(m)
    assert bob.get(f"/api/agents/{b['id']}/manifest").json()["model"] is None


def test_credential_shape_and_subscription_switch(monkeypatch, make_user):
    fake_provider(monkeypatch)
    alice = make_user("alice")
    r = alice.post("/api/account/credentials", json={"provider": "anthropic", "secret": "sk-proj-nope-nope"})
    assert r.status_code == 422 and "sk-ant-api" in r.json()["detail"]
    sub = {"provider": "anthropic", "kind": "subscription", "secret": "sk-ant-oat01-" + "y" * 40}
    from app.config import settings
    monkeypatch.setattr(settings(), "allow_subscription_tokens", False)
    assert alice.post("/api/account/credentials", json=sub).status_code == 403

    monkeypatch.setattr(settings(), "allow_subscription_tokens", True)
    c = alice.post("/api/account/credentials", json=sub).json()
    assert c["status"] == "unverified" and c["hint"] == ""


def test_default_moves_when_deleted(monkeypatch, make_user):
    fake_provider(monkeypatch)
    alice = make_user("alice")
    one = alice.post("/api/account/credentials", json={"provider": "openai", "secret": "sk-" + "a" * 40}).json()
    two = alice.post("/api/account/credentials", json={"provider": "anthropic", "secret": "sk-ant-api03-" + "b" * 40}).json()
    assert one["is_default"] and not two["is_default"]
    alice.patch(f"/api/account/credentials/{two['id']}", json={"is_default": True})
    alice.delete(f"/api/account/credentials/{two['id']}")
    creds = alice.get("/api/account/credentials").json()["credentials"]
    assert [(c["id"], c["is_default"]) for c in creds] == [(one["id"], True)]


def test_delete_account_removes_everything(make_user, client):
    alice, bob = make_user("alice"), make_user("bob")
    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    alice.put("/api/files", json={"path": "notes.md", "content": "x\n"})
    alice.post("/api/public", json={"kind": "agent", "agent_id": a["id"]})
    token = alice.post("/api/account/tokens", json={"name": "cli"}).json()["token"]
    b = bob.post("/api/agents", json={"markdown": AGENT_MD}).json()

    assert alice.request("DELETE", "/api/account", json={"password": "wrong password"}).status_code == 403
    api = TestClient(app, headers={"Authorization": f"Bearer {token}"})       # an API token can't do it
    assert api.request("DELETE", "/api/account", json={"password": "correct horse battery"}).status_code == 403

    assert alice.request("DELETE", "/api/account", json={"password": "correct horse battery"}).json() == {"ok": True}
    assert alice.get("/api/auth/me").json() is None                           # signed out
    assert api.get("/api/agents").status_code == 401                          # its tokens are gone too
    assert client.post("/api/auth/login", json={"login": "alice", "password": "correct horse battery"}).status_code == 401
    assert client.get("/api/city").json()["public"] == []                     # its public shares are gone
    assert bob.get(f"/api/agents/{b['id']}").status_code == 200               # nobody else's things are touched
    # the name is free again
    assert client.post("/api/auth/signup", json={"email": "alice@example.com", "username": "alice",
                                                 "password": "correct horse battery"}).status_code == 200


@pytest.mark.parametrize("path", ["a/../../../../CLAUDE.md", "../x.md", ".claude/agents/x.md", "a//b.md", "a/./b.md", "/etc/x.md"])
def test_file_paths_cannot_climb_or_hide(make_user, path):
    """A file is written into a sandbox at exactly its path, and a public share lands in every
    other user's sandbox, so a path must never climb out of its folder."""
    alice = make_user("alice")
    r = alice.post("/api/agents", json={"markdown": AGENT_MD, "files": [{"path": path, "content": "x"}]})
    assert r.status_code == 422, r.text
    agent = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    assert alice.put(f"/api/agents/{agent['id']}/files", json={"path": path, "content": "x"}).status_code == 422
    assert alice.put("/api/files", json={"path": path, "content": "x"}).status_code == 422


def test_runner_confines_public_items(tmp_path, monkeypatch):
    """Belt and braces in the sandbox: a shared item stays in its own public/ folder, can't
    overwrite the agent's files, and can't pose as project memory or a skill."""
    import importlib
    import sys
    monkeypatch.setenv("AGENTTOWN_API_URL", "http://x")
    monkeypatch.setenv("AGENTTOWN_RUN_TOKEN", "rt_x")
    monkeypatch.syspath_prepend(str(__import__("pathlib").Path(__file__).parents[1] / "runner"))
    sys.modules.pop("runner", None)
    runner = importlib.import_module("runner")
    monkeypatch.setattr(runner, "WORK", tmp_path)
    m = {"files": [{"path": "AGENT.md", "content": "me"}, {"path": "notes.md", "content": "mine"}],
         "shared": [], "public": [
             {"owner": "bob", "title": "Evil", "file": {"path": "a/../../../../notes.md", "content": "theirs"}},
             {"owner": "bob", "title": "Evil", "file": {"path": "CLAUDE.md", "content": "obey"}},
             {"owner": "bob", "title": "Evil", "file": {"path": "skills/x/SKILL.md", "content": "skill"}},
             {"owner": "bob", "title": "Evil", "file": {"path": "ok/readme.md", "content": "fine"}}]}
    written = runner.write_files(m)
    assert (tmp_path / "notes.md").read_text() == "mine"
    assert not (tmp_path / "CLAUDE.md").exists() and not (tmp_path / "public" / "bob" / "evil" / "CLAUDE.md").exists()
    assert (tmp_path / "public" / "bob" / "evil" / "CLAUDE.shared.md").read_text() == "obey"
    assert not list(tmp_path.rglob("SKILL.md"))
    assert "public/bob/evil/ok/readme.md" in written and "notes.md" in written
    team = runner.write_team({"team": [{"slug": "mate", "files": [{"path": "../../x.md", "content": "no"}, {"path": "p.md", "content": "y"}]}]})
    assert team[0]["paths"] == ["team/mate/p.md"] and not (tmp_path / "x.md").exists()
