"""Read-only web APIs: Agent Town calls them for a run, GET only, with a header the sandbox never sees.
The API itself is faked with httpx.MockTransport."""

import json

import httpx
import pytest

from app import sandbox, webapi
from app.config import settings
from app.models import McpConnection

from .conftest import AGENT_MD, FakeProvider

BASE = "https://api.example.com/api/v1/admin-s3cret"
HEADER = "Bearer rva_test-token"


class FakeApi:
    def __init__(self):
        self.seen: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req)
        if req.headers.get("authorization") != HEADER:
            return httpx.Response(401, json={"detail": "admin agent token required"})
        if req.url.path == "/api/v1/admin-s3cret/dashboard":
            return httpx.Response(200, json={"signups_last_30d": 42, "mau": 310})
        if req.url.path == "/api/v1/admin-s3cret/moved":
            return httpx.Response(302, headers={"location": "https://elsewhere.example.net/steal"})
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def fake_api(monkeypatch):
    fa = FakeApi()
    monkeypatch.setattr(webapi, "http", lambda: httpx.Client(transport=httpx.MockTransport(fa), follow_redirects=False))
    monkeypatch.setattr(settings(), "allow_private_mcp_hosts", True)      # no DNS lookups in tests
    return fa


def connect(alice):
    r = alice.post("/api/mcp", json={"name": "Example admin", "transport": "web", "url": BASE, "auth_header": HEADER})
    assert r.status_code == 200, r.text
    return r.json()


def run_with(alice, client, monkeypatch, conn):
    FakeProvider.started = []
    monkeypatch.setattr(sandbox, "provider", lambda name=None: FakeProvider())
    alice.post("/api/account/credentials", json={"provider": "anthropic", "kind": "subscription", "secret": "sk-ant-oat01-" + "x" * 40})
    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    alice.put(f"/api/agents/{a['id']}/grants", json={"grants": [{"connection_id": conn["id"], "tool_name": None}]})
    alice.post(f"/api/agents/{a['id']}/runs")
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {FakeProvider.started[0][1]}"
    return client


def call(c, conn_id, args):
    r = c.post(f"/api/runtime/mcp/{conn_id}", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                    "params": {"name": "get", "arguments": args}})
    return r.json()["result"]


def test_connecting_lists_one_read_only_tool(make_user, fake_api):
    conn = connect(make_user("alice"))
    assert conn["status"] == "connected" and conn["has_auth"]
    assert [t["name"] for t in conn["tools"]] == ["get"]
    assert fake_api.seen == []                                 # connecting doesn't call the API


def test_a_run_reads_the_api_through_agent_town(make_user, client, fake_api, monkeypatch):
    alice = make_user("alice")
    conn = connect(alice)
    sb = run_with(alice, client, monkeypatch, conn)

    setup = sb.get("/api/runtime/setup").json()
    [tool] = [t for t in setup["manifest"]["tools"] if t["server"] != "mail"]      # every front door has mail too
    assert tool["hosted"] and tool["url"].endswith(f"/api/runtime/mcp/{conn['id']}") and not tool["server"]   # named after the connection
    assert setup["secrets"] == {}                              # the header stays here
    assert "rva_test-token" not in json.dumps(setup) and "s3cret" not in json.dumps(setup)

    out = call(sb, conn["id"], {"path": "/dashboard", "query": {"days": 30, "fresh": True}})
    assert out["content"][0]["text"].startswith("HTTP 200") and '"mau":310' in out["content"][0]["text"]
    req = fake_api.seen[-1]
    assert req.method == "GET" and req.url.params["days"] == "30" and req.url.params["fresh"] == "true"


@pytest.mark.parametrize("path", ["dashboard", "//evil.example.net/x", "/../other", "/a/../../b", "/%2e%2e/admin", "/a/%2E%2E/%2e%2e/b", "/x?y=1", "/x#y", "/x\\y"])
def test_paths_stay_under_the_base_url(make_user, client, fake_api, monkeypatch, path):
    alice = make_user("alice")
    conn = connect(alice)
    out = call(run_with(alice, client, monkeypatch, conn), conn["id"], {"path": path})
    assert out.get("isError") and fake_api.seen == []


def test_redirects_are_not_followed(make_user, client, fake_api, monkeypatch):
    alice = make_user("alice")
    conn = connect(alice)
    out = call(run_with(alice, client, monkeypatch, conn), conn["id"], {"path": "/moved"})
    assert out["content"][0]["text"].startswith("HTTP 302")
    assert [r.url.host for r in fake_api.seen] == ["api.example.com"]


def test_a_web_connection_needs_a_url(make_user):
    r = make_user("alice").post("/api/mcp", json={"name": "x", "transport": "web"})
    assert r.status_code == 422


def test_the_url_is_kept_secret(make_user, client, fake_api, monkeypatch, db_session):
    alice = make_user("alice")
    conn = connect(alice)
    assert conn["url"] == "https://api.example.com/…"         # its key is in the path
    assert "s3cret" not in json.dumps(alice.get("/api/mcp").json())
    with db_session() as db:
        row = db.get(McpConnection, conn["id"])
        assert "s3cret" not in row.url and "s3cret" not in row.url_enc and webapi.base_url(row) == BASE

    out = call(run_with(alice, client, monkeypatch, conn), conn["id"], {"path": "/dashboard"})
    assert out["content"][0]["text"].startswith("HTTP 200") and "310" in out["content"][0]["text"]


def test_changing_the_url(make_user, fake_api):
    alice = make_user("alice")
    conn = connect(alice)
    r = alice.patch(f"/api/mcp/{conn['id']}", json={"url": "https://other.example.com/v2/k3y"})
    assert r.status_code == 200 and r.json()["url"] == "https://other.example.com/…"
    assert alice.patch(f"/api/mcp/{conn['id']}", json={"url": ""}).status_code == 422
    assert alice.patch(f"/api/mcp/{conn['id']}", json={"name": "Renamed"}).json()["url"] == "https://other.example.com/…"


@pytest.mark.parametrize("url,seen", [
    ("https://api.example.com", "https://api.example.com"),
    ("https://api.example.com/", "https://api.example.com"),
    ("https://u:pw@api.example.com/v1", "https://api.example.com/…"),
    ("https://api.example.com?key=1", "https://api.example.com/…"),
])
def test_shown(url, seen):
    assert webapi.shown(url) == seen
