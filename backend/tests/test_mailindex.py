"""The email index: syncing (first in full, then by history), people, open loops, the tools, turning it
off, and routines that start when email arrives. Gmail is a fake mailbox on top of test_google's fake."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import google, mailindex, outbox, routines
from app.models import MailMessage, OAuthAccount, Routine

from .conftest import AGENT_MD
from .test_google import FakeGoogle, rpc, sign_in
from .test_outbox import setup

NOW = datetime.now(timezone.utc)


class Mailbox(FakeGoogle):
    """Threads of {id, labels, from, to, subject, at}; every message added bumps the history id."""

    def __init__(self):
        super().__init__()
        self.threads: dict[str, list[dict]] = {}
        self.history: list[tuple[int, dict]] = []
        self.hid = 100
        self.thread_gets = 0

    def add(self, tid, mid, frm, to, subject, days_ago, labels=("INBOX",)):
        m = {"id": mid, "threadId": tid, "labelIds": list(labels), "from": frm, "to": to, "subject": subject,
             "internalDate": str(int((NOW - timedelta(days=days_ago)).timestamp() * 1000))}
        self.threads.setdefault(tid, []).append(m)
        self.hid += 1
        self.history.append((self.hid, m))

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url, p = str(req.url), req.url.params
        if url.startswith(f"{google.GMAIL}/profile"):
            return httpx.Response(200, json={"emailAddress": "alice@example.com", "historyId": str(self.hid)})
        if url.startswith(f"{google.GMAIL}/threads/"):
            self.thread_gets += 1
            tid = req.url.path.rsplit("/", 1)[1]
            if tid not in self.threads:
                return httpx.Response(404, json={"error": {"message": "Not Found"}})
            return httpx.Response(200, json={"id": tid, "messages": [
                {"id": m["id"], "threadId": tid, "labelIds": m["labelIds"], "internalDate": m["internalDate"],
                 "payload": {"headers": [{"name": "From", "value": m["from"]}, {"name": "To", "value": m["to"]},
                                         {"name": "Subject", "value": m["subject"]}]}} for m in self.threads[tid]]})
        if url.startswith(f"{google.GMAIL}/threads"):
            assert "newer_than:90d" in p["q"] and "-category:promotions" in p["q"]
            return httpx.Response(200, json={"threads": [{"id": t} for t in self.threads]})
        if url.startswith(f"{google.GMAIL}/history"):
            start = int(p["startHistoryId"])
            if start < 50:
                return httpx.Response(404, json={"error": {"message": "Requested entity was not found."}})
            return httpx.Response(200, json={"historyId": str(self.hid), "history": [
                {"id": str(h), "messagesAdded": [{"message": {"id": m["id"], "threadId": m["threadId"], "labelIds": m["labelIds"]}}]}
                for h, m in self.history if h > start]})
        return super().__call__(req)


@pytest.fixture
def mailbox(monkeypatch):
    mb = Mailbox()
    monkeypatch.setattr(google, "http", lambda: httpx.Client(transport=httpx.MockTransport(mb)))
    from app.config import settings
    monkeypatch.setattr(settings(), "google_client_id", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings(), "google_client_secret", "test-secret")
    monkeypatch.setattr(settings(), "app_url", "http://testserver")
    mb.add("t1", "a1", "Alice <alice@example.com>", "Sam Lee <sam@example.com>", "Pricing for Q4", 10, ["SENT"])
    mb.add("t1", "a2", "Sam Lee <sam@example.com>", "alice@example.com", "Re: Pricing for Q4", 2)       # waiting on alice
    mb.add("t2", "b1", "Alice <alice@example.com>", "Priya <priya@acme.com>, sam@example.com", "Intro", 6, ["SENT"])  # gone quiet
    mb.add("t3", "c1", "Stranger <x@spam.example>", "alice@example.com", "Hi friend", 1)                   # not someone she knows
    mb.add("t4", "d1", "Shop <deals@shop.example>", "alice@example.com", "50% off", 1, ["CATEGORY_PROMOTIONS"])
    mb.add("t5", "e1", "GitHub <noreply@github.com>", "alice@example.com", "PR merged", 1)
    mb.add("t6", "f1", "Alice <alice@example.com>", "noreply@github.com", "re", 20, ["SENT"])           # she wrote to a robot once
    return mb


def connect(alice) -> int:
    alice.get(f"/api/connect/google/callback?state={sign_in(alice)}&code=the-code", follow_redirects=False)
    return alice.get("/api/connect/google").json()["accounts"][0]["id"]


def tick(db_session, now=None):
    db = db_session()
    try:
        mailindex.tick(db, now)
    finally:
        db.close()


def test_first_sync_builds_people_and_loops(make_user, mailbox, db_session):
    alice = make_user("alice")
    acct_id = connect(alice)
    assert alice.get("/api/today").json()["loops"]["indexing"] is True
    tick(db_session)
    acct = alice.get("/api/connect/google").json()["accounts"][0]["index"]
    assert acct["on"] and acct["synced_at"] and acct["people"] == 3           # sam, priya, the robot she wrote to

    db = db_session()
    a = db.get(OAuthAccount, acct_id)
    msgs = db.query(MailMessage).filter_by(account_id=a.id).all()
    assert {m.gmail_id for m in msgs} == {"a1", "a2", "b1", "c1", "e1", "f1"}       # no promotions
    assert all(m.subject_enc and "Pricing" not in m.subject_enc for m in msgs)    # subjects encrypted
    sam = mailindex.person(db, a, "sam@example.com")
    assert (sam.name, sam.sent, sam.received) == ("Sam Lee", 2, 1)
    db.close()

    loops = alice.get("/api/today").json()["loops"]
    assert [(x["with"], x["subject"]) for x in loops["waiting_on_me"]] == [("Sam Lee", "Re: Pricing for Q4")]
    assert [(x["with"], x["subject"]) for x in loops["gone_quiet"]] == [("Priya +1", "Intro")]   # not the stranger, not the robot


def test_then_only_changed_threads(make_user, mailbox, db_session):
    alice = make_user("alice")
    connect(alice)
    tick(db_session)
    before = mailbox.thread_gets
    tick(db_session)   # not due yet
    assert mailbox.thread_gets == before
    mailbox.add("t2", "b2", "Priya <priya@acme.com>", "alice@example.com", "Re: Intro", 0)
    tick(db_session, datetime.now(timezone.utc) + mailindex.EVERY + timedelta(seconds=1))
    assert mailbox.thread_gets == before + 1                                    # just t2
    loops = alice.get("/api/today").json()["loops"]
    assert loops["gone_quiet"] == [] and {x["subject"] for x in loops["waiting_on_me"]} == {"Re: Pricing for Q4", "Re: Intro"}


def test_tools_and_the_known_check_use_the_index(make_user, client, mailbox, monkeypatch, db_session):
    alice = make_user("alice")
    sb, conn, run_id = setup(alice, client, monkeypatch, {"mode": "auto"})
    out = rpc(sb, conn, "tools/call", {"name": "open_loops", "arguments": {}}).json()["result"]["content"][0]["text"]
    assert "still building the email index" in out
    tick(db_session)
    out = rpc(sb, conn, "tools/call", {"name": "find_people", "arguments": {"query": "sam"}}).json()["result"]["content"][0]["text"]
    assert "Sam Lee" in out and "Pricing for Q4" in out
    mailbox.known = set()   # Google's search would say no…
    outbox._known.clear()
    assert "goes out" in rpc(sb, conn, "tools/call", {"name": "send_email", "arguments": {
        "to": "priya@acme.com", "body": "Hi"}}).json()["result"]["content"][0]["text"]   # …but the index knows priya
    rpc(sb, conn, "tools/call", {"name": "find_people", "arguments": {"query": "x@spam"}})  # a stranger's subjects
    assert "Not sent yet" in rpc(sb, conn, "tools/call", {"name": "send_email", "arguments": {
        "to": "priya@acme.com", "body": "Hi"}}).json()["result"]["content"][0]["text"]


def test_turning_it_off_deletes_it(make_user, mailbox, db_session):
    alice = make_user("alice")
    acct_id = connect(alice)
    tick(db_session)
    bob = make_user("bob")
    assert bob.patch(f"/api/connect/google/{acct_id}", json={"index": False}).status_code == 404
    r = alice.patch(f"/api/connect/google/{acct_id}", json={"index": False}).json()
    assert r["index"] == {"on": False, "synced_at": None, "people": 0, "problem": ""}
    db = db_session()
    assert db.query(MailMessage).count() == 0
    db.close()
    tick(db_session, datetime.now(timezone.utc) + timedelta(hours=1))   # stays off
    assert alice.get("/api/connect/google").json()["accounts"][0]["index"]["people"] == 0
    alice.patch(f"/api/connect/google/{acct_id}", json={"index": True})
    tick(db_session, datetime.now(timezone.utc) + timedelta(hours=1))
    assert alice.get("/api/connect/google").json()["accounts"][0]["index"]["people"] == 3


def test_disconnecting_deletes_it(make_user, mailbox, db_session):
    alice = make_user("alice")
    acct_id = connect(alice)
    tick(db_session)
    alice.delete(f"/api/connect/google/{acct_id}")
    db = db_session()
    assert db.query(MailMessage).count() == 0
    db.close()


def test_history_too_old_starts_over(make_user, mailbox, db_session):
    alice = make_user("alice")
    acct_id = connect(alice)
    tick(db_session)
    db = db_session()
    db.get(OAuthAccount, acct_id).index_history = "7"
    db.commit()
    db.close()
    tick(db_session, datetime.now(timezone.utc) + timedelta(hours=1))
    assert alice.get("/api/connect/google").json()["accounts"][0]["index"]["problem"] == ""


@pytest.fixture
def fired(monkeypatch):
    calls = []
    monkeypatch.setattr(routines, "fire", lambda db, r, now=None, mail=None: calls.append((r.name, mail)) or object())
    return calls


def test_email_routine_runs_for_mail_from_people_she_knows(make_user, mailbox, db_session, fired):
    alice = make_user("alice")
    connect(alice)
    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    r = alice.post("/api/routines", json={"agent_id": a["id"], "name": "Triage", "prompt": "Reply if easy", "trigger": "email"}).json()
    assert r["trigger"] == "email" and r["next_run_at"] is None and r["when"].startswith("When email arrives")
    tick(db_session)
    assert fired == []                                                          # the first sync is history, not news

    mailbox.add("t7", "g1", "Sam Lee <sam@example.com>", "alice@example.com", "Quick question", -0.01)
    mailbox.add("t8", "h1", "Stranger <x@spam.example>", "alice@example.com", "Urgent!!", -0.01)
    tick(db_session, datetime.now(timezone.utc) + timedelta(minutes=3))   # watched: every 2 minutes
    assert [(n, [m["from"] for m in mail]) for n, mail in fired] == [("Triage", ["sam@example.com"])]
    assert fired[0][1][0]["subject"] == "Quick question" and fired[0][1][0]["email_id"] == "g1"

    tick(db_session, datetime.now(timezone.utc) + timedelta(minutes=6))   # nothing new: no run
    assert len(fired) == 1


def test_mail_that_arrives_during_a_run_waits_for_the_next_tick(make_user, mailbox, db_session, monkeypatch):
    """fire() says None while the routine's last run is still going; the mail isn't lost, it's
    picked up from the index on the next tick."""
    alice = make_user("alice")
    connect(alice)
    a = alice.post("/api/agents", json={"markdown": AGENT_MD}).json()
    alice.post("/api/routines", json={"agent_id": a["id"], "name": "Triage", "prompt": "Reply", "trigger": "email"})
    tick(db_session)
    calls, busy = [], [True]
    monkeypatch.setattr(routines, "fire", lambda db, r, now=None, mail=None: calls.append([m["email_id"] for m in mail]) or
                        (None if busy[0] else object()))
    mailbox.add("t7", "g1", "Sam Lee <sam@example.com>", "alice@example.com", "One", -0.02)
    tick(db_session, datetime.now(timezone.utc) + timedelta(minutes=3))
    assert calls == [["g1"]]                                                     # asked, but the run was still going
    mailbox.add("t9", "g2", "Sam Lee <sam@example.com>", "alice@example.com", "Two", -0.03)   # later than "One"
    busy[0] = False
    tick(db_session, datetime.now(timezone.utc) + timedelta(minutes=6))
    assert calls[-1] == ["g1", "g2"]                                             # both, oldest first
    tick(db_session, datetime.now(timezone.utc) + timedelta(minutes=9))
    assert len(calls) == 2                                                       # and not again


def test_email_routine_first_message():
    r = Routine(name="Triage", prompt="Reply if easy", timezone="UTC", trigger="email")
    text = routines.first_message(r, NOW, [{"email_id": "g1", "from": "sam@example.com", "subject": "Q", "at": "now"}])
    assert "new email arrived" in text and "email_id g1: from sam@example.com" in text and text.endswith("Reply if easy")
