"""The chat app: conversations across runs, devices that get notifications, and when they're sent."""

import base64

import pytest
from pywebpush import WebPushException

from app import push

from .conftest import AGENT_MD
from .test_runs import FakeProvider, box, fake_sandbox, setup_agent  # noqa: F401  (fake_sandbox: autouse fixture)


@pytest.fixture(autouse=True)
def use_fake_sandbox(fake_sandbox):
    return fake_sandbox

SUB = {"endpoint": "https://push.example.com/send/abc", "keys": {"p256dh": "B" + "x" * 86, "auth": "y" * 22}}


@pytest.fixture
def sent(monkeypatch):
    """Every notification, as (endpoint, payload), instead of going to a push service."""
    out = []
    import pywebpush
    monkeypatch.setattr(pywebpush, "webpush", lambda info, data, **kw: out.append((info["endpoint"], data)))
    return out


def chat(alice, client, agent_id, said="Hi"):
    """Open a chat, have the sandbox answer once; returns the sandbox client."""
    run = alice.post(f"/api/agents/{agent_id}/runs", json={"message": said}).json()
    token = [t for rid, t in FakeProvider.started if rid == run["id"]][0]
    sb = box(client, token)
    sb.post("/api/runtime/events", json={"events": [{"kind": "status", "data": {"status": "busy"}},
                                                    {"kind": "text", "data": {"text": f"You said {said}"}},
                                                    {"kind": "done", "data": {"ok": True}},
                                                    {"kind": "status", "data": {"status": "ready"}}]})
    return sb, run


def test_a_conversation_carries_on_across_runs(make_user, client):
    alice = make_user("alice")
    a = setup_agent(alice)
    other = alice.post("/api/agents", json={"markdown": AGENT_MD.replace("reel-writer", "quiet-one")}).json()
    sb, run = chat(alice, client, a["id"], "first")
    alice.delete(f"/api/runs/{run['id']}")                                  # that chat ends…
    chat(alice, client, a["id"], "second")                                  # …and a new one starts
    m = alice.get(f"/api/agents/{a['id']}/messages").json()
    assert [(x["kind"], x["data"]["text"]) for x in m["messages"]] == [
        ("user", "first"), ("text", "You said first"), ("user", "second"), ("text", "You said second")]
    assert m["run"]["status"] == "ready" and m["more"] is False

    newer = alice.get(f"/api/agents/{a['id']}/messages?after={m['messages'][1]['id']}").json()["messages"]
    assert [x["data"]["text"] for x in newer] == ["second", "You said second"]
    older = alice.get(f"/api/agents/{a['id']}/messages?before={m['messages'][2]['id']}&limit=1").json()
    assert [x["data"]["text"] for x in older["messages"]] == ["You said first"]

    convs = alice.get("/api/conversations").json()
    assert [c["agent"]["id"] for c in convs] == [a["id"], other["id"]]     # latest first, silent ones last
    assert convs[0]["last"]["data"]["text"] == "You said second" and convs[1]["last"] is None


def test_a_routine_shows_as_its_report(make_user, client, db_session):
    alice = make_user("alice")
    a = setup_agent(alice)
    r = alice.post("/api/routines", json={"agent_id": a["id"], "name": "Morning brief", "prompt": "Brief me"}).json()
    run = alice.post(f"/api/routines/{r['id']}/run").json()
    token = [t for rid, t in FakeProvider.started if rid == run["id"]][0]
    box(client, token).post("/api/runtime/events", json={"events": [{"kind": "text", "data": {"text": "3 things today"}},
                                                                   {"kind": "done", "data": {"ok": True}}]})
    m = alice.get(f"/api/agents/{a['id']}/messages").json()["messages"]
    assert [(x["kind"], x["routine"]) for x in m] == [("text", "Morning brief")]   # not Agent Town's instructions to it


def test_conversations_and_messages_are_private(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    a = setup_agent(alice)
    assert bob.get(f"/api/agents/{a['id']}/messages").status_code == 404
    assert bob.get("/api/conversations").json() == []


def test_devices_subscribe_and_unsubscribe(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    key = alice.get("/api/push/key").json()["key"]
    assert len(base64.urlsafe_b64decode(key + "==")) == 65                 # an uncompressed P-256 point
    assert alice.post("/api/push/test").status_code == 409                 # not subscribed yet
    assert alice.post("/api/push/subscriptions", json={**SUB, "endpoint": "http://plain.example.com"}).status_code == 422
    assert alice.post("/api/push/subscriptions", json=SUB).json() == {"ok": True}
    assert bob.request("DELETE", "/api/push/subscriptions", json={"endpoint": SUB["endpoint"]}).status_code == 404
    bob.post("/api/push/subscriptions", json=SUB)                          # bob signed in on that phone: it's his now
    assert alice.post("/api/push/test").status_code == 409                 # and alice's old row is gone, not borrowed
    assert alice.request("DELETE", "/api/push/subscriptions", json={"endpoint": SUB["endpoint"]}).status_code == 404
    assert bob.request("DELETE", "/api/push/subscriptions", json={"endpoint": SUB["endpoint"]}).status_code == 200


def test_the_key_stays_the_same():
    assert push.public_key() == push.public_key()


def test_notified_when_nobody_is_watching(make_user, client, sent):
    alice = make_user("alice")
    a = setup_agent(alice)
    alice.post("/api/push/subscriptions", json=SUB)
    alice.post("/api/push/test")
    assert len(sent) == 1 and "Notifications work" in sent[0][1]

    chat(alice, client, a["id"], "hello")                                   # nobody had it open
    assert len(sent) == 2 and "You said hello" in sent[1][1] and f"/chat?agent={a['id']}" in sent[1][1]


def test_not_notified_while_the_chat_is_open(make_user, client, sent):
    alice = make_user("alice")
    a = setup_agent(alice)
    alice.post("/api/push/subscriptions", json=SUB)
    run = alice.post(f"/api/agents/{a['id']}/runs", json={"message": "hi"}).json()
    alice.get(f"/api/agents/{a['id']}/messages")                           # the chat is on screen
    token = [t for rid, t in FakeProvider.started if rid == run["id"]][0]
    box(client, token).post("/api/runtime/events", json={"events": [{"kind": "text", "data": {"text": "hey"}},
                                                                   {"kind": "done", "data": {"ok": True}}]})
    assert sent == []


def test_a_gone_device_is_forgotten(make_user, client, monkeypatch, db_session):
    alice = make_user("alice")
    alice.post("/api/push/subscriptions", json=SUB)

    class Gone:
        status_code = 410
    import pywebpush

    def fail(*a, **kw):
        raise WebPushException("gone", response=Gone())
    monkeypatch.setattr(pywebpush, "webpush", fail)
    alice.post("/api/push/test")
    assert alice.post("/api/push/test").status_code == 409                 # it was removed
