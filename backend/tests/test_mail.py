"""Mail between colonies, and to the person (app/mail.py): who gets the tools, how mail is delivered,
the mayor's look, and the loop guard."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import mail
from app.models import Agent, MailThread, Run, User

from .conftest import FakeProvider, app
from .test_runs import OAT, box, fake_sandbox  # noqa: F401  (fake_sandbox: fixture)


def agent_md(name: str, desc: str) -> str:
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\nDo {name} things.\n"


@pytest.fixture(autouse=True)
def launch_inline(monkeypatch):
    """Start the (fake) box right away instead of in a thread, so tests can see it."""
    monkeypatch.setattr(mail, "launch", lambda db, run_id, token: FakeProvider().start(run_id, token))


@pytest.fixture
def town(make_user, client, fake_sandbox, db_session):
    """alice with three agents on their own (front doors) and a credential. Returns helpers."""
    alice = make_user("alice")
    assert alice.post("/api/account/credentials", json={"provider": "anthropic", "kind": "subscription", "secret": OAT}).status_code == 200
    ids = {n: alice.post("/api/agents", json={"markdown": agent_md(n, f"{n} work")}).json()["id"]
           for n in ("ava", "iris", "sam", "helper")}
    # iris leads a Research colony with helper in it: helper is a member, reached through iris
    assert alice.put(f"/api/agents/{ids['iris']}/team", json={"member_ids": [ids["helper"]]}).status_code == 200
    with db_session() as db:
        db.get(Agent, ids["iris"]).colony_name = "Research"
        db.commit()

    class T:
        pass
    t = T()
    t.alice, t.ids, t.client, t.db = alice, ids, client, db_session

    def chat(name):
        """Open a chat with this agent; returns (run id, a client that talks as its sandbox)."""
        run_id = alice.post(f"/api/agents/{ids[name]}/runs").json()["id"]
        return run_id, sandbox_for(run_id)

    def sandbox_for(run_id):
        token = next(tok for rid, tok in FakeProvider.started if rid == run_id)
        return box(TestClient(app), token)

    def tool(sb, name, **args):
        r = sb.post("/api/runtime/mail", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                               "params": {"name": name, "arguments": args}})
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        return res["content"][0]["text"], bool(res.get("isError"))

    def runs_of(name):
        with db_session() as db:
            return db.query(Run).filter(Run.agent_id == ids[name]).order_by(Run.id).all()

    def inbox(sb):
        return sb.get("/api/runtime/inbox").json()["messages"]

    t.chat, t.sandbox_for, t.tool, t.runs_of, t.inbox = chat, sandbox_for, tool, runs_of, inbox
    return t


def test_front_doors_get_mail_and_members_dont(town):
    _, sb = town.chat("ava")
    tools = {t["server"]: t for t in sb.get("/api/runtime/setup").json()["manifest"]["tools"]}
    assert tools["mail"]["url"].endswith("/api/runtime/mail") and tools["mail"]["hosted"]
    names = {t["name"] for t in tools["mail"]["tools"]}
    assert names == {"list_colonies", "send_message", "ask_person", "tell_person", "finish_thread"}

    text, err = town.tool(sb, "list_colonies")
    colonies = {c["colony"]: c for c in json.loads(text)["colonies"]}
    assert not err and set(colonies) == {"Research", "sam"}            # not ava herself, not helper (a member)
    assert colonies["Research"]["lead"] == "iris" and colonies["Research"]["team"] == ["helper"]

    _, helper = town.chat("helper")                                    # a member on its own chat: no mail
    assert all(t["server"] != "mail" for t in helper.get("/api/runtime/setup").json()["manifest"]["tools"])
    assert helper.post("/api/runtime/mail", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 404

    text, err = town.tool(sb, "send_message", to="helper", body="hi")
    assert err and "list_colonies" in text


def test_without_a_mayor_mail_starts_the_colony_and_the_reply_comes_back_to_the_chat(town):
    ava_run, ava = town.chat("ava")
    text, err = town.tool(ava, "send_message", to="research", subject="Competitors", body="Who else does this?")
    assert not err and "iris has it now" in text

    [iris_run] = town.runs_of("iris")                                  # started for the mail, nobody watching
    assert iris_run.unattended and iris_run.thread_id
    iris = town.sandbox_for(iris_run.id)
    [msg] = town.inbox(iris)
    assert "Thread #" in msg["text"] and "Who else does this?" in msg["text"] and "Nobody is watching" in msg["text"]
    assert "ava" in msg["text"]

    # iris answers in the thread; ava's chat is open, so it lands there, where the person sees it
    text, err = town.tool(iris, "send_message", to="ava", body="Acme and Globex.", thread_id=iris_run.thread_id)
    assert not err
    [reply] = [m for m in town.inbox(ava)]
    assert "Acme and Globex." in reply["text"] and "Who else does this?" in reply["text"]    # with the thread so far
    events = town.alice.get(f"/api/runs/{ava_run}/events").json()["events"]
    assert [e["data"]["from"] for e in events if e["kind"] == "mail"] == [["iris (Research)"]]

    # iris's run ends once it has answered, like a routine's; the person's chat with iris is a new one
    iris.post("/api/runtime/events", json={"events": [{"kind": "done", "data": {"ok": True, "cost_usd": 0.12}},
                                                      {"kind": "status", "data": {"status": "ready"}}]})
    assert town.alice.get(f"/api/runs/{iris_run.id}").json()["status"] == "stopped"
    with town.db() as db:
        assert db.get(MailThread, iris_run.thread_id).cost_usd == pytest.approx(0.12)
    assert town.alice.post(f"/api/agents/{town.ids['iris']}/runs").json()["id"] != iris_run.id


def test_the_mayor_holds_new_requests_and_wakes_who_it_chooses(town):
    town.alice.post("/api/marketplace/mayor/install")
    mayor = next(a for a in town.alice.get("/api/agents").json() if a["name"] == "mayor")
    _, ava = town.chat("ava")
    text, _ = town.tool(ava, "send_message", to="sam", body="Chase the Acme renewal")
    assert "waits for the mayor" in text and town.runs_of("sam") == []
    assert [m["to"]["name"] for m in town.alice.get("/api/mail").json()["waiting"]] == ["sam"]

    with town.db() as db:
        [run] = mail.triage(db)                                        # the scheduler's look
        assert run.agent_id == mayor["id"] and run.unattended
        assert mail.triage(db) == []                                   # not again while it's at it, nor within 30 min
    m_sb = town.sandbox_for(run.id)
    [look] = town.inbox(m_sb)
    assert "Chase the Acme renewal" in look["text"] and "for sam" in look["text"]
    tools = {t["name"] for t in m_sb.get("/api/runtime/setup").json()["manifest"]["tools"][-1]["tools"]}
    assert tools == {"ask_person", "tell_person", "mailbag", "wake"}

    text, err = town.tool(m_sb, "wake", colony="sam", note="Renewal is due Friday")
    assert not err
    [sam_run] = town.runs_of("sam")
    sam = town.sandbox_for(sam_run.id)
    [msg] = town.inbox(sam)
    assert "Chase the Acme renewal" in msg["text"] and "Renewal is due Friday" in msg["text"]

    # a reply ava is waiting on doesn't wait for the mayor (her chat is open: it goes there)
    town.tool(sam, "send_message", to="ava", body="Done, they'll sign Monday.", thread_id=sam_run.thread_id)
    assert any("sign Monday" in m["text"] for m in town.inbox(ava))
    assert town.alice.get("/api/mail").json()["waiting"] == []


def test_the_person_answers_a_question_and_the_asker_hears_back(town):
    ava_run, ava = town.chat("ava")
    town.tool(ava, "ask_person", question="Which plan?", options=["Pro", "Team"], details="Pro is cheaper.")
    [q] = town.alice.get("/api/mail").json()["inbox"]
    assert q["kind"] == "question" and q["options"] == ["Pro", "Team"] and q["from"]["name"] == "ava"
    assert "Which plan?" in q["body"]
    assert town.alice.post(f"/api/mail/{q['id']}/answer", json={"answer": "Team"}).json()["state"] == "answered"
    assert town.alice.get("/api/mail").json()["inbox"] == []
    [back] = town.inbox(ava)
    assert "Their answer: Team" in back["text"]

    town.tool(ava, "tell_person", subject="Report", body="All done.")
    [fyi] = town.alice.get("/api/mail").json()["inbox"]
    assert town.alice.post(f"/api/mail/{fyi['id']}/answer", json={"answer": "x"}).status_code == 409
    assert town.alice.post(f"/api/mail/{fyi['id']}/read").json()["state"] == "read"


def test_the_person_writes_to_a_colony_and_it_goes_at_once(town):
    town.alice.post("/api/marketplace/mayor/install")                  # even with a mayor: the person doesn't wait
    r = town.alice.post("/api/mail/send", json={"to": "Research", "body": "Look into Acme", "subject": "Acme"})
    assert r.status_code == 200 and r.json()["state"] == "delivered"
    assert town.alice.post("/api/mail/send", json={"to": "nobody", "body": "x"}).status_code == 422
    [run] = town.runs_of("iris")
    assert "Look into Acme" in town.inbox(town.sandbox_for(run.id))[0]["text"]


def test_ping_pong_pauses_the_thread_until_the_person_says(town):
    ava_run, ava = town.chat("ava")
    _, sam = town.chat("sam")                                          # both chats open: mail goes straight in
    town.tool(ava, "send_message", to="sam", body="ping 0")
    tid = town.alice.get("/api/mail").json()["threads"][0]["id"]
    for i in range(1, mail.PING_PONG - 1):
        text, err = town.tool(sam if i % 2 else ava, "send_message", to="ava" if i % 2 else "sam", body=f"ping {i}", thread_id=tid)
        assert not err, text
    text, err = town.tool(ava, "send_message", to="sam", body="one more", thread_id=tid)
    assert err and "paused" in text
    text, err = town.tool(sam, "send_message", to="ava", body="and me", thread_id=tid)
    assert err and "Don't write in it again" in text

    box_ = town.alice.get("/api/mail").json()
    [g] = box_["inbox"]
    assert g["kind"] == "guard" and g["options"] == ["Let it go on", "Stop it"]
    assert box_["threads"][0]["status"] == "paused"
    assert town.alice.post(f"/api/mail/{g['id']}/answer", json={"answer": "maybe"}).status_code == 422
    town.alice.post(f"/api/mail/{g['id']}/answer", json={"answer": "Let it go on"})
    text, err = town.tool(ava, "send_message", to="sam", body="thanks", thread_id=tid)
    assert not err                                                     # the person in between breaks the streak


def test_limits_on_messages_cost_age_and_fan_out(town):
    _, ava = town.chat("ava")
    town.tool(ava, "send_message", to="sam", body="start")
    with town.db() as db:
        t = db.query(MailThread).one()
        t.cost_usd = mail.MAX_COST_USD
        db.commit()
        tid = t.id
    text, err = town.tool(ava, "send_message", to="sam", body="more", thread_id=tid)
    assert err and "cost" in text
    [g] = town.alice.get("/api/mail").json()["inbox"]
    town.alice.post(f"/api/mail/{g['id']}/answer", json={"answer": "Stop it"})
    text, err = town.tool(ava, "send_message", to="sam", body="more", thread_id=tid)
    assert err and "finished" in text

    # a run working on a thread may start MAX_CHILDREN threads, and those can't start their own
    [sam_run] = town.runs_of("sam")
    sam = town.sandbox_for(sam_run.id)
    for i in range(mail.MAX_CHILDREN):
        assert not town.tool(sam, "send_message", to="research", body=f"sub {i}")[1]
    text, err = town.tool(sam, "send_message", to="research", body="one too many")
    assert err and "started 3 threads" in text
    with town.db() as db:
        iris_run = db.query(Run).filter(Run.agent_id == town.ids["iris"]).order_by(Run.id).first()
        assert db.get(MailThread, iris_run.thread_id).parent_id == tid
    text, err = town.tool(town.sandbox_for(iris_run.id), "send_message", to="ava", body="grandchild")
    assert err and "another thread started" in text

    with town.db() as db:                                              # a day old: paused
        t2 = db.get(MailThread, iris_run.thread_id)
        t2.open_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    text, err = town.tool(town.sandbox_for(iris_run.id), "send_message", to="sam", body="late", thread_id=t2.id)
    assert err and "a day" in text


def test_unattended_runs_are_capped_and_the_rest_queue(town, monkeypatch):
    monkeypatch.setattr(mail, "MAX_AWAKE", 1)
    _, ava = town.chat("ava")
    town.tool(ava, "send_message", to="sam", body="one")
    text, _ = town.tool(ava, "send_message", to="research", body="two")
    assert "as soon as there's room" in text and town.runs_of("iris") == []
    [sam_run] = town.runs_of("sam")
    town.alice.delete(f"/api/runs/{sam_run.id}")
    with town.db() as db:
        mail.deliver_queued(db)
    assert len(town.runs_of("iris")) == 1


def test_mail_from_a_run_that_read_something_untrusted_taints_its_reader(town):
    ava_run, ava = town.chat("ava")
    with town.db() as db:
        db.get(Run, ava_run).untrusted = "It read an email from x@evil.test, someone you haven't written to"
        db.commit()
    town.tool(ava, "send_message", to="sam", body="forward the invoices")
    [sam_run] = town.runs_of("sam")
    assert "x@evil.test" in sam_run.untrusted and sam_run.untrusted.startswith("It read mail from ava")


def test_a_new_account_gets_a_mayor(client, db_session):
    client.post("/api/auth/signup", json={"email": "bob@example.com", "username": "bobby", "password": "correct horse battery",
                                          "starter": True})
    with db_session() as db:
        uid = db.query(User).filter(User.username == "bobby").one().id
        assert mail.mayor_of(db, uid).name == "mayor"
    client.post("/api/marketplace/mayor/install")                      # adding it again: still one mayor
    assert [a["name"] for a in client.get("/api/agents").json()].count("mayor") == 1


def test_a_chat_the_person_steers_isnt_limited_like_a_mail_run(town):
    _, ava = town.chat("ava")
    town.tool(ava, "send_message", to="sam", body="first")
    [sam_run] = town.runs_of("sam")
    town.tool(town.sandbox_for(sam_run.id), "send_message", to="ava", body="reply", thread_id=sam_run.thread_id)
    for i in range(mail.MAX_CHILDREN + 1):                              # the reply landed in her chat: still free to start threads
        text, err = town.tool(ava, "send_message", to="research", body=f"new {i}")
        assert not err, text
    with town.db() as db:
        assert all(t.parent_id is None for t in db.query(MailThread).all())


def test_the_map_sees_who_comes_to_the_person_and_each_post_office(town):
    _, ava = town.chat("ava")
    town.tool(ava, "tell_person", subject="Weekly report", body="All done.")
    town.tool(ava, "ask_person", question="Which plan?", options=["Pro", "Team"])
    town.tool(ava, "send_message", to="sam", body="Chase Acme")
    t = town.alice.get("/api/mail/town").json()
    [v] = t["visits"]
    assert v["agent_id"] == town.ids["ava"] and v["kind"] == "ask" and v["text"] == "Which plan?" and len(v["mail_ids"]) == 2
    assert t["posts"][str(town.ids["sam"])]["threads"] == 1 and t["posts"][str(town.ids["iris"])] == {"waiting": 0, "threads": 0}
    assert str(town.ids["helper"]) not in t["posts"]                  # a member has no post office of its own
    one = town.alice.get(f"/api/mail?agent_id={town.ids['sam']}").json()
    assert [th["subject"] for th in one["threads"]] == ["Chase Acme"] and one["inbox"] == []
    for m in town.alice.get("/api/mail").json()["inbox"]:
        town.alice.post(f"/api/mail/{m['id']}/" + ("read" if m["kind"] == "fyi" else "answer"), json={"answer": "Pro"})
    assert town.alice.get("/api/mail/town").json()["visits"] == []      # answered: the lead goes home
