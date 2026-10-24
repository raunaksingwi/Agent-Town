"""Running an agent: a sandbox per chat, with the owner's own model credential.

Two audiences, two kinds of credential:
  /api/agents/{id}/runs, /api/runs/…   the owner (session cookie or API token)
  /api/runtime/…                       the sandbox (its run token, "Bearer rt_…")

The sandbox never accepts connections: it calls us. It fetches its setup once, then polls its
inbox for the owner's messages and posts back what the agent says and does. So it needs no
public address, and the same code works on any provider. A run's life (starting the box, noticing
it died, ending it) is in app/runs.py.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .. import caretaker, mail, mcp_auth, outbox, push
from ..auth import require_user
from ..db import get_db
from ..manifest import ABOUT_ME, build_manifest, granted_tools
from ..models import McpConnection, ModelCredential, Routine, Run, RunEvent, User
from ..runs import CantStart, end, launch, new_run, open_chat, reap
from ..schemas import MAX_FILE, MAX_MEMORY
from ..security import RUN_TOKEN_PREFIX, decrypt, hash_token
from ..timeutil import iso, utc
from .agents import own_agent, set_file

router = APIRouter(tags=["runs"])

FROM_SANDBOX = {"text", "tool", "tool_result", "done", "status", "error"}
MAX_EVENT = 100_000
HEARTBEAT_WRITE = timedelta(seconds=15)   # a poll a second shouldn't mean a write a second


def run_view(r: Run) -> dict:
    return {"id": r.id, "agent_id": r.agent_id, "routine_id": r.routine_id, "status": r.status, "detail": r.detail, "provider": r.provider,
            "created_at": iso(r.created_at), "last_active_at": iso(r.last_active_at), "ended_at": iso(r.ended_at)}


def event_view(e: RunEvent) -> dict:
    return {"id": e.id, "kind": e.kind, "data": e.data, "created_at": iso(e.created_at)}


def own_run(db: Session, user: User, run_id: int) -> Run:
    r = db.get(Run, run_id)
    if r is None or r.owner_id != user.id:
        raise HTTPException(404, "No such run")
    reap(db, r)
    return r


# ---- the owner ------------------------------------------------------------------------------

class StartIn(BaseModel):
    message: str | None = Field(None, min_length=1, max_length=50_000, description="say this first (Today's buttons do)")


@router.post("/api/agents/{agent_id}/runs", status_code=202)
def start_run(agent_id: int, bg: BackgroundTasks, response: Response, body: StartIn | None = None,
              user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Open a chat with this agent: 202 while its sandbox starts. If one is already running it's
    reused (200: nothing is starting)."""
    a = own_agent(db, user, agent_id)
    first = body.message if body else None
    if (r := open_chat(db, a.id)) is not None:
        if first:
            db.add(RunEvent(run_id=r.id, kind="user", data={"text": first}))
            r.last_active_at = datetime.now(timezone.utc)
            db.commit()
        response.status_code = 200
        return run_view(r)
    try:
        r, token = new_run(db, a, first=first)
    except CantStart as e:
        raise HTTPException(e.status, e.detail) from None
    bg.add_task(launch, sessionmaker(bind=db.get_bind(), expire_on_commit=False), r.id, token)
    return run_view(r)


@router.get("/api/runs/active")
def awake(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Which of your agents are awake right now, and what they're doing. The map polls this."""
    out = []
    for r in db.scalars(select(Run).where(Run.owner_id == user.id, Run.agent_id.is_not(None), Run.ended_at.is_(None))):
        reap(db, r)
        if r.ended_at is None:
            out.append({"agent_id": r.agent_id, "run_id": r.id, "status": r.status})
    return out


@router.get("/api/agents/{agent_id}/runs/active")
def active_run(agent_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The agent's running chat, if there is one (null if not). Never starts a sandbox, so the UI
    can call it whenever someone just looks at an agent."""
    a = own_agent(db, user, agent_id)
    r = open_chat(db, a.id)
    return run_view(r) if r else None


@router.get("/api/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return run_view(own_run(db, user, run_id))


@router.get("/api/runs/{run_id}/events")
def run_events(run_id: int, after: int = 0, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The conversation so far, or what's new since event `after`. The UI polls this."""
    r = own_run(db, user, run_id)
    rows = db.scalars(select(RunEvent).where(RunEvent.run_id == r.id, RunEvent.id > after)
                      .order_by(RunEvent.id).limit(500))
    return {"run": run_view(r), "events": [event_view(e) for e in rows]}


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


@router.post("/api/runs/{run_id}/messages")
def send_message(run_id: int, body: MessageIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    r = own_run(db, user, run_id)
    if r.ended_at is not None:
        raise HTTPException(409, "This run has ended; start a new one")
    e = RunEvent(run_id=r.id, kind="user", data={"text": body.text})
    r.last_active_at = datetime.now(timezone.utc)
    db.add(e)
    db.commit()
    return event_view(e)


class DecisionIn(BaseModel):
    send: bool


@router.post("/api/runs/{run_id}/approvals/{event_id}")
def decide(run_id: int, event_id: int, body: DecisionIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The person presses Send (or Don't send) on an email an agent asked to send, or Send now (or
    Cancel) on one its rules let go out after a short wait; or Post (or Don't post) on a LinkedIn post. This, not the agent, is what sends it;
    the agent then hears what happened, as a message from Agent Town."""
    r = own_run(db, user, run_id)
    # Locked while it's handled, so the scheduler can't send it at the same moment (it locks per row too)
    e = db.scalar(select(RunEvent).where(RunEvent.id == event_id, RunEvent.run_id == r.id, RunEvent.kind == "approval")
                  .with_for_update())
    if e is None:
        raise HTTPException(404, "Nothing like that waiting for you")
    state = e.data.get("state")
    if state not in ("pending", "scheduled"):
        raise HTTPException(409, f"Already {state}")
    if body.send:
        if not outbox.claim(db, e):
            raise HTTPException(409, "Already sending")
        err = outbox.deliver(db, e)
        if err:
            db.commit()
            raise HTTPException(409, err)
        kind = e.data.get("type")
        note = (f"{user.username} pressed Post: {outbox.what(e)} is on LinkedIn ({e.data.get('url')})." if kind == "post"
                else f"{user.username} pressed Add: {outbox.what(e)} is in their town now." if kind in ("agent", "colony")
                else f"{user.username} pressed Send: {outbox.what(e)} was sent.")
    elif state == "scheduled":
        e.data, note = {**e.data, "state": "cancelled"}, f"{user.username} cancelled {outbox.what(e)} before it went out.{outbox.kept(e)}"
    else:
        e.data, note = {**e.data, "state": "declined"}, (f"{user.username} chose not to add {outbox.what(e)}."
                                                         if e.data.get("type") in ("agent", "colony")
                                                         else f"{user.username} chose not to send {outbox.what(e)}.{outbox.kept(e)}")
    outbox.tell(db, r, note)
    if r.ended_at is None:
        r.last_active_at = datetime.now(timezone.utc)
    db.commit()
    return event_view(e)


@router.delete("/api/runs/{run_id}")
def stop_run(run_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    r = own_run(db, user, run_id)
    end(db, r, "stopped", "Stopped by you")
    return run_view(r)


# ---- the sandbox ----------------------------------------------------------------------------

def current_run(request: Request, db: Session = Depends(get_db)) -> Run:
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token.startswith(RUN_TOKEN_PREFIX):
        raise HTTPException(401, "Use: Authorization: Bearer rt_…")
    r = db.scalar(select(Run).where(Run.token_hash == hash_token(token.strip())))
    if r is None or r.ended_at is not None:
        raise HTTPException(401, "Invalid run token, or the run has ended")
    return r


def seen(db: Session, r: Run, now: datetime) -> None:
    """The box is alive. Written at most every HEARTBEAT_WRITE: it polls every second."""
    if now - utc(r.last_seen_at) > HEARTBEAT_WRITE:
        r.last_seen_at = now
        db.commit()


@router.get("/api/runtime/setup", tags=["runtime"])
def runtime_setup(r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """The one place secrets leave the server: to this run's own sandbox, for the owner's own
    agent. The manifest stays secret-free; credentials come alongside it."""
    cred = db.get(ModelCredential, r.credential_id) if r.credential_id else None
    secret = decrypt(cred.secret_enc) if cred else None
    if cred is None or secret is None:
        end(db, r, "error", "The model credential is gone or can't be decrypted; add it again")
        raise HTTPException(409, "No usable model credential")
    if r.kind == "caretaker":                         # its tools are served by Agent Town: no app secrets
        m = caretaker.manifest(db, r)
        return {"run_id": r.id, "manifest": m, "secrets": {},
                "credential": {"provider": cred.provider, "kind": cred.kind, "secret": secret,
                               "model": m["model"]["model"], "thinking": m["model"]["thinking"]}}
    m = build_manifest(db, r.agent)
    return {"run_id": r.id, "manifest": m, "secrets": connection_secrets(db, r.agent),
            "credential": {"provider": cred.provider, "kind": cred.kind, "secret": secret,
                           "model": m["model"]["model"], "thinking": m["model"]["thinking"]}}


def connection_secrets(db: Session, agent) -> dict:
    """Each granted server's headers (http) or environment (stdio), by connection id. Hosted ones
    and web APIs are called from here, so nothing of theirs goes out. A sign-in is refreshed first."""
    out = {}
    for t in granted_tools(agent) + [t for member in agent.team for t in granted_tools(member)]:
        c = db.get(McpConnection, t["connection_id"])
        if c is None or c.transport in ("hosted", "web") or str(c.id) in out:
            continue
        try:
            out[str(c.id)] = {"headers": mcp_auth.request_headers(c), "env": {}} if c.transport == "http" \
                else {"headers": {}, "env": mcp_auth.env(c)}
        except mcp_auth.AuthError:                    # expired: it'll answer 401, and the agent says so
            c.status, c.status_detail = "auth_required", "The sign-in expired: sign in again"
    db.commit()
    return out


@router.get("/api/runtime/secrets", tags=["runtime"])
def runtime_secrets(r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """Fresh headers before each turn: a chat can outlast a sign-in's hour-long access token."""
    return {"secrets": connection_secrets(db, r.agent) if r.agent else {}}


@router.get("/api/runtime/ping", tags=["runtime"])
def runtime_ping(r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """The sandbox's heartbeat during a turn, when it isn't polling the inbox: a long tool call or a
    long think mustn't look like a dead box."""
    seen(db, r, datetime.now(timezone.utc))
    return {"ok": True}


@router.get("/api/runtime/inbox", tags=["runtime"])
def runtime_inbox(after: int = 0, r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """The owner's messages (and mail, app/mail.py) since `after`. Polling this is also the sandbox's heartbeat between turns."""
    now = datetime.now(timezone.utc)
    seen(db, r, now)
    rows = db.scalars(select(RunEvent).where(RunEvent.run_id == r.id, RunEvent.kind.in_(("user", "notice", "mail")),
                                             RunEvent.id > after).order_by(RunEvent.id))
    return {"messages": [{"id": e.id, "text": e.data.get("text", "")} for e in rows],
            "idle_seconds": int((now - utc(r.last_active_at)).total_seconds()),
            "memory": memory_tag(r.agent.memory if r.agent else "")}   # changed: the owner edited its notes mid-chat


class EventIn(BaseModel):
    kind: str
    data: dict = Field(default_factory=dict)


class EventsIn(BaseModel):
    events: list[EventIn] = Field(max_length=100)


@router.post("/api/runtime/events", tags=["runtime"])
def runtime_events(body: EventsIn, r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """What the agent said and did, in order. Every event is stored, even the ones after a final
    "stopped"/"error" in the same batch; then the run ends."""
    r.last_seen_at = datetime.now(timezone.utc)
    ending = None
    for ev in body.events:
        if ev.kind not in FROM_SANDBOX:
            raise HTTPException(422, f"Unknown event kind {ev.kind!r}")
        if len(json.dumps(ev.data)) > MAX_EVENT:
            ev.data = {"truncated": True, **{k: v for k, v in ev.data.items() if k in ("name", "ok")}}
        if ev.kind == "tool" and r.agent:
            outbox.check_tool(r, str(ev.data.get("name", "")), str(ev.data.get("input", "")))
        if r.kind == "caretaker":                    # its words and "done" finish the message it's on
            caretaker.heard(db, r, ev.kind, ev.data)
        if ev.kind == "status":
            status = ev.data.get("status")
            if status in ("stopped", "error"):
                ending = ending or (status, str(ev.data.get("detail", "")))
                continue                                    # end() writes this status event itself
            db.flush()                    # a "done" earlier in this same batch counts too
            if status == "ready" and (r.routine_id or r.unattended) and db.scalar(
                    select(RunEvent.id).where(RunEvent.run_id == r.id, RunEvent.kind == "done").limit(1)):
                # A routine (or a run mail started) has answered, and saved its notes, which comes before
                # this "ready": nobody will reply, so end it now instead of keeping a box up until it idles out.
                ending = ending or ("stopped", "Finished")
                continue
            if status in ("ready", "busy"):
                r.status = status
        if ev.kind == "done":
            mail.spent(db, r, ev.data.get("cost_usd"))      # counts against the thread it's working on
        if ev.kind == "done" and r.credential_id:
            cred = db.get(ModelCredential, r.credential_id)
            if cred and ev.data.get("ok") and cred.status == "unverified":  # a subscription token proved itself
                cred.status, cred.status_detail = "valid", "Worked in a run"
            elif cred and ev.data.get("auth_failed"):
                cred.status, cred.status_detail = "invalid", "Rejected by the provider during a run; add it again"
        db.add(RunEvent(run_id=r.id, kind=ev.kind, data=ev.data))
        if ev.kind == "done":
            db.flush()
            answered(db, r)
    db.commit()
    if ending:
        end(db, r, *ending)
    return {"ok": True}


def answered(db: Session, r: Run) -> None:
    """The agent finished a turn. If nobody has its chat open, tell its owner's devices: a routine's
    report is ready, or the agent replied."""
    if push.watched(r.id) or r.agent is None or r.unattended:   # the caretaker answers in its panel; mail
        return                                                    # runs answer by mail, which notifies itself
    said = db.scalar(select(RunEvent).where(RunEvent.run_id == r.id, RunEvent.kind == "text")
                     .order_by(RunEvent.id.desc()).limit(1))
    text = " ".join(str(said.data.get("text", "")).split()) if said else ""
    name = r.agent.name[0].upper() + r.agent.name[1:]
    if r.routine_id:
        routine = db.get(Routine, r.routine_id)
        push.notify(r.owner_id, f"{name}: {routine.name if routine else 'routine'} is done", text or "Its report is on Today.",
                    url="/chat?today", tag=f"routine-{r.routine_id}")
    elif text:
        push.notify(r.owner_id, name, text, url=f"/chat?agent={r.agent_id}", tag=f"agent-{r.agent_id}")


def memory_tag(text: str) -> str:
    """A fingerprint of its notes, so the sandbox can tell they changed without fetching them every second."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class MemoryIn(BaseModel):
    content: str = Field(max_length=MAX_MEMORY)
    base: str = Field(max_length=64, description="memory_tag of the notes this edit started from")


@router.get("/api/runtime/memory", tags=["runtime"])
def runtime_get_memory(r: Run = Depends(current_run)):
    if r.agent is None:
        return {"content": "", "tag": memory_tag("")}
    return {"content": r.agent.memory, "tag": memory_tag(r.agent.memory)}


@router.put("/api/runtime/memory", tags=["runtime"])
def runtime_memory(body: MemoryIn, r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """The agent edited memory.md: keep it for its next chat. Only its own agent's memory, by its token.
    If the owner changed the notes since the agent last had them, the owner's version wins."""
    if r.agent is None:
        raise HTTPException(404, "The caretaker keeps no notes")
    if body.base != memory_tag(r.agent.memory):
        raise HTTPException(409, "The owner changed these notes during the chat")
    r.agent.memory = body.content
    db.commit()
    return {"ok": True, "tag": memory_tag(body.content)}


class AboutMeIn(BaseModel):
    content: str = Field(max_length=MAX_FILE)


@router.put("/api/runtime/about-me", tags=["runtime"])
def runtime_about_me(body: AboutMeIn, r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """The agent wrote down what its owner told it about themselves (its first-chat interview, or later):
    keep about-me.md for its next chat. Only its own agent's file, by its token. The owner sees and
    edits it in the agent's house, like any of its files."""
    if r.agent is None:
        raise HTTPException(404, "The caretaker has no about-me.md")
    if not body.content.strip():
        raise HTTPException(422, "Empty: keeping what was there")
    set_file(r.agent, ABOUT_ME, body.content)
    db.commit()
    return {"ok": True}
