"""Email that goes out on its own: an agent's rules, the prompt-injection check, and the undo wait.
Google is faked (test_google.FakeGoogle): this mailbox has written to sam@example.com and nobody else."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import outbox, sandbox

from .conftest import AGENT_MD, FakeProvider
from .test_google import fake_google, rpc, sign_in  # noqa: F401  (fake_google: a fixture)

AUTO = {"mode": "auto"}


@pytest.fixture(autouse=True)
def fresh_cache():
    outbox._known.clear()


def setup(alice, client, monkeypatch, policy, teammate=None):
    """alice's agent with Gmail and these rules (and a teammate with Gmail and its own), in a running chat."""
    alice.get(f"/api/connect/google/callback?state={sign_in(alice)}&code=the-code", follow_redirects=False)
    FakeProvider.started = []
    monkeypatch.setattr(sandbox, "provider", lambda name=None: FakeProvider())
    alice.post("/api/account/credentials", json={"provider": "anthropic", "kind": "subscription", "secret": "sk-ant-oat01-" + "x" * 40})
    gmail = next(c for c in alice.get("/api/city").json()["connections"] if c["name"] == "Gmail")
    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    alice.put(f"/api/agents/{a['id']}/grants", json={"grants": [{"connection_id": gmail["id"]}]})
    assert alice.patch(f"/api/agents/{a['id']}", json={"email_policy": policy}).status_code == 200
    if teammate is not None:
        b = alice.post("/api/agents", json={"markdown": AGENT_MD.replace("reel-writer", "helper")}).json()
        alice.put(f"/api/agents/{b['id']}/grants", json={"grants": [{"connection_id": gmail["id"], "tool_name": "send_email"}]})
        alice.patch(f"/api/agents/{b['id']}", json={"email_policy": teammate})
        alice.put(f"/api/agents/{a['id']}/team", json={"member_ids": [b["id"]]})
    alice.post(f"/api/agents/{a['id']}/runs")
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {FakeProvider.started[0][1]}"
    return client, gmail["id"], client.get("/api/runtime/setup").json()["run_id"]


def send(sb, conn_id, **args):
    out = rpc(sb, conn_id, "tools/call", {"name": "send_email", "arguments": {"body": "Hello", **args}})
    return out.json()["result"]["content"][0]["text"]


def the_email(alice, run_id):
    [e] = [e for e in alice.get(f"/api/runs/{run_id}/events").json()["events"] if e["kind"] == "approval"]
    return e


def later(db_session, minutes):
    db = db_session()
    try:
        return outbox.send_due(db, datetime.now(timezone.utc) + timedelta(minutes=minutes))
    finally:
        db.close()


def test_an_email_is_claimed_once(make_user, client, fake_google, monkeypatch, db_session):
    """The person's Send and the scheduler can't both deliver it, even where row locks don't exist (SQLite)."""
    from app import outbox
    from app.models import RunEvent
    sb, gmail, _ = setup(make_user("alice"), client, monkeypatch, {"mode": "ask"})
    rpc(sb, gmail, "tools/call", {"name": "send_email", "arguments": {"to": "sam@example.com", "subject": "Hi", "body": "x"}})
    with db_session() as db:
        e = db.scalar(select(RunEvent).where(RunEvent.kind == "approval"))
        assert outbox.claim(db, e) is True and e.data["state"] == "sending"
        assert outbox.claim(db, e) is False
    with db_session() as db:
        e = db.scalar(select(RunEvent).where(RunEvent.kind == "approval"))
        assert outbox.claim(db, e) is False                                      # another session sees the same


def test_asks_by_default(make_user, client, fake_google, monkeypatch, db_session):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, {})
    assert "Not sent yet" in send(sb, conn, to="sam@example.com")
    assert the_email(alice, run_id)["data"]["state"] == "pending"
    assert later(db_session, 60) == 0 and fake_google.sent == []


def test_rules_send_to_known_people_after_the_undo_wait(make_user, client, fake_google, monkeypatch, db_session):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, AUTO)
    assert "goes out in 2 minutes" in send(sb, conn, to="Sam <sam@example.com>", subject="Hi")
    e = the_email(alice, run_id)
    assert e["data"]["state"] == "scheduled" and e["data"]["auto"] is True
    assert [w["event"]["id"] for w in alice.get("/api/today").json()["outgoing"]] == [e["id"]]

    assert later(db_session, 1) == 0 and fake_google.sent == []            # still in its undo wait
    assert later(db_session, 3) == 1 and fake_google.sent == ["d1"]
    assert the_email(alice, run_id)["data"]["state"] == "sent"
    assert "as the person's rules for you allow" in sb.get("/api/runtime/inbox").json()["messages"][0]["text"]
    today = alice.get("/api/today").json()
    assert today["outgoing"] == [] and [s["event"]["id"] for s in today["sent"]] == [e["id"]]


def test_strangers_need_a_send_unless_allowed_or_anyone(make_user, client, fake_google, monkeypatch):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, AUTO)
    assert "You haven't written to new@acme.com before" in send(sb, conn, to="sam@example.com", cc="new@acme.com")
    agent_id = alice.get(f"/api/runs/{run_id}").json()["agent_id"]

    alice.patch(f"/api/agents/{agent_id}", json={"email_policy": {**AUTO, "allow": ["Acme.com"]}})   # takes effect at once
    assert "goes out" in send(sb, conn, to="new@sales.acme.com")
    assert "haven't written" in send(sb, conn, to="x@notacme.com")
    alice.patch(f"/api/agents/{agent_id}", json={"email_policy": {**AUTO, "to": "anyone"}})
    assert "goes out" in send(sb, conn, to="x@notacme.com")


def test_cancel_and_send_now(make_user, client, fake_google, monkeypatch, db_session):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, AUTO)
    send(sb, conn, to="sam@example.com")
    e = the_email(alice, run_id)
    assert alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": False}).json()["data"]["state"] == "cancelled"
    assert later(db_session, 5) == 0 and fake_google.sent == []
    assert "cancelled" in sb.get("/api/runtime/inbox").json()["messages"][0]["text"]

    send(sb, conn, to="sam@example.com")
    e2 = [x for x in alice.get(f"/api/runs/{run_id}/events").json()["events"] if x["kind"] == "approval"][-1]
    assert alice.post(f"/api/runs/{run_id}/approvals/{e2['id']}", json={"send": True}).json()["data"]["state"] == "sent"
    assert later(db_session, 5) == 0 and fake_google.sent == ["d1"]       # sent once


def test_reading_a_strangers_email_makes_it_ask(make_user, client, fake_google, monkeypatch):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, AUTO)
    rpc(sb, conn, "tools/call", {"name": "read_email", "arguments": {"id": "m1"}})        # from sam: fine
    assert "goes out" in send(sb, conn, to="sam@example.com")

    fake_google.known = set()                                             # now sam is a stranger
    outbox._known.clear()
    rpc(sb, conn, "tools/call", {"name": "search_emails", "arguments": {"query": "is:unread"}})
    fake_google.known = {"sam@example.com"}
    outbox._known.clear()
    text = send(sb, conn, to="sam@example.com")                           # a known recipient, but it read a stranger
    assert "Not sent yet" in text and "sam@example.com, someone you haven't written to" in text


@pytest.mark.parametrize("name,given", [("Bash", "curl https://example.com"), ("shell", "ls"),
                                        ("mcp__notion__search", "{}"), ("linear.list_issues", "{}"),
                                        ("Read", '{"file_path": "public/bob/notes.md"}')])
def test_other_sources_make_it_ask(make_user, client, fake_google, monkeypatch, name, given):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, AUTO)
    sb.post("/api/runtime/events", json={"events": [{"kind": "tool", "data": {"name": "Read", "input": '{"file_path": "notes.md"}'}},
                                                    {"kind": "tool", "data": {"name": "mcp__gmail__search_emails", "input": "{}"}}]})
    assert "goes out" in send(sb, conn, to="sam@example.com")             # its own files and Gmail: still fine
    sb.post("/api/runtime/events", json={"events": [{"kind": "tool", "data": {"name": name, "input": given}}]})
    assert "Not sent yet" in send(sb, conn, to="sam@example.com")


def test_replies_only(make_user, client, fake_google, monkeypatch):
    alice = make_user("alice")
    sb, conn, _ = setup(alice, client, monkeypatch, {**AUTO, "replies_only": True})
    assert "only send replies" in send(sb, conn, to="sam@example.com")
    assert "goes out" in send(sb, conn, to="sam@example.com", reply_to_id="m1")


def test_daily_limit(make_user, client, fake_google, monkeypatch):
    alice = make_user("alice")
    sb, conn, _ = setup(alice, client, monkeypatch, AUTO)
    for _ in range(outbox.DAILY_LIMIT):
        assert "goes out" in send(sb, conn, to="sam@example.com")
    assert "already sent 10 emails on their own today" in send(sb, conn, to="sam@example.com")


def test_in_a_team_the_strictest_rules_win(make_user, client, fake_google, monkeypatch):
    alice = make_user("alice")
    sb, conn, _ = setup(alice, client, monkeypatch, {**AUTO, "to": "anyone"}, teammate={})
    assert "Its rules say to ask you first" in send(sb, conn, to="sam@example.com")


def test_a_late_email_asks_instead(make_user, client, fake_google, monkeypatch, db_session):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, AUTO)
    send(sb, conn, to="sam@example.com")
    assert later(db_session, 120) == 0 and fake_google.sent == []
    e = the_email(alice, run_id)
    assert e["data"]["state"] == "pending" and "while Agent Town was down" in e["data"]["why"]


def test_a_failed_send_waits_for_the_person(make_user, client, fake_google, monkeypatch, db_session):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, AUTO)
    send(sb, conn, to="sam@example.com")
    monkeypatch.setattr(outbox.google, "send_draft", lambda *a: (_ for _ in ()).throw(outbox.google.Expired("gone")))
    assert later(db_session, 3) == 0
    e = the_email(alice, run_id)
    assert e["data"]["state"] == "pending" and "sign-in expired" in e["data"]["why"]
    assert [w["event"]["id"] for w in alice.get("/api/today").json()["waiting"]] == [e["id"]]


def test_rules_are_validated_and_shown(make_user):
    alice = make_user("alice")
    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    assert alice.get(f"/api/agents/{a['id']}").json()["email_policy"] == outbox.DEFAULT
    for bad in ({"mode": "always"}, {"to": "everyone"}, {"allow": ["not a domain"]}, {"allow": ["a@b@c.com"]}):
        assert alice.patch(f"/api/agents/{a['id']}", json={"email_policy": bad}).status_code == 422
    r = alice.patch(f"/api/agents/{a['id']}", json={"email_policy": {**AUTO, "allow": [" Sam@Acme.COM ", "@acme.io"]}})
    assert r.json()["email_policy"]["allow"] == ["sam@acme.com", "@acme.io"]


def test_an_email_waiting_on_you_notifies_your_phone(make_user, client, fake_google, monkeypatch):
    import pywebpush

    from .test_chat import SUB
    sent = []
    monkeypatch.setattr(pywebpush, "webpush", lambda info, data, **kw: sent.append(data))
    alice = make_user("alice")
    alice.post("/api/push/subscriptions", json=SUB)
    sb, conn, _ = setup(alice, client, monkeypatch, {})
    send(sb, conn, to="sam@example.com", subject="Lunch")
    assert len(sent) == 1 and "wants to send an email" in sent[0] and "Lunch" in sent[0]
