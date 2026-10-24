"""Guards around the edges: the default secret, request sizes, capped replies, cross-site links, tool names."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app import mcp_client


def test_default_secret_only_runs_on_localhost(monkeypatch):
    import importlib

    from app import config, main
    monkeypatch.setattr(config.settings(), "secret_key", config.DEV_SECRET)
    monkeypatch.setattr(config.settings(), "public_url", "https://town.example.com")
    with pytest.raises(RuntimeError, match="AGENTTOWN_SECRET_KEY"):
        importlib.reload(main)
    monkeypatch.setattr(config.settings(), "public_url", "http://127.0.0.1:8000")
    importlib.reload(main)   # fine on a laptop


def test_api_docs_can_be_turned_off(monkeypatch):
    import importlib

    from app import config, main
    def served(path):   # with a built frontend, unknown paths fall through to the app's index.html
        r = TestClient(main.app).get(path)
        return r.status_code == 200 and "text/html" not in r.headers.get("content-type", "") or "swagger" in r.text.lower()
    assert served("/openapi.json") and served("/docs")
    monkeypatch.setattr(config.settings(), "api_docs", False)
    importlib.reload(main)
    assert not served("/openapi.json") and not served("/docs")
    monkeypatch.setattr(config.settings(), "api_docs", True)
    importlib.reload(main)


def test_big_bodies_are_refused(client, make_user):
    alice = make_user("alice")
    r = alice.post("/api/agents", content=b"{}", headers={"Content-Type": "application/json", "Content-Length": "3000000"})
    assert r.status_code == 413
    big = {"files": [{"path": f"f{i}.md", "content": "x" * 100_000} for i in range(30)]}   # 3 MB: fine for an import
    assert alice.post("/api/import/preview", json=big).status_code == 200
    assert alice.post("/api/agents", json={"markdown": "x" * 2_100_000}).status_code == 413


def test_replies_from_other_servers_are_capped():
    def huge(request):
        return httpx.Response(200, content=b"x" * 5_000_000, headers={"content-type": "text/plain"})
    with httpx.Client(transport=httpx.MockTransport(huge)) as c:
        r = mcp_client.fetch(c, "GET", "http://example.com/", limit=1000)
    assert r.status_code == 200 and len(r.content) == 1000


def test_sign_in_starters_refuse_cross_site_links(make_user):
    alice = make_user("alice")
    conn = alice.post("/api/mcp", json={"name": "x", "transport": "http", "url": "https://mcp.example.com/mcp"}).json()
    for path in (f"/api/connect/mcp/{conn['id']}/start", "/api/connect/google/start", "/api/connect/linkedin/start"):
        assert alice.get(path, headers={"Sec-Fetch-Site": "cross-site"}, follow_redirects=False).status_code == 403


def test_odd_tool_names_are_dropped(make_user, monkeypatch):
    from app.mcp_client import CheckResult
    from app.routers import mcp as mcp_router
    alice = make_user("alice")
    monkeypatch.setattr(mcp_router.mcp_client, "check", lambda *a, **k: CheckResult(
        "connected", "ok", server_name="s", server_version="1",
        tools=[{"name": "fine_tool"}, {"name": "x,Bash"}, {"name": "with space"}, {"name": "a.b-c"}]))
    conn = alice.post("/api/mcp", json={"name": "s", "transport": "http", "url": "https://mcp.example.com/mcp"}).json()
    assert [t["name"] for t in conn["tools"]] == ["fine_tool", "a.b-c"]
