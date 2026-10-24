"""The person's mailbox, and their view of the mail between their colonies (app/mail.py).

    GET  /api/mail                     what waits on them, recent threads, mail waiting for the mayor
                                       (?agent_id=: only one colony's, for its post office on the map)
    GET  /api/mail/town                for the map: which leads come to see them, and each post office's counts
    GET  /api/mail/threads/{id}        one thread, every message in it
    POST /api/mail/send                write to a colony (it goes at once: the person doesn't wait for the mayor)
    POST /api/mail/{id}/answer         answer a question (or a paused thread's "go on?")
    POST /api/mail/{id}/read           done with something they were told
    POST /api/mail/{id}/deliver        hand mail that waits for the mayor to its colony now
    POST /api/mail/threads/{id}/finish close a thread
"""

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import mail
from ..auth import require_user
from ..db import get_db
from ..models import Agent, Mail, MailThread, User
from ..timeutil import iso

router = APIRouter(prefix="/api/mail", tags=["mail"])

RECENT_DAYS = 14
MAX_THREADS = 30


def who(a: Agent | None) -> dict | None:
    return {"id": a.id, "name": a.name, "color": a.color, "colony": mail.colony(a)} if a else None


def mail_view(db: Session, m: Mail) -> dict:
    t = db.get(MailThread, m.thread_id)
    return {"id": m.id, "thread_id": m.thread_id, "subject": t.subject, "kind": m.kind, "body": m.body,
            "options": m.options, "answer": m.answer, "state": m.state, "from": who(m.sender), "to": who(m.recipient),
            "created_at": iso(m.created_at), "delivered_at": iso(m.delivered_at), "run_id": m.run_id}


def thread_view(db: Session, t: MailThread) -> dict:
    msgs = db.scalars(select(Mail).where(Mail.thread_id == t.id).order_by(Mail.id)).all()
    people = {}
    for m in msgs:
        for a in (m.sender, m.recipient):
            if a is not None:
                people[a.id] = who(a)
    return {"id": t.id, "subject": t.subject, "status": t.status, "paused_reason": t.paused_reason,
            "started_by": who(db.get(Agent, t.started_by_id)) if t.started_by_id else None, "parent_id": t.parent_id,
            "messages": len(msgs), "cost_usd": round(t.cost_usd, 4), "agents": list(people.values()),
            "created_at": iso(t.created_at), "updated_at": iso(t.updated_at)}


def own_mail(db: Session, user: User, mail_id: int) -> Mail:
    m = db.get(Mail, mail_id)
    if m is None or m.owner_id != user.id:
        raise HTTPException(404, "No such mail")
    return m


def own_thread(db: Session, user: User, thread_id: int) -> MailThread:
    t = db.get(MailThread, thread_id)
    if t is None or t.owner_id != user.id:
        raise HTTPException(404, "No such thread")
    return t


def _involving(agent_id: int):
    """Threads this agent wrote or was written to in."""
    return select(Mail.thread_id).where((Mail.from_id == agent_id) | (Mail.to_id == agent_id))


@router.get("")
def mailbox(agent_id: int | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    mine = select(Mail).where(Mail.owner_id == user.id, Mail.to_id.is_(None), Mail.from_id.is_not(None) | (Mail.kind == "guard"),
                              or_(Mail.state == "new", Mail.created_at >= since))
    waiting = select(Mail).where(Mail.owner_id == user.id, Mail.state.in_(("waiting", "queued")))
    threads = select(MailThread).where(MailThread.owner_id == user.id)
    if agent_id is not None:                          # one colony's post office
        mine = mine.where(Mail.thread_id.in_(_involving(agent_id)))
        waiting = waiting.where(Mail.to_id == agent_id)
        threads = threads.where(MailThread.id.in_(_involving(agent_id)))
    mine = db.scalars(mine.order_by(Mail.id.desc())).all()
    waiting = db.scalars(waiting.order_by(Mail.id)).all()
    threads = db.scalars(threads.order_by(MailThread.updated_at.desc()).limit(MAX_THREADS)).all()
    mayor = mail.mayor_of(db, user.id)
    return {"inbox": [mail_view(db, m) for m in mine if m.state == "new"],
            "done": [mail_view(db, m) for m in mine if m.state != "new"][:20],
            "waiting": [mail_view(db, m) for m in waiting],
            "threads": [thread_view(db, t) for t in threads],
            "colonies": [who(a) for a in mail.front_doors(db, user.id)],
            "mayor": who(mayor), "mayor_checked_at": iso(user.mayor_checked_at)}


@router.get("/town")
def town(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """What the map shows of mail, polled with who's awake:
    visits  a colony's lead walks to the square while something of theirs waits on the person: a
            question, a note, or a paused thread (whoever started it comes about that one)
    posts   each front door's post office: mail waiting for it to be woken, and its threads still going"""
    visits: dict[int, dict] = {}
    for m in db.scalars(select(Mail).where(Mail.owner_id == user.id, Mail.to_id.is_(None), Mail.state == "new").order_by(Mail.id)):
        who_id = m.from_id if m.kind != "guard" else db.get(MailThread, m.thread_id).started_by_id
        if who_id is None:
            continue
        v = visits.setdefault(who_id, {"agent_id": who_id, "mail_ids": [], "kind": "fyi", "text": ""})
        v["mail_ids"].append(m.id)
        if m.kind in ("question", "guard") or not v["text"]:   # a question outranks a note, in what the bubble says
            first = next((t for t in (" ".join(re.sub(r"[*_#`>]", "", ln).split()) for ln in m.body.splitlines()) if t), "")
            if m.kind != "fyi" or v["kind"] == "fyi":
                v["kind"], v["text"] = ("ask" if m.kind != "fyi" else "fyi"), first[:80]
    posts = {}
    for a in mail.front_doors(db, user.id):
        waiting = db.scalar(select(func.count()).select_from(Mail).where(Mail.to_id == a.id, Mail.state.in_(("waiting", "queued"))))
        going = db.scalar(select(func.count()).select_from(MailThread).where(MailThread.status != "done",
                                                                            MailThread.id.in_(_involving(a.id))))
        posts[a.id] = {"waiting": waiting, "threads": going}
    return {"visits": list(visits.values()), "posts": posts}


@router.get("/threads/{thread_id}")
def thread(thread_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    t = own_thread(db, user, thread_id)
    return {**thread_view(db, t), "mail": [mail_view(db, m) for m in
                                           db.scalars(select(Mail).where(Mail.thread_id == t.id).order_by(Mail.id))]}


class SendIn(BaseModel):
    to: str = Field(min_length=1, max_length=80, description="a colony's name, or its lead's")
    body: str = Field(min_length=1, max_length=mail.MAX_BODY)
    subject: str = Field("", max_length=200)
    thread_id: int | None = None


@router.post("/send")
def send(body: SendIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        to = mail.address(db, user.id, body.to)
        m = mail.send(db, None, to, body.body.strip(), subject=body.subject.strip(), thread_id=body.thread_id, owner_id=user.id)
    except mail.MailError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from None
    return mail_view(db, m)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=mail.MAX_BODY)


@router.post("/{mail_id}/answer")
def answer(mail_id: int, body: AnswerIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    m = own_mail(db, user, mail_id)
    if m.to_id is not None or m.kind not in ("question", "guard") or m.state != "new":
        raise HTTPException(409, "That isn't a question waiting on you")
    if m.kind == "guard" and body.answer not in m.options:
        raise HTTPException(422, f"Answer one of: {', '.join(m.options)}")
    mail.answer(db, m, body.answer.strip())
    return mail_view(db, m)


@router.post("/{mail_id}/read")
def read(mail_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    m = own_mail(db, user, mail_id)
    if m.to_id is not None or m.state != "new" or m.kind in ("question", "guard"):
        raise HTTPException(409, "Nothing to mark read")
    m.state = "read"
    db.commit()
    return mail_view(db, m)


@router.post("/{mail_id}/deliver")
def deliver(mail_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    m = own_mail(db, user, mail_id)
    if m.state not in ("waiting", "queued"):
        raise HTTPException(409, "It isn't waiting")
    mail.deliver(db, [m], wake=True, note="The person asked for this one now.")
    return mail_view(db, m)


@router.post("/threads/{thread_id}/finish")
def finish(thread_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    t = own_thread(db, user, thread_id)
    t.status, t.paused_reason = "done", ""
    for m in db.scalars(select(Mail).where(Mail.thread_id == t.id, Mail.state.in_(("waiting", "queued", "held")))):
        m.state = "dropped"
    for m in db.scalars(select(Mail).where(Mail.thread_id == t.id, Mail.kind == "guard", Mail.state == "new")):
        m.state, m.answer = "answered", "Stopped"
    db.commit()
    return thread_view(db, t)
