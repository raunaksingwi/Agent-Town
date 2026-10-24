"""Connecting any MCP server: signing in to it, other headers, a command's environment, and
importing a config someone already has (Claude Code, Claude Desktop, VS Code, Codex)."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import mcp_auth, mcp_client, mcp_import
from app.config import settings
from app.models import McpConnection
from app.routers import mcp as mcp_router
from dev.demo_mcp_server import app as demo_app

from .test_runs import box, fake_sandbox, setup_agent  # noqa: F401  (fake_sandbox: a fixture)


@pytest.fixture
def demo(monkeypatch):
    """Every request Agent Town makes goes to the in-process demo server, which wants a sign-in."""
    monkeypatch.setenv("DEMO_MCP_OAUTH", "1")
    monkeypatch.setattr(settings(), "allow_private_mcp_hosts", True)       # no DNS lookups in tests
    monkeypatch.setattr(settings(), "app_url", "http://testserver")        # where the sign-in comes back to
    monkeypatch.setattr(mcp_auth, "http", lambda: TestClient(demo_app))
    real = mcp_client.check
    monkeypatch.setattr(mcp_router.mcp_client, "check",
                        lambda url, headers=None, allow_private=False: real(url, headers, allow_private=True,
                                                                            client=TestClient(demo_app)))


def sign_in(user: TestClient, conn_id: int, agent: int | None = None):
    r = user.get(f"/api/connect/mcp/{conn_id}/start" + (f"?agent={agent}" if agent else ""), follow_redirects=False)
    assert r.status_code == 303, r.text
    to_app = urlparse(r.headers["location"])
    assert to_app.path == "/authorize" and parse_qs(to_app.query)["resource"] == ["http://testserver/mcp"]
    back = TestClient(demo_app).get(r.headers["location"], follow_redirects=False)  # the app approves
    return user.get(back.headers["location"], follow_redirects=False)              # and sends them back


def test_signing_in_to_an_mcp_server(demo, make_user, client, fake_sandbox, db_session):
    alice, bob = make_user("alice"), make_user("bob")
    conn = alice.post("/api/mcp", json={"name": "demo", "url": "http://testserver/mcp"}).json()
    assert conn["status"] == "auth_required" and conn["sign_in"] == "available"
    assert "Sign in with testserver" in conn["status_detail"]

    assert bob.get(f"/api/connect/mcp/{conn['id']}/start", follow_redirects=False).status_code == 404
    a = setup_agent(alice)
    done = sign_in(alice, conn["id"], agent=a["id"])
    assert done.status_code == 303 and "connected=demo" in done.headers["location"]

    conn = alice.get("/api/mcp").json()[0]
    assert conn["status"] == "connected" and conn["sign_in"] == "signed_in" and len(conn["tools"]) == 3
    assert "token" not in str(conn).lower().replace("tokens", "")
    assert alice.get(f"/api/agents/{a['id']}").json()["grants"] == [{"connection_id": conn["id"], "tool_name": None}]

    alice.post(f"/api/agents/{a['id']}/runs")
    sb = box(client, fake_sandbox.started[0][1])
    auth = sb.get("/api/runtime/setup").json()["secrets"][str(conn["id"])]["headers"]["Authorization"]
    assert auth.startswith("Bearer ") and "Bearer" not in str(alice.get(f"/api/agents/{a['id']}/manifest").json())

    # nearly expired: the next turn gets a fresh token, without anyone signing in again
    with db_session() as s:
        c = s.get(McpConnection, conn["id"])
        mcp_auth.set_oauth(c, {**mcp_auth.oauth(c), "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()})
        s.commit()
    fresh = sb.get("/api/runtime/secrets").json()["secrets"][str(conn["id"])]["headers"]["Authorization"]
    assert fresh.startswith("Bearer ") and fresh != auth

    out = alice.post(f"/api/mcp/{conn['id']}/sign-out").json()
    assert out["sign_in"] == "available" and out["status"] == "auth_required"


def test_sign_in_must_start_in_the_same_browser(demo, make_user):
    alice = make_user("alice")
    conn = alice.post("/api/mcp", json={"name": "demo", "url": "http://testserver/mcp"}).json()
    r = alice.get(f"/api/connect/mcp/{conn['id']}/start", follow_redirects=False)
    back = TestClient(demo_app).get(r.headers["location"], follow_redirects=False).headers["location"]
    alice.cookies.delete("agenttown_mcp_oauth", path="/api/connect/mcp")
    assert "connect_error" in alice.get(back, follow_redirects=False).headers["location"]
    assert alice.get("/api/mcp").json()[0]["sign_in"] == "available"


def test_a_server_without_sign_in_asks_for_a_header(monkeypatch, make_user):
    monkeypatch.setenv("DEMO_MCP_TOKEN", "s3cret")
    monkeypatch.setattr(settings(), "allow_private_mcp_hosts", True)
    monkeypatch.setattr(mcp_auth, "http", lambda: TestClient(demo_app))
    real = mcp_client.check
    monkeypatch.setattr(mcp_router.mcp_client, "check",
                        lambda url, headers=None, allow_private=False: real(url, headers, allow_private=True,
                                                                            client=TestClient(demo_app)))
    alice = make_user("alice")
    conn = alice.post("/api/mcp", json={"name": "demo", "url": "http://testserver/mcp"}).json()
    assert conn["status"] == "auth_required" and conn["sign_in"] == "none"
    conn = alice.post("/api/mcp", json={"name": "demo2", "url": "http://testserver/mcp",
                                        "headers": {"Authorization": "Bearer s3cret", "X-Team": "a"}}).json()
    assert conn["status"] == "connected" and conn["header_names"] == ["Authorization", "X-Team"]
    assert "s3cret" not in str(conn)


def test_a_commands_environment_goes_only_to_its_sandbox(make_user, client, fake_sandbox):
    alice = make_user("alice")
    conn = alice.post("/api/mcp", json={"name": "files", "transport": "stdio", "command": "npx -y server-x",
                                        "env": {"API_KEY": "k-123"}}).json()
    assert conn["env_names"] == ["API_KEY"] and "k-123" not in str(conn)
    a = setup_agent(alice)
    alice.put(f"/api/agents/{a['id']}/grants", json={"grants": [{"connection_id": conn["id"], "tool_name": None}]})
    alice.post(f"/api/agents/{a['id']}/runs")
    setup = box(client, fake_sandbox.started[0][1]).get("/api/runtime/setup").json()
    assert setup["secrets"] == {str(conn["id"]): {"headers": {}, "env": {"API_KEY": "k-123"}}}
    assert "k-123" not in str(setup["manifest"])
    alice.patch(f"/api/mcp/{conn['id']}", json={"env": {}})
    assert alice.get("/api/mcp").json()[0]["env_names"] == []


CLAUDE = """{"mcpServers": {
  "notion": {"type": "http", "url": "https://mcp.notion.com/mcp"},
  "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/", "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}},
  "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/my files"], "env": {"DEBUG": "1"}},
  "off": {"command": "x", "disabled": true}
}}"""

CODEX = """
model = "gpt-5"

[mcp_servers.linear]
url = "https://mcp.linear.app/mcp"

[mcp_servers.sentry]
url = "https://mcp.sentry.dev/mcp"
bearer_token_env_var = "SENTRY_TOKEN"

[mcp_servers.time]
command = "uvx"
args = ["mcp-server-time"]
env = { TZ = "UTC" }
"""


def test_parsing_claude_codex_and_vscode_configs():
    claude = {s["name"]: s for s in mcp_import.parse(CLAUDE)}
    assert set(claude) == {"notion", "github", "fs"}
    assert claude["fs"]["command"] == "npx -y @modelcontextprotocol/server-filesystem '/my files'" and claude["fs"]["env"] == {"DEBUG": "1"}
    assert claude["github"]["warnings"] and not claude["notion"]["warnings"]

    codex = {s["name"]: s for s in mcp_import.parse(CODEX)}
    assert codex["linear"]["transport"] == "http" and codex["time"]["command"] == "uvx mcp-server-time"
    assert codex["time"]["env"] == {"TZ": "UTC"} and "SENTRY_TOKEN" in codex["sentry"]["warnings"][0]

    vscode = mcp_import.parse('{"servers": {"x": {"type": "http", "url": "https://x.example/mcp"}}}')
    assert vscode[0]["name"] == "x"
    with pytest.raises(mcp_import.NotAConfig):
        mcp_import.parse("hello")


def test_importing_a_config(monkeypatch, make_user):
    monkeypatch.setattr(mcp_router.mcp_client, "check", lambda *a, **k: mcp_client.CheckResult("connected", "ok", "s", "1", [{"name": "t"}]))
    alice = make_user("alice")
    alice.post("/api/mcp", json={"name": "notion", "transport": "stdio", "command": "x"})
    r = alice.post("/api/mcp/import", json={"text": CLAUDE}).json()
    assert [c["name"] for c in r["added"]] == ["notion 2", "github", "fs"] and r["problems"] == []
    assert r["added"][1]["header_names"] == ["Authorization"] and r["added"][1]["warnings"]
    assert alice.post("/api/mcp/import", json={"text": "{}"}).status_code == 422


def test_runner_hands_headers_env_and_skills_to_both_clis(tmp_path, monkeypatch):
    import json
    import tomllib

    from .conftest import load_runner
    runner = load_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "emit", lambda *a, **k: None)
    monkeypatch.setattr(runner, "system_prompt", lambda *a: "sys")
    cmds = []
    monkeypatch.setattr(runner, "stream", lambda cmd, *a: (cmds.append(cmd), (0, ""))[1])
    (tmp_path / "work" / "skills" / "brief").mkdir(parents=True)
    (tmp_path / "work" / "skills" / "brief" / "SKILL.md").write_text("---\nname: brief\ndescription: d\n---\nDo it.")

    tool = {"connection": "Notion", "connection_id": 1, "transport": "http", "url": "https://mcp.notion.com/mcp",
            "command": None, "usable": True, "all_tools": True, "tools": []}
    cmd = {"connection": "fs", "connection_id": 2, "transport": "stdio", "url": None, "command": "npx -y srv '/my files'",
           "usable": True, "all_tools": False, "tools": [{"name": "read"}]}
    m = {"agent": {"name": "A", "description": ""}, "instructions": "hi", "tools": [tool, cmd], "team": []}
    first = {"1": {"headers": {"Authorization": "Bearer old", "X-Team": "a"}, "env": {}}, "2": {"headers": {}, "env": {"KEY": "k"}}}
    later = {**first, "1": {"headers": {"Authorization": "Bearer new"}, "env": {}}}
    monkeypatch.setattr(runner, "fresh_secrets", lambda: later)

    claude = runner.Claude(m, {"kind": "api_key", "secret": "k", "model": "", "thinking": ""}, first, [])
    config = json.loads((tmp_path / "home" / "mcp.json").read_text())["mcpServers"]
    assert config["notion"]["headers"] == {"Authorization": "Bearer old", "X-Team": "a"}
    assert config["fs"] == {"type": "stdio", "command": "npx", "args": ["-y", "srv", "/my files"], "env": {"KEY": "k"}}
    claude.turn("hi")
    assert json.loads((tmp_path / "home" / "mcp.json").read_text())["mcpServers"]["notion"]["headers"] == {"Authorization": "Bearer new"}
    assert "--tools=Read,Write,Edit,Glob,Grep,Skill" in cmds[0]
    assert "--allowedTools=Read,Write,Edit,Glob,Grep,Skill,mcp__notion,mcp__fs__read" in cmds[0]
    assert (tmp_path / "work" / ".claude" / "skills" / "brief" / "SKILL.md").exists()

    runner.Codex(m, {"kind": "api_key", "secret": "k", "model": "", "thinking": ""}, first, []).turn("hi")
    toml = tomllib.loads((tmp_path / "home" / ".codex" / "config.toml").read_text())["mcp_servers"]
    assert toml["notion"]["http_headers"] == {"Authorization": "Bearer new"}
    assert toml["fs"]["env"] == {"KEY": "k"} and toml["fs"]["enabled_tools"] == ["read"]
    assert (tmp_path / "home" / ".codex" / "skills" / "brief" / "SKILL.md").exists()
