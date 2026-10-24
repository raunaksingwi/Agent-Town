"""Routines: agents that work on a schedule.

A routine says which agent, what to do, and when ("weekdays at 08:00, Europe/London"). Each one keeps
next_run_at (UTC) up to date, so finding what's due is one indexed comparison. A thread in the API
process looks every SCHEDULER_SECONDS; for each due routine it moves next_run_at on and starts a run,
the same kind of run a chat starts, with the routine's job as the first message. The run ends by
itself once the agent has answered (routers/runs.py), and a box that died is noticed here too (app/runs.py), and the answer shows on the Today page. The same
loop sends each email whose undo wait is over (app/outbox.py).

Several API processes can run this loop at once: a routine is claimed with a conditional UPDATE
("move next_run_at on, if it's still the value I read"), so exactly one of them starts it.
"""

import logging
import threading
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from . import mail, outbox, runs
from .config import settings
from .models import Routine, Run, RunEvent
from .security import new_run_token

log = logging.getLogger("agenttown.routines")

SCHEDULER_SECONDS = 30
LATE = timedelta(hours=3)   # down for longer than this (a deploy, a laptop asleep): skip that one, don't run it late
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Ready-made routines for the founder team, offered on Today when that agent is in town.
SUGGESTED = [                                  # "trigger" is "schedule" unless it says otherwise
    {"slug": "ava", "name": "Daily brief", "days": "01234", "at": "08:00",
     "prompt": "Brief me for today: what needs me, today's meetings, the drafts your team made, and what's "
               "waiting on others."},
    {"slug": "cleo", "name": "New email", "days": "0123456", "at": "08:00", "trigger": "email",
     "prompt": "Sort these new emails. Draft a reply to each one that needs it, and tell me only what needs my call."},
    {"slug": "finn", "name": "Follow-ups", "days": "024", "at": "10:00",
     "prompt": "Find the threads waiting on me and the ones that went quiet. Draft a reply or a nudge for each "
               "one worth it, oldest first."},
    {"slug": "maya", "name": "Morning brief", "days": "01234", "at": "08:00",
     "prompt": "Brief me for today. Check my inbox and calendar (ask Emma), and deals that went quiet (ask Sam). "
               "Give me: the few things only I can do today, the meetings to prep for, and the drafts waiting for me."},
    {"slug": "sam", "name": "Deal follow-ups", "days": "03", "at": "09:00",
     "prompt": "Find the deals and people I haven't followed up with in over a week. Draft a short follow-up to each "
               "and list them, most valuable first."},
    {"slug": "nora", "name": "Weekly investor update", "days": "4", "at": "16:00",
     "prompt": "Draft this week's investor update from what happened this week (my sent mail and calendar): "
               "wins, numbers I mentioned, asks. Mark anything you're unsure of with [check]."},
]


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown time zone {name!r}") from None


def next_time(days: str, at: str, tz: str, after: datetime) -> datetime | None:
    """The first time strictly after `after` that is on one of `days` at `at`, local time, in UTC.
    Local time on purpose: "08:00" stays 08:00 for the person when the clocks change."""
    if not days:
        return None
    z, (h, m) = zone(tz), map(int, at.split(":"))
    start: date = after.astimezone(z).date()
    for i in range(8):
        d = start + timedelta(days=i)
        if str(d.weekday()) in days:
            t = datetime.combine(d, time(h, m), tzinfo=z)
            if t > after:
                return t.astimezone(timezone.utc)
    return None


def describe(r: Routine) -> str:
    """ "Weekdays at 08:00", or "When email arrives from someone you've written to" """
    if r.trigger == "email":
        return "When email arrives from someone you've written to"
    days = "".join(sorted(set(r.days)))
    when = {"0123456": "Every day", "01234": "Weekdays", "56": "Weekends"}.get(days) \
        or ", ".join(DAY_NAMES[int(d)] for d in days)
    return f"{when} at {r.at}"


def schedule(r: Routine, now: datetime | None = None) -> None:
    """Set next_run_at from the schedule (none while it's off)."""
    r.next_run_at = next_time(r.days, r.at, r.timezone, now or datetime.now(timezone.utc)) \
        if r.enabled and r.trigger == "schedule" else None      # email routines start from app/mailindex.py


def first_message(r: Routine, now: datetime, mail: list[dict] | None = None) -> str:
    local = now.astimezone(zone(r.timezone)).strftime("%A %d %B %Y, %H:%M")
    if mail:
        new = "\n".join(f"- email_id {m['email_id']}: from {m['from']}, \"{m['subject']}\" ({m['at']})" for m in mail)
        why = f"started because new email arrived ({local}, {r.timezone}). Read it with read_email:\n{new}\n"
    else:
        why = f"running on its schedule ({local}, {r.timezone}). "
    return (f"[From Agent Town: this is your routine \"{r.name}\", {why}"
            "Nobody is watching live and nobody will answer questions, so make sensible assumptions and say what "
            "they were. A decision that needs the person is left for them. To email someone, use send_email: Agent "
            "Town holds it for their Send unless their rules for you let it go, so don't wait for an answer. "
            "Finish with a short report for their Today page: the result first, then what's "
            "waiting on them.]\n\n" + r.prompt)


def fire(db: Session, r: Routine, now: datetime | None = None, mail: list[dict] | None = None) -> Run | None:
    """Start a run of this routine now (for an email routine: about these new emails). Returns the run
    (already failed if it couldn't start, so the Today page says why), or None when the last one is still going.
    Two callers at once (the scheduler and a Run now click) can't both start it: the database allows
    one open run per routine, so the second insert fails and that caller gets None."""
    now = now or datetime.now(timezone.utc)
    for old in db.scalars(select(Run).where(Run.routine_id == r.id, Run.ended_at.is_(None))):
        runs.reap(db, old)
        if old.ended_at is None:
            return None
    try:
        run, token = runs.new_run(db, r.agent, routine_id=r.id, first=first_message(r, now, mail))
    except runs.CantStart as e:
        db.rollback()
        if e.status == 409:
            return None
        run = Run(agent_id=r.agent_id, owner_id=r.owner_id, routine_id=r.id, provider=settings().sandbox_provider,
                  token_hash=new_run_token()[1], status="error", detail=e.detail, ended_at=now)
        db.add(run)
        db.flush()
        db.add(RunEvent(run_id=run.id, kind="status", data={"status": "error", "detail": e.detail}))
        db.commit()
        return run
    launch(runs.launch, sessionmaker(bind=db.get_bind(), expire_on_commit=False), run.id, token)
    return run


def launch(start, *args) -> None:
    """Ask the provider for a box without holding up the scheduler (or the request): a cold start is slow."""
    threading.Thread(target=start, args=args, daemon=True).start()


def tick(db: Session, now: datetime | None = None) -> list[Run]:
    """Start every routine that's due. Safe to call from several processes at once."""
    now = now or datetime.now(timezone.utc)
    started = []
    due = db.scalars(select(Routine).where(Routine.enabled.is_(True), Routine.next_run_at <= now)).all()
    for r in due:
        was = r.next_run_at
        nxt = next_time(r.days, r.at, r.timezone, now)
        claimed = db.execute(update(Routine).where(Routine.id == r.id, Routine.next_run_at == was)
                             .values(next_run_at=nxt)).rowcount
        db.commit()
        if not claimed:
            continue                                   # another process got it
        db.refresh(r)
        if now - (was if was.tzinfo else was.replace(tzinfo=timezone.utc)) > LATE:
            log.info("routine %s skipped: due at %s, more than %s ago", r.id, was, LATE)
            continue
        try:
            if (run := fire(db, r, now)) is not None:
                started.append(run)
        except Exception:  # noqa: BLE001  (one bad routine mustn't stop the others)
            log.exception("routine %s failed to start", r.id)
            db.rollback()
    return started


def start_scheduler(make_session: sessionmaker) -> threading.Event:
    """The loop, in a daemon thread. Set the returned event to stop it."""
    stop = threading.Event()

    def loop():
        while not stop.wait(SCHEDULER_SECONDS):
            db = make_session()
            try:
                # routines that are due, emails whose wait is over, boxes that died while nobody was looking,
                # mail that has room to go now, and the mayor's look at what's waiting (app/mail.py)
                for job in (tick, outbox.send_due, runs.reap_all, mail.deliver_queued, mail.triage):
                    try:
                        job(db)
                    except Exception:  # noqa: BLE001  (one failing mustn't stop the other)
                        log.exception("scheduler: %s failed", job.__name__)
                        db.rollback()
            finally:
                db.close()

    threading.Thread(target=loop, name="routines", daemon=True).start()
    return stop
