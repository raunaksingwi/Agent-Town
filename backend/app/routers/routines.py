"""Routines (agents on a schedule) and Today: one page of what your agents did, what's waiting on
you, and what runs next. See app/routines.py for the scheduler."""

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import google, mailindex, routines
from ..auth import require_user
from ..db import get_db
from ..models import Agent, OAuthAccount, Routine, Run, RunEvent, User
from ..runs import reap
from ..timeutil import iso, utc
from .agents import own_agent
from .runs import run_view

router = APIRouter(tags=["routines"])

RESULT_DAYS = 7
MAX_RESULTS = 30
WAITING_DAYS = 30     # an email still waiting for a Send after this long is stale, not Today's business


def routine_view(db: Session, r: Routine) -> dict:
    last = db.scalar(select(Run).where(Run.routine_id == r.id).order_by(Run.id.desc()).limit(1))
    return {"id": r.id, "agent_id": r.agent_id, "agent": r.agent.name, "name": r.name, "prompt": r.prompt,
            "days": r.days, "at": r.at, "timezone": r.timezone, "enabled": r.enabled, "trigger": r.trigger,
            "when": routines.describe(r),
            "next_run_at": iso(r.next_run_at), "last_run": run_view(last) if last else None}


def own_routine(db: Session, user: User, routine_id: int) -> Routine:
    r = db.get(Routine, routine_id)
    if r is None or r.owner_id != user.id:
        raise HTTPException(404, "No such routine")
    return r


class RoutineIn(BaseModel):
    agent_id: int | None = None
    name: str | None = Field(None, min_length=1, max_length=80)
    prompt: str | None = Field(None, min_length=1, max_length=10_000)
    days: str | None = Field(None, description='weekdays as digits, Monday=0: "01234" is Monday to Friday')
    at: str | None = Field(None, description='"HH:MM", 24-hour, in `timezone`')
    timezone: str | None = Field(None, max_length=64)
    enabled: bool | None = None
    trigger: Literal["schedule", "email"] | None = Field(None, description='"email": when mail arrives from someone you\'ve written to')

    @field_validator("days")
    @classmethod
    def _days(cls, v):
        if v is not None and not re.fullmatch(r"[0-6]{1,7}", v):
            raise ValueError("pick at least one day")
        return "".join(sorted(set(v))) if v else v

    @field_validator("at")
    @classmethod
    def _at(cls, v):
        if v is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("use HH:MM, like 08:00")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v is not None:
            routines.zone(v)
        return v


@router.get("/api/routines")
def list_routines(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Routine).where(Routine.owner_id == user.id).order_by(Routine.created_at))
    return [routine_view(db, r) for r in rows]


class RoutineCreate(RoutineIn):
    """A new routine needs these; the rest have defaults. (RoutineIn alone is the PATCH body.)"""
    agent_id: int
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=10_000)


@router.post("/api/routines")
def create_routine(body: RoutineCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    a = own_agent(db, user, body.agent_id)
    r = Routine(owner_id=user.id, agent_id=a.id, name=body.name.strip(), prompt=body.prompt.strip(),
                days=body.days or "01234", at=body.at or "08:00", timezone=body.timezone or "UTC",
                enabled=True if body.enabled is None else body.enabled, trigger=body.trigger or "schedule",
                seen_until=datetime.now(timezone.utc))        # an email routine starts with mail from now on
    r.agent = a
    routines.schedule(r)
    db.add(r)
    db.commit()
    return routine_view(db, r)


@router.patch("/api/routines/{routine_id}")
def update_routine(routine_id: int, body: RoutineIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    r = own_routine(db, user, routine_id)
    if body.agent_id is not None:
        r.agent_id = own_agent(db, user, body.agent_id).id
    if body.trigger == "email" and r.trigger != "email":
        r.seen_until = datetime.now(timezone.utc)
    for k in ("name", "prompt", "days", "at", "timezone", "enabled", "trigger"):
        v = getattr(body, k)
        if v is not None:
            setattr(r, k, v.strip() if isinstance(v, str) and k in ("name", "prompt") else v)
    routines.schedule(r)
    db.commit()
    db.refresh(r)
    return routine_view(db, r)


@router.delete("/api/routines/{routine_id}")
def delete_routine(routine_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    db.delete(own_routine(db, user, routine_id))
    db.commit()
    return {"ok": True}


@router.post("/api/routines/{routine_id}/run", status_code=202)
def run_now(routine_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Try it now, without waiting for its time. Its schedule doesn't change."""
    r = own_routine(db, user, routine_id)
    run = routines.fire(db, r)
    if run is None:
        raise HTTPException(409, "It's already running")
    return run_view(run)


# ---- Today ----------------------------------------------------------------------------------

BUILT_IN = {"Read": "read a file", "Write": "wrote a file", "Edit": "edited a file", "Glob": "looked through files",
            "Grep": "searched files", "Bash": "ran a command", "WebSearch": "searched the web",
            "WebFetch": "read a web page", "TodoWrite": "made a to-do list", "Task": "asked a teammate"}


def tool_label(name: str, given: str = "") -> str:
    """In words a person reads: mcp__gmail__search_emails → "gmail: search emails", Task → "asked emma"."""
    if name in ("Task", "Agent") and (who := re.search(r'"subagent_type":\s*"([^"]+)"', given)):
        return f"asked {who[1]}"
    m = re.fullmatch(r"mcp__(.+?)__(.+)", name)
    return f"{m[1]}: {m[2].replace('_', ' ')}" if m else BUILT_IN.get(name, name)


def result_view(db: Session, run: Run, names: dict[int, str]) -> dict:
    """A routine's run as the person needs it: its report, and in plain steps what it did to get there."""
    reap(db, run)
    report, steps, done, errors = "", [], {}, []
    for e in db.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id)):
        if e.kind == "text" and str(e.data.get("text", "")).strip():
            report = str(e.data["text"])          # the last thing it said is its report
        elif e.kind == "tool":
            label = tool_label(str(e.data.get("name", "")), str(e.data.get("input", "")))
            if steps and steps[-1]["tool"] == label:
                steps[-1]["count"] += 1
            else:
                steps.append({"tool": label, "count": 1})
        elif e.kind == "done":
            done = {k: e.data.get(k) for k in ("ok", "cost_usd", "duration_ms")}
        elif e.kind == "error":
            errors.append(str(e.data.get("detail", "")))
    return {"run": run_view(run), "routine": names.get(run.routine_id, "A routine"),
            "agent": {"id": run.agent.id, "name": run.agent.name, "color": run.agent.color},
            "report": report, "steps": steps, "done": done, "errors": errors[-3:]}


@router.get("/api/today")
def today(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Everything on the Today page in one request:
    waiting   emails your agents want to send (from routines and chats), oldest first
    outgoing  emails their rules let go out on their own, still in the undo wait
    sent      emails your agents sent in the last week, newest first
    loops     email threads waiting on you, and yours that went quiet (app/mailindex.py)
    results   what your routines did in the last week, newest first
    routines  your routines, the next one due first
    suggested ready-made routines for agents you have (the founder team), not added yet"""
    mine = db.scalars(select(Routine).where(Routine.owner_id == user.id)).all()
    names = {r.id: r.name for r in mine}

    since = datetime.now(timezone.utc) - timedelta(days=RESULT_DAYS)
    mail: dict[str, list] = {"pending": [], "scheduled": [], "sent": []}
    for e, run in db.execute(select(RunEvent, Run).join(Run, Run.id == RunEvent.run_id)
                             .where(Run.owner_id == user.id, RunEvent.kind == "approval",
                                    RunEvent.created_at >= datetime.now(timezone.utc) - timedelta(days=WAITING_DAYS))
                             .order_by(RunEvent.id)):
        state = e.data.get("state")
        if state in mail and (state != "sent" or utc(e.created_at) >= since):
            mail[state].append({"run_id": run.id, "event": {"id": e.id, "kind": e.kind, "data": e.data, "created_at": iso(e.created_at)},
                                "agent": {"id": run.agent.id, "name": run.agent.name, "color": run.agent.color},
                                "routine": names.get(run.routine_id) if run.routine_id else None})

    runs = db.scalars(select(Run).where(Run.owner_id == user.id, Run.routine_id.is_not(None), Run.created_at >= since)
                      .order_by(Run.id.desc()).limit(MAX_RESULTS)).all()

    have = {a.slug: a for a in db.scalars(select(Agent).where(Agent.owner_id == user.id))}
    taken = {(r.agent_id, r.name) for r in mine}
    suggested = [{**s, "agent_id": have[s["slug"]].id, "agent": have[s["slug"]].name}
                 for s in routines.SUGGESTED if s["slug"] in have and (have[s["slug"]].id, s["name"]) not in taken]

    loops: dict[str, list] = {"waiting_on_me": [], "gone_quiet": []}
    indexing = False
    for acct in db.scalars(select(OAuthAccount).where(OAuthAccount.owner_id == user.id, OAuthAccount.index_on.is_(True))):
        if mailindex.ready(acct):
            for k, v in mailindex.loops(db, acct, limit=8).items():
                loops[k] += v
        elif "gmail" in google.apps_granted(acct.scopes):
            indexing = True

    order = sorted(mine, key=lambda r: (r.next_run_at is None, utc(r.next_run_at).timestamp() if r.next_run_at else 0, r.id))
    return {"waiting": mail["pending"], "outgoing": mail["scheduled"], "sent": mail["sent"][::-1][:MAX_RESULTS],
            "loops": {**loops, "indexing": indexing},
            "results": [result_view(db, r, names) for r in runs],
            "routines": [routine_view(db, r) for r in order], "suggested": suggested}
