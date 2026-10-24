from fastapi.testclient import TestClient

from app import mcp_client
from app.routers import mcp as mcp_router
from dev.demo_mcp_server import app as demo_app

from .conftest import AGENT_MD

# ---- auth ------------------------------------------------------------------------------

def test_signup_login_logout(client):
    r = client.post("/api/auth/signup", json={"email": "A@Example.com", "username": "alice",
                                              "password": "correct horse battery"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").json()["username"] == "alice"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").json() is None
    assert client.post("/api/auth/login", json={"login": "a@example.com", "password": "nope-nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"login": "alice", "password": "correct horse battery"}).status_code == 200
    assert client.get("/api/auth/me").json()["email"] == "a@example.com"


def test_duplicate_signup(client, make_user):
    make_user("alice")
    r = client.post("/api/auth/signup", json={"email": "alice@example.com", "username": "other",
                                              "password": "correct horse battery"})
    assert r.status_code == 409


def test_writes_need_a_session_and_same_origin(client, make_user):
    assert client.post("/api/agents", json={"markdown": AGENT_MD}).status_code == 401
    alice = make_user("alice")
    r = alice.post("/api/agents", json={"markdown": AGENT_MD}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# ---- agents are private until shared ---------------------------------------------------------

def test_agent_from_frontmatter_and_privacy(client, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    a = alice.post("/api/agents", json={"markdown": AGENT_MD,
                                        "files": [{"path": "playbook.md", "content": "a\nb\nc\n"}]}).json()
    assert a["name"] == "reel-writer" and a["description"] == "Scripts short videos."
    assert [f["path"] for f in a["files"]] == ["AGENT.md", "playbook.md"]
    assert a["files"][1]["lines"] == 3

    assert bob.get(f"/api/agents/{a['id']}").status_code == 404
    assert client.get(f"/api/agents/{a['id']}").status_code == 404
    assert bob.get("/api/city").json()["agents"] == []
    assert bob.patch(f"/api/agents/{a['id']}", json={"name": "mine now"}).status_code == 404
    assert bob.delete(f"/api/agents/{a['id']}").status_code == 404


def test_town_positions_are_private(client, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    assert alice.get("/api/city").json()["town"] == {}
    r = alice.put("/api/account/town", json={"positions": {"agent:1": [3.456, -7], "files": [0, 12]}})
    assert r.status_code == 200 and r.json()["town"] == {"agent:1": [3.46, -7], "files": [0, 12]}
    assert alice.get("/api/city").json()["town"]["agent:1"] == [3.46, -7]
    assert bob.get("/api/city").json()["town"] == {}
    assert client.get("/api/city").json()["town"] == {}
    assert client.put("/api/account/town", json={"positions": {}}).status_code == 401
    assert alice.put("/api/account/town", json={"positions": {"house:1": [0, 0]}}).status_code == 422
    assert alice.put("/api/account/town", json={"positions": {"room:7": [-40, 12], "room:agents": [5, 5], "room:empty-2": [0, -30]}}).status_code == 200
    assert alice.put("/api/account/town", json={"positions": {"room:lobby": [0, 0]}}).status_code == 422
    assert alice.put("/api/account/town", json={"positions": {"agent:1": [9999, 0]}}).status_code == 422
    assert alice.put("/api/account/town", json={"positions": {}}).json()["town"] == {}


def test_empty_colonies(client, make_user):
    """A colony can be named before any agents are in it; it's theirs alone."""
    alice, bob = make_user("alice"), make_user("bob")
    assert alice.get("/api/city").json()["empty_colonies"] == []
    r = alice.put("/api/account/empty-colonies", json={"colonies": [
        {"name": "  Home   stuff ", "about": "bills"}, {"name": "home stuff"}, {"name": "Outreach"}]})
    assert r.status_code == 200
    assert r.json()["empty_colonies"] == [{"name": "Home stuff", "about": "bills"}, {"name": "Outreach", "about": ""}]
    assert alice.get("/api/city").json()["empty_colonies"][1]["name"] == "Outreach"
    assert bob.get("/api/city").json()["empty_colonies"] == []
    assert client.put("/api/account/empty-colonies", json={"colonies": []}).status_code == 401
    assert alice.put("/api/account/empty-colonies", json={"colonies": [{"name": ""}]}).status_code == 422
    assert alice.put("/api/account/empty-colonies", json={"colonies": [{"name": "x" * 61}]}).status_code == 422


def test_share_agent_and_file(client, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    a = alice.post("/api/agents", json={"markdown": AGENT_MD,
                                        "files": [{"path": "playbook.md", "content": "tips\n"}]}).json()
    playbook = a["files"][1]["id"]

    assert bob.post("/api/public", json={"kind": "agent", "agent_id": a["id"]}).status_code == 404
    s = alice.post("/api/public", json={"kind": "agent", "agent_id": a["id"], "note": "use for reels"}).json()
    alice.post("/api/public", json={"kind": "file", "file_id": playbook})

    shares = client.get("/api/public").json()
    assert [x["kind"] for x in shares] == ["agent", "file"] and shares[0]["owner"] == "alice"
    assert client.get(f"/api/agents/{a['id']}").json()["files"][0]["content"].startswith("---")

    assert bob.delete(f"/api/public/{s['id']}").status_code == 404
    assert alice.delete(f"/api/public/{s['id']}").status_code == 200
    assert client.get(f"/api/agents/{a['id']}").status_code == 404


# ---- tools ------------------------------------------------------------------------------

def demo_check(monkeypatch):
    """Point connection checks at the in-process demo MCP server."""
    real = mcp_client.check
    monkeypatch.setattr(mcp_router.mcp_client, "check",
                        lambda url, headers=None, allow_private=False: real(url, headers, allow_private=True,
                                                                            client=TestClient(demo_app)))


def test_mcp_check_json_and_sse():
    for url in ("http://testserver/mcp", "http://testserver/mcp?sse=1"):
        r = mcp_client.check(url, allow_private=True, client=TestClient(demo_app))
        assert r.status == "connected", r.detail
        assert r.server_name == "demo-mcp"
        assert [t["name"] for t in r.tools] == ["echo", "utc_now", "word_count"]


def test_mcp_auth_required(monkeypatch):
    monkeypatch.setenv("DEMO_MCP_TOKEN", "s3cret")
    r = mcp_client.check("http://testserver/mcp", allow_private=True, client=TestClient(demo_app))
    assert r.status == "auth_required"
    r = mcp_client.check("http://testserver/mcp", {"Authorization": "Bearer s3cret"}, allow_private=True, client=TestClient(demo_app))
    assert r.status == "connected"


def test_ssrf_guard():
    r = mcp_client.check("http://127.0.0.1:9/mcp", allow_private=False)
    assert r.status == "error" and "private address" in r.detail


def test_grants_and_manifest(monkeypatch, make_user):
    demo_check(monkeypatch)
    alice, bob = make_user("alice"), make_user("bob")
    conn = alice.post("/api/mcp", json={"name": "demo", "url": "http://testserver/mcp",
                                        "auth_header": "Bearer xyz"}).json()
    assert conn["status"] == "connected" and len(conn["tools"]) == 3
    assert conn["has_auth"] and "auth_header" not in conn

    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    other = alice.post("/api/agents", json={"markdown": AGENT_MD, "name": "helper"}).json()
    r = alice.put(f"/api/agents/{a['id']}/grants",
                  json={"grants": [{"connection_id": conn["id"], "tool_name": "echo"}]})
    assert r.json()["grants"] == [{"connection_id": conn["id"], "tool_name": "echo"}]
    assert alice.put(f"/api/agents/{a['id']}/grants", json={"grants": [
        {"connection_id": conn["id"], "tool_name": "rm_rf"}]}).status_code == 422

    b = bob.post("/api/agents", json={"markdown": AGENT_MD}).json()
    assert bob.put(f"/api/agents/{b['id']}/grants",
                   json={"grants": [{"connection_id": conn["id"]}]}).status_code == 404

    alice.post("/api/public", json={"kind": "agent", "agent_id": other["id"], "note": "ask me"})
    alice.post("/api/public", json={"kind": "agent", "agent_id": a["id"], "allow_agent_use": False})

    m = alice.get(f"/api/agents/{a['id']}/manifest").json()
    assert m["instructions"].startswith("# Reel writer")
    assert [t["name"] for t in m["tools"][0]["tools"]] == ["echo"]
    assert "Bearer" not in str(m)
    assert [p["title"] for p in m["public"]] == ["helper"]  # not itself, not a no-agent-use share

    bm = bob.get(f"/api/agents/{b['id']}/manifest").json()
    assert [t["server"] for t in bm["tools"]] == ["mail"] and [p["title"] for p in bm["public"]] == ["helper"]
    bob.patch(f"/api/agents/{b['id']}", json={"can_use_public": False})
    assert bob.get(f"/api/agents/{b['id']}/manifest").json()["public"] == []
    assert bob.get(f"/api/agents/{a['id']}/manifest").status_code == 404


def test_stdio_needs_sandbox(make_user):
    alice = make_user("alice")
    c = alice.post("/api/mcp", json={"name": "gmail", "transport": "stdio",
                                     "command": "npx @gongrzhe/server-gmail-autoauth-mcp"}).json()
    assert c["status"] == "needs_sandbox"


def _agent(c, name):
    return c.post("/api/agents", json={"markdown": AGENT_MD.replace("reel-writer", name)}).json()


def test_naming_a_colony_fills_the_empty_one_of_that_name(make_user):
    """Whichever way a lead's colony gets its name, an empty colony named the same becomes it: the map
    never shows "Outreach" twice. And an empty colony can't take a name a lead already has."""
    alice = make_user("alice")
    alice.put("/api/account/empty-colonies", json={"colonies": [{"name": "Outreach", "about": "Posts and cold email"},
                                                                {"name": "Home", "about": ""}]})
    lead, m = _agent(alice, "lead"), _agent(alice, "member")
    alice.put(f"/api/agents/{lead['id']}/team", json={"member_ids": [m["id"]]})
    # the Colonies screen (PATCH) with a different case: the empty one's spelling and "about" are kept
    got = alice.patch(f"/api/agents/{lead['id']}", json={"colony_name": "outreach"}).json()
    assert (got["colony_name"], got["colony_about"]) == ("Outreach", "Posts and cold email")
    assert [c["name"] for c in alice.get("/api/city").json()["empty_colonies"]] == ["Home"]
    # a lead's name can't be taken by a new empty colony
    r = alice.put("/api/account/empty-colonies", json={"colonies": [{"name": "Home"}, {"name": "OUTREACH"}]})
    assert r.status_code == 422 and "Outreach" in r.json()["detail"]
    assert [c["name"] for c in alice.get("/api/city").json()["empty_colonies"]] == ["Home"]
    # the market: Maya's team fills an empty colony called Company
    alice.put("/api/account/empty-colonies", json={"colonies": [{"name": "Home"}, {"name": "company", "about": "my startup"}]})
    maya = alice.post("/api/marketplace/maya/install").json()["agent"]
    assert (maya["colony_name"], maya["colony_about"]) == ("company", "my startup")
    assert [c["name"] for c in alice.get("/api/city").json()["empty_colonies"]] == ["Home"]
