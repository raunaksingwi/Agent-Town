"""A run's life: starting its sandbox, noticing when the box died, and ending it.

The API (routers/runs.py) and the scheduler (routines.py) both go through here, so there is one
place that decides what "dead" means and one that tears a box down. The runner in the box
(runner/runner.py) keeps itself alive by polling its inbox between turns and pinging during one;
a box that goes quiet for longer than SILENCE is gone, and a box still "starting" after BOOT_GRACE
never came up.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from . import sandbox
from .config import settings
from .manifest import build_manifest
from .models import Agent, Run, RunEvent
from .security import new_run_token
from .timeutil import utc

log = logging.getLogger("agenttown.runs")

ACTIVE = ("starting", "ready", "busy")
BOOT_GRACE = timedelta(minutes=10)   # the first Modal run builds the image
SILENCE = timedelta(minutes=2)       # between turns the runner polls every second; this long quiet = gone
SILENCE_BUSY = timedelta(minutes=10)  # during a turn it only pings every 20 s; a long tool call mustn't look dead
EXIT_CHECK = timedelta(seconds=15)   # a box still "starting" after this: ask the provider if it died
_checked: dict[int, float] = {}      # run id -> when we last asked (don't ask on every UI poll)
_reachable_until = 0.0


def end(db: Session, r: Run, status: str, detail: str) -> None:
    """Stop for good: the token stops working at once, then the box is torn down (best effort)."""
    if r.ended_at is not None:
        return
    r.status, r.detail, r.ended_at = status, detail[:2000], datetime.now(timezone.utc)
    db.add(RunEvent(run_id=r.id, kind="status", data={"status": status, "detail": detail[:2000]}))
    db.commit()
    if r.sandbox_id:
        try:
            sandbox.provider(r.provider).stop(r.sandbox_id)
        except Exception:  # noqa: BLE001  (already ended for us; the provider's own timeout is the backstop)
            log.warning("couldn't stop sandbox %s of run %s", r.sandbox_id, r.id, exc_info=True)


def reap(db: Session, r: Run) -> None:
    """Runs end on their own (idle timeout in the runner), but a crashed box can't say so."""
    if r.ended_at is not None:
        return
    now = datetime.now(timezone.utc)
    if now - utc(r.created_at) > timedelta(hours=settings().run_max_hours):
        end(db, r, "stopped", "Reached the maximum run length")
    elif r.status == "starting" and now - utc(r.created_at) > BOOT_GRACE:
        end(db, r, "error", "The sandbox never started")
    elif r.status == "starting" and r.sandbox_id and now - utc(r.created_at) > EXIT_CHECK \
            and time.monotonic() - _checked.get(r.id, 0) > 10:
        _checked[r.id] = time.monotonic()
        try:
            gone = not sandbox.provider(r.provider).alive(r.sandbox_id)
        except Exception:  # noqa: BLE001  (can't tell: leave it to BOOT_GRACE)
            gone = False
        if gone:  # it exited before it ever checked in: almost always it couldn't reach us
            end(db, r, "error", f"The sandbox stopped before it could reach Agent Town at {settings().public_url}")
    elif r.status != "starting" and now - utc(r.last_seen_at) > (SILENCE_BUSY if r.status == "busy" else SILENCE):
        end(db, r, "error", "The sandbox stopped responding")


def reap_all(db: Session) -> None:
    """The scheduler's sweep: a box that died while nobody had the app open still gets noticed."""
    for r in db.scalars(select(Run).where(Run.ended_at.is_(None))):
        reap(db, r)


def open_chat(db: Session, agent_id: int) -> Run | None:
    """The agent's running chat, if any. A routine's run, or one mail started, isn't a chat: talking to the agent starts its own."""
    for r in db.scalars(select(Run).where(Run.agent_id == agent_id, Run.routine_id.is_(None), Run.unattended.is_(False),
                                          Run.ended_at.is_(None))):
        reap(db, r)
        if r.ended_at is None:
            return r
    return None


def end_open_runs(db: Session, agent: Agent, why: str) -> None:
    """A sandbox gets its apps and team when it starts; after a change, the next message starts fresh."""
    for r in db.scalars(select(Run).where(Run.agent_id == agent.id, Run.ended_at.is_(None))):
        end(db, r, "stopped", why)


def reachable_problem() -> str | None:
    """A sandbox calls us back at public_url. If that doesn't answer (a stopped tunnel, a wrong
    URL), say so now instead of letting the person watch "starting" for minutes."""
    global _reachable_until
    if settings().sandbox_provider == "local" or time.monotonic() < _reachable_until:
        return None
    url = settings().public_url.rstrip("/") + "/api/health"
    try:
        ok = httpx.get(url, timeout=5, headers={"User-Agent": "agent-town-selfcheck"}).json().get("ok") is True
    except (httpx.HTTPError, ValueError, AttributeError):
        ok = False
    if not ok:
        return (f"Sandboxes reach Agent Town at {settings().public_url}, but nothing answers there. "
                "If that's a tunnel (ngrok), restart it and update AGENTTOWN_PUBLIC_URL.")
    _reachable_until = time.monotonic() + 60
    return None


class CantStart(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def new_run(db: Session, a: Agent, routine_id: int | None = None, first: str | None = None) -> tuple[Run, str]:
    """A run row and its token, with its first message already waiting if given. The caller
    starts the box with launch (after the response, or in the scheduler's own thread).
    For a routine, the database allows one open run at a time (a partial unique index), so two
    processes firing it together can't both start a box: the second gets CantStart."""
    m = build_manifest(db, a)
    if m["model"] is None:
        raise CantStart(422, "Add a model key or subscription first (your name, top right → Account and AI models)")
    problem = reachable_problem()
    if problem:
        raise CantStart(503, problem)
    token, token_hash = new_run_token()
    r = Run(agent_id=a.id, owner_id=a.owner_id, routine_id=routine_id, credential_id=m["model"]["credential_id"],
            provider=settings().sandbox_provider, token_hash=token_hash)
    db.add(r)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise CantStart(409, "It's already running") from None
    if first:
        db.add(RunEvent(run_id=r.id, kind="user", data={"text": first}))
    db.commit()
    return r, token


def launch(make_session: sessionmaker, run_id: int, token: str) -> None:
    """After the response is sent: ask the provider for a box. Slow on a cold start, which is
    why POST /runs answers 202 right away and the UI watches the status instead."""
    db = make_session()
    try:
        r = db.get(Run, run_id)
        try:
            sid = sandbox.provider(r.provider).start(run_id, token)
        except Exception as e:  # noqa: BLE001
            end(db, r, "error", f"Couldn't start the sandbox: {type(e).__name__}: {e}")
            return
        # Only a run that is still open keeps the box: one ended (by the owner, or reaped) while it
        # was booting would otherwise be forgotten and left running.
        kept = db.execute(update(Run).where(Run.id == run_id, Run.ended_at.is_(None)).values(sandbox_id=sid)).rowcount
        db.commit()
        if not kept:
            sandbox.provider(r.provider).stop(sid)
    finally:
        db.close()
