"""LinkedIn: signing in, the tools a run may call, and posts that go out at once or wait for the person.
LinkedIn itself is faked with httpx.MockTransport."""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import linkedin, sandbox
from app.config import settings
from app.models import OAuthAccount

from .conftest import AGENT_MD, FakeProvider
from .test_google import rpc


class FakeLinkedIn:
    def __init__(self):
        self.posts, self.revoked = [], []
        self.post_status = 201

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.startswith(linkedin.TOKEN_URL):
            form = parse_qs(req.content.decode())
            assert form["code"] == ["the-code"] and form["client_secret"] == ["test-secret"]
            return httpx.Response(200, json={"access_token": "li-at-1", "expires_in": 5184000,
                                             "scope": "email,openid,profile,w_member_social"})
        if url.startswith(linkedin.REVOKE_URL):
            self.revoked.append(parse_qs(req.content.decode())["token"][0])
            return httpx.Response(200)
        assert req.headers["authorization"] == "Bearer li-at-1"
        if url.startswith(linkedin.USERINFO_URL):
            return httpx.Response(200, json={"sub": "li-123", "name": "Alice Example", "email": "alice@example.com",
                                             "picture": "https://media.example.com/alice.jpg"})
        if url.startswith(linkedin.POSTS_URL):
            assert req.headers["linkedin-version"] == settings().linkedin_api_version
            assert req.headers["x-restli-protocol-version"] == "2.0.0"
            if self.post_status >= 400:
                return httpx.Response(self.post_status, json={"message": "Nope"})
            self.posts.append(json.loads(req.content))
            return httpx.Response(201, headers={"x-restli-id": f"urn:li:share:{len(self.posts)}"})
        return httpx.Response(404)


@pytest.fixture
def fake_linkedin(monkeypatch):
    fl = FakeLinkedIn()
    monkeypatch.setattr(linkedin, "http", lambda: httpx.Client(transport=httpx.MockTransport(fl)))
    monkeypatch.setattr(settings(), "linkedin_client_id", "li-client")
    monkeypatch.setattr(settings(), "linkedin_client_secret", "test-secret")
    monkeypatch.setattr(settings(), "app_url", "http://testserver")
    return fl


def connect(c, agent_id=None):
    r = c.get("/api/connect/linkedin/start" + (f"?agent={agent_id}" if agent_id else ""), follow_redirects=False)
    assert r.status_code == 303
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_uri"] == ["http://testserver/api/connect/linkedin/callback"] and "w_member_social" in q["scope"][0]
    return c.get(f"/api/connect/linkedin/callback?state={q['state'][0]}&code=the-code", follow_redirects=False)


def in_a_run(alice, client, monkeypatch, policy=None):
    """alice's agent with LinkedIn (and these post rules), in a running chat: the sandbox's client."""
    FakeProvider.started = []
    monkeypatch.setattr(sandbox, "provider", lambda name=None: FakeProvider())
    alice.post("/api/account/credentials", json={"provider": "anthropic", "kind": "subscription", "secret": "sk-ant-oat01-" + "x" * 40})
    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    assert connect(alice, a["id"]).headers["location"] == "http://testserver/?connected=linkedin"
    if policy:
        assert alice.patch(f"/api/agents/{a['id']}", json={"post_policy": policy}).status_code == 200
    alice.post(f"/api/agents/{a['id']}/runs")
    li = next(c for c in alice.get("/api/city").json()["connections"] if c["name"] == "LinkedIn")
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {FakeProvider.started[-1][1]}"
    return client, li["id"], client.get("/api/runtime/setup").json()["run_id"]


def post(sb, conn_id, text="Shipped it (finally) #agents"):
    return rpc(sb, conn_id, "tools/call", {"name": "create_post", "arguments": {"text": text}}).json()["result"]


def the_post(alice, run_id):
    [e] = [e for e in alice.get(f"/api/runs/{run_id}/events").json()["events"] if e["kind"] == "approval"]
    return e


def test_not_set_up(make_user):
    alice = make_user("alice")
    assert alice.get("/api/connect/linkedin").json()["configured"] is False
    assert alice.get("/api/connect/linkedin/start", follow_redirects=False).status_code == 404


def test_sign_in_makes_a_connection_and_keeps_the_token_encrypted(make_user, fake_linkedin, db_session):
    alice = make_user("alice")
    assert connect(alice).headers["location"] == "http://testserver/?connected=linkedin"
    [acct] = alice.get("/api/connect/linkedin").json()["accounts"]
    assert acct["email"] == "alice@example.com" and acct["status"] == "connected"
    [conn] = alice.get("/api/city").json()["connections"]
    assert conn["name"] == "LinkedIn" and [t["name"] for t in conn["tools"]] == ["create_post", "get_profile"]
    with db_session() as s:
        row = s.query(OAuthAccount).one()
        assert "li-at-1" not in row.access_token_enc and row.scopes == "email openid profile w_member_social"
    connect(alice)                                           # again: nothing doubles
    assert len(alice.get("/api/city").json()["connections"]) == 1
    assert alice.get("/api/connect/google").json()["accounts"] == []    # not mistaken for a Google account


def test_callback_must_come_back_to_the_same_person(make_user, fake_linkedin):
    alice, bob = make_user("alice"), make_user("bob")
    r = alice.get("/api/connect/linkedin/start", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = bob.get(f"/api/connect/linkedin/callback?state={state}&code=the-code", follow_redirects=False)
    assert "connect_error" in r.headers["location"] and bob.get("/api/connect/linkedin").json()["accounts"] == []
    r = alice.get(f"/api/connect/linkedin/callback?state={state}&error=user_cancelled_login", follow_redirects=False)
    assert "cancelled" in r.headers["location"]


def test_posts_at_once_by_default(make_user, client, fake_linkedin, monkeypatch):
    alice = make_user("alice")
    sb, li, run_id = in_a_run(alice, client, monkeypatch)
    setup = sb.get("/api/runtime/setup").json()
    assert setup["manifest"]["tools"][0]["server"] == "linkedin" and "li-at-1" not in json.dumps(setup)
    profile = json.loads(rpc(sb, li, "tools/call", {"name": "get_profile", "arguments": {}}).json()["result"]["content"][0]["text"])
    assert profile["name"] == "Alice Example"

    out = post(sb, li)
    assert "Posted on their LinkedIn: https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A1/" in out["content"][0]["text"]
    [sent] = fake_linkedin.posts
    assert sent["author"] == "urn:li:person:li-123" and sent["visibility"] == "PUBLIC"
    assert sent["commentary"] == r"Shipped it \(finally\) {hashtag|\#|agents}"
    e = the_post(alice, run_id)
    assert e["data"]["type"] == "post" and e["data"]["state"] == "sent" and e["data"]["auto"] is True
    assert post(sb, li, "")["isError"] and post(sb, li, "x" * 3001)["isError"]


def test_ask_first_waits_for_the_person(make_user, client, fake_linkedin, monkeypatch):
    alice, bob = make_user("alice"), make_user("bob")
    sb, li, run_id = in_a_run(alice, client, monkeypatch, {"mode": "ask"})
    assert "Not posted yet" in post(sb, li)["content"][0]["text"] and fake_linkedin.posts == []
    e = the_post(alice, run_id)
    assert e["data"]["state"] == "pending" and "rules" in e["data"]["why"]
    assert bob.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": True}).status_code == 404
    r = alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": True})
    assert r.json()["data"]["state"] == "sent" and len(fake_linkedin.posts) == 1
    note = [x for x in alice.get(f"/api/runs/{run_id}/events").json()["events"] if x["kind"] == "notice"][-1]
    assert "pressed Post" in note["data"]["text"] and "linkedin.com/feed/update" in note["data"]["text"]


def test_a_run_that_read_something_untrusted_asks_first(make_user, client, fake_linkedin, monkeypatch, db_session):
    """Even on "post at once": a stranger's email or a web page may have put the words there."""
    from app.models import Run
    alice = make_user("alice")
    sb, li, run_id = in_a_run(alice, client, monkeypatch)
    with db_session() as s:
        s.get(Run, run_id).untrusted = "it read a web page"
        s.commit()
    assert "Not posted yet" in post(sb, li)["content"][0]["text"] and fake_linkedin.posts == []
    assert the_post(alice, run_id)["data"]["why"] == "It read a web page"


def test_dont_post(make_user, client, fake_linkedin, monkeypatch):
    alice = make_user("alice")
    sb, li, run_id = in_a_run(alice, client, monkeypatch, {"mode": "ask"})
    post(sb, li)
    e = the_post(alice, run_id)
    assert alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": False}).json()["data"]["state"] == "declined"
    assert fake_linkedin.posts == []
    note = [x for x in alice.get(f"/api/runs/{run_id}/events").json()["events"] if x["kind"] == "notice"][-1]
    assert "chose not to send the LinkedIn post" in note["data"]["text"] and "Drafts" not in note["data"]["text"]


def test_daily_limit_then_it_asks(make_user, client, fake_linkedin, monkeypatch):
    alice = make_user("alice")
    sb, li, _ = in_a_run(alice, client, monkeypatch)
    for i in range(5):
        assert "Posted" in post(sb, li, f"Post {i}")["content"][0]["text"]
    assert "already posted 5 times" in post(sb, li, "One more")["content"][0]["text"] and len(fake_linkedin.posts) == 5


def test_a_failed_post_waits_for_the_person(make_user, client, fake_linkedin, monkeypatch):
    alice = make_user("alice")
    sb, li, run_id = in_a_run(alice, client, monkeypatch)
    fake_linkedin.post_status = 422
    assert "didn't take it" in post(sb, li)["content"][0]["text"]
    e = the_post(alice, run_id)
    assert e["data"]["state"] == "pending" and "Nope" in e["data"]["why"]


def test_an_expired_sign_in_says_connect_again(make_user, client, fake_linkedin, monkeypatch, db_session):
    alice = make_user("alice")
    sb, li, _ = in_a_run(alice, client, monkeypatch)
    with db_session() as s:                                   # the 60 days are up
        s.query(OAuthAccount).one().expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    out = rpc(sb, li, "tools/call", {"name": "get_profile", "arguments": {}}).json()["result"]
    assert out["isError"] and "connect LinkedIn again" in out["content"][0]["text"]
    sb.headers.pop("Authorization")
    [conn] = alice.get("/api/city").json()["connections"]
    assert conn["status"] == "auth_required"


def test_rules_are_shown_and_validated(make_user):
    alice = make_user("alice")
    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    assert a["post_policy"] == {"mode": "auto"}
    assert alice.patch(f"/api/agents/{a['id']}", json={"post_policy": {"mode": "sometimes"}}).status_code == 422


def test_disconnect_revokes_and_removes_access(make_user, fake_linkedin):
    alice, bob = make_user("alice"), make_user("bob")
    connect(alice)
    [acct] = alice.get("/api/connect/linkedin").json()["accounts"]
    assert bob.delete(f"/api/connect/linkedin/{acct['id']}").status_code == 404
    assert alice.delete(f"/api/connect/linkedin/{acct['id']}").json() == {"ok": True}
    assert fake_linkedin.revoked == ["li-at-1"] and alice.get("/api/city").json()["connections"] == []
