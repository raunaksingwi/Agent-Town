"""The chat app (frontend /chat, installable on a phone): each agent as a conversation that carries on
across its runs, and the devices that get notifications.

    GET    /api/conversations                 your agents, the latest message first
    GET    /api/agents/{id}/messages          what was said with one agent, over all its chats and routines
    GET    /api/push/key                      the key a device subscribes with
    POST   /api/push/subscriptions            this device wants notifications
    DELETE /api/push/subscriptions            …and now it doesn't
    POST   /api/push/test                     send yourself one, to see it works

A run (routers/runs.py) is one sandbox session; a conversation is all of an agent's runs, read as one
thread. Routine runs show as the routine's name and its report: their first message is Agent Town's
instructions, not something the person said.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import push
from ..auth import require_user
from ..db import get_db
from ..models import Agent, PushSubscription, Routine, Run, RunEvent, User
from ..runs import open_chat, reap
from .agents import own_agent
from .runs import event_view, run_view

router = APIRouter(tags=["chat"])

SAID = ("user", "text", "approval", "mail")      # mail: another colony (or the person) wrote to it (app/mail.py)
WAITING_DAYS = 30      # as on Today: an approval older than this isn't waiting any more, it's forgotten


def _said(db: Session, agent_id: int):
    """The query for an agent's conversation: what was said, in its chats and its routines' runs."""
    return (select(RunEvent, Run).join(Run, Run.id == RunEvent.run_id)
            .where(Run.agent_id == agent_id, RunEvent.kind.in_(SAID)))


def _message(e: RunEvent, run: Run, routines: dict[int, str]) -> dict | None:
    if e.kind == "user" and run.routine_id:
        return None                                  # Agent Town's instructions to the routine, not the person
    return {**event_view(e), "run_id": run.id,
            "routine": routines.get(run.routine_id, "A routine") if run.routine_id else None}


@router.get("/api/conversations")
def conversations(user: User = Depends(require_user), db: Session = Depends(get_db)):
    routines = {r.id: r.name for r in db.scalars(select(Routine).where(Routine.owner_id == user.id))}
    agents = db.scalars(select(Agent).where(Agent.owner_id == user.id).options(selectinload(Agent.team))).all()
    # one pass over the open runs and the waiting approvals for all agents, not a query per agent
    open_runs = {}
    for run in db.scalars(select(Run).where(Run.owner_id == user.id, Run.routine_id.is_(None), Run.ended_at.is_(None))):
        reap(db, run)
        if run.ended_at is None:
            open_runs[run.agent_id] = run
    waiting: dict[int, int] = {}
    for e, run in db.execute(select(RunEvent, Run).join(Run, Run.id == RunEvent.run_id)
                             .where(Run.owner_id == user.id, RunEvent.kind == "approval",
                                    RunEvent.created_at >= datetime.now(timezone.utc) - timedelta(days=WAITING_DAYS))):
        if e.data.get("state") in ("pending", "scheduled"):
            waiting[run.agent_id] = waiting.get(run.agent_id, 0) + 1
    out = []
    for a in agents:
        last = None
        for e, run in db.execute(_said(db, a.id).order_by(RunEvent.id.desc()).limit(5)):
            if (last := _message(e, run, routines)) is not None:
                break
        chat = open_runs.get(a.id)
        out.append({"agent": {"id": a.id, "name": a.name, "color": a.color, "description": a.description,
                              "team": [m.id for m in a.team]},
                    "last": last, "waiting": waiting.get(a.id, 0), "status": chat.status if chat else None})
    out.sort(key=lambda c: c["agent"]["name"].lower())
    out.sort(key=lambda c: c["last"]["created_at"] if c["last"] else "", reverse=True)   # latest first; silent ones last, by name
    return out


@router.get("/api/agents/{agent_id}/messages")
def messages(agent_id: int, after: int = 0, before: int | None = None, limit: int = 50,
             user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Oldest first. No cursor: the latest `limit`. after: what's new since that event (polling).
    before: older history (scrolling up). Also the agent's open chat, and the last two days' emails as
    they are now, so a card that was waiting shows it went out."""
    a = own_agent(db, user, agent_id)
    routines = {r.id: r.name for r in db.scalars(select(Routine).where(Routine.owner_id == user.id))}
    q, limit = _said(db, a.id), max(1, min(limit, 200))
    if after:
        rows = db.execute(q.where(RunEvent.id > after).order_by(RunEvent.id).limit(limit)).all()
    else:
        older = q.where(RunEvent.id < before) if before is not None else q
        rows = db.execute(older.order_by(RunEvent.id.desc()).limit(limit)).all()[::-1]
    out = [m for e, run in rows if (m := _message(e, run, routines))]
    chat = open_chat(db, a.id)
    if chat is not None:
        push.watching(chat.id)                       # someone's looking: no notification for its answers
    since = datetime.now(timezone.utc) - timedelta(days=2)
    mail = [event_view(e) for e, _ in db.execute(_said(db, a.id).where(RunEvent.kind == "approval", RunEvent.created_at >= since))]
    return {"messages": out, "run": run_view(chat) if chat else None, "mail": mail,
            "cursor": max([after, *(e.id for e, _ in rows)]), "more": not after and len(rows) == limit}


class Keys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=4, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: Keys


class EndpointIn(BaseModel):
    endpoint: str = Field(max_length=1000)


@router.get("/api/push/key")
def push_key():
    return {"key": push.public_key()}


@router.post("/api/push/subscriptions")
def subscribe(body: SubscriptionIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """One row per device. A device that someone else used before is theirs now: notifications follow
    whoever signed in on it last. Their old row goes, rather than being taken over, so a leaked endpoint
    can't be re-pointed at someone's device from another account."""
    s = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if s is not None and s.user_id != user.id:
        db.delete(s)
        db.flush()
        s = None
    if s is None:
        s = PushSubscription(endpoint=body.endpoint, user_id=user.id)
        db.add(s)
    s.p256dh, s.auth = body.keys.p256dh, body.keys.auth
    db.commit()
    return {"ok": True}


@router.delete("/api/push/subscriptions")
def unsubscribe(body: EndpointIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    s = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint,
                                                 PushSubscription.user_id == user.id))
    if s is None:
        raise HTTPException(404, "This device isn't subscribed")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/api/push/test")
def test_push(user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user.id).limit(1)):
        raise HTTPException(409, "Turn on notifications on this device first")
    push.notify(user.id, "Agent Town", "Notifications work. Your agents will tell you here when something needs you.",
                tag="test")
    return {"ok": True}

