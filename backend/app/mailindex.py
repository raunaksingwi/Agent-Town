"""An index of who someone emails: the people, and the threads still waiting on a reply.

Instinct-style assistants copy your whole mailbox. This keeps the least that makes agents proactive:
for each email in the last DAYS days, who it was from and to, when, which thread, and its subject
(encrypted). Never its text. From that:

    people       who they write to and hear from, how often, and when last (mail_people)
    open loops   threads where the last word is someone they know, waiting on them; or theirs, gone quiet
    triggers     routines that run when an email arrives from someone they've written to

It's on for every Gmail account unless they turn it off, which deletes it (so does disconnecting).

Sync: the first time, the inbox's threads from the last DAYS days (not Promotions, Social, Updates or
Forums), at most MAX_THREADS. After that, Gmail's history API says which threads changed since the
last historyId, and only those are fetched again. A thread of its own runs this every few minutes (more
often for an account with an email routine), claiming each account with a conditional UPDATE so that
several API processes never sync the same one at once.
"""

import logging
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parseaddr

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from . import google
from .models import MailMessage, MailPerson, OAuthAccount, Routine, Run
from .security import decrypt, encrypt
from .timeutil import utc

log = logging.getLogger("agenttown.mailindex")

DAYS = 90
MAX_THREADS = 500
EVERY = timedelta(minutes=10)
EVERY_WATCHED = timedelta(minutes=2)       # an account with an email routine: new mail matters sooner
CLAIM = timedelta(minutes=10)
LOOP_SECONDS = 30
SKIP = "-category:promotions -category:social -category:updates -category:forums"
SKIP_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS", "SPAM", "TRASH", "DRAFT"}
HEADERS = ["From", "To", "Cc", "Subject"]
QUIET = timedelta(days=3)                  # your email with no answer for this long has "gone quiet"
LOOP_DAYS = 30                             # older threads aren't open loops any more, just old
TRIGGER_RUNS_PER_DAY = 20
ROBOT = re.compile(r"^(no-?reply|do-?not-?reply|notifications?|mailer-daemon|bounce)", re.I)


# ---- syncing ------------------------------------------------------------------------------------

def _thread(c, token: str, acct: OAuthAccount, db: Session, thread_id: str, names: dict[str, str]) -> list[MailMessage]:
    """Fetch one thread's headers and store what's new. Returns the emails it hadn't seen; senders'
    display names go into `names`."""
    try:
        t = google._get(c, f"{google.GMAIL}/threads/{thread_id}", token, format="metadata", metadataHeaders=HEADERS)
    except google.GoogleError as e:
        if e.status == 404:                # deleted since
            db.execute(delete(MailMessage).where(MailMessage.account_id == acct.id, MailMessage.thread_id == thread_id))
            return []
        raise
    have = set(db.scalars(select(MailMessage.gmail_id).where(MailMessage.account_id == acct.id,
                                                            MailMessage.thread_id == thread_id)))
    new = []
    for m in t.get("messages", []):
        labels = set(m.get("labelIds", []))
        if m["id"] in have or labels & SKIP_LABELS:
            continue
        h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
        name, sender = parseaddr(h.get("from", ""))
        mine = "SENT" in labels
        to = [(n, a.strip().lower()) for n, a in getaddresses([h.get("to", ""), h.get("cc", "")]) if "@" in a]
        people = [a for _, a in to if a != (acct.email or "").lower()] if mine else [sender.lower()]
        for n, a in ([(name, sender.lower())] if not mine else to):
            if n and n != a:
                names.setdefault(a, n)          # how they're named in the mail itself
        msg = MailMessage(account_id=acct.id, gmail_id=m["id"], thread_id=thread_id, from_me=mine, sender=sender.lower()[:320],
                          at=datetime.fromtimestamp(int(m.get("internalDate", 0)) / 1000, timezone.utc),
                          people=people[:50], subject_enc=encrypt(h.get("subject", "")[:500]))
        db.add(msg)
        new.append(msg)
    return new


def sync(db: Session, acct: OAuthAccount) -> list[MailMessage]:
    """Bring the index up to date. Returns the emails that are new since last time (for triggers)."""
    token = google.access_token(db, acct)
    new: list[MailMessage] = []
    names: dict[str, str] = {}
    with google.http() as c:
        changed: set[str] = set()
        if acct.index_history:
            try:
                page = None
                while True:
                    h = google._get(c, f"{google.GMAIL}/history", token, startHistoryId=acct.index_history,
                                    historyTypes="messageAdded", **({"pageToken": page} if page else {}))
                    for item in h.get("history", []):
                        for added in item.get("messagesAdded", []):
                            if not set(added["message"].get("labelIds", [])) & SKIP_LABELS:
                                changed.add(added["message"]["threadId"])
                    latest = h.get("historyId", acct.index_history)
                    page = h.get("nextPageToken")
                    if not page:
                        break
            except google.GoogleError as e:
                if e.status != 404:
                    raise
                acct.index_history = ""     # too old for Gmail to remember: start over
        if not acct.index_history:
            latest = google._get(c, f"{google.GMAIL}/profile", token).get("historyId", "")
            page = None
            while len(changed) < MAX_THREADS:
                lst = google._get(c, f"{google.GMAIL}/threads", token, q=f"newer_than:{DAYS}d {SKIP}", maxResults=100,
                                  **({"pageToken": page} if page else {}))
                changed.update(t["id"] for t in lst.get("threads", [])[:MAX_THREADS - len(changed)])
                page = lst.get("nextPageToken")
                if not page:
                    break
            first = True
        else:
            first = False
        for tid in sorted(changed):
            new += _thread(c, token, acct, db, tid, names)
    db.execute(delete(MailMessage).where(MailMessage.account_id == acct.id,
                                         MailMessage.at < datetime.now(timezone.utc) - timedelta(days=DAYS)))
    db.flush()
    rebuild(db, acct, names)
    acct.index_history, acct.index_synced_at, acct.index_detail = str(latest), datetime.now(timezone.utc), ""
    return [] if first else new


def rebuild(db: Session, acct: OAuthAccount, names: dict[str, str]) -> None:
    """mail_people from mail_messages: who, how often each way, and when last."""
    old = {p.email: p for p in db.scalars(select(MailPerson).where(MailPerson.account_id == acct.id))}
    stats: dict[str, dict] = defaultdict(lambda: {"sent": 0, "received": 0, "last_sent_at": None, "last_received_at": None})
    for m in db.scalars(select(MailMessage).where(MailMessage.account_id == acct.id)):
        for who in m.people:
            s = stats[who]
            k = "sent" if m.from_me else "received"
            s[k] += 1
            last = f"last_{k}_at"
            s[last] = max(s[last], utc(m.at)) if s[last] else utc(m.at)
    for email, s in stats.items():
        p = old.pop(email, None) or MailPerson(account_id=acct.id, email=email[:320])
        for k, v in s.items():
            setattr(p, k, v)
        if names.get(email):
            p.name = names[email][:200]
        db.add(p)
    for gone in old.values():
        db.delete(gone)


def forget(db: Session, acct: OAuthAccount) -> None:
    """Delete the index (turned off). Disconnecting deletes it too, through the foreign keys."""
    db.execute(delete(MailMessage).where(MailMessage.account_id == acct.id))
    db.execute(delete(MailPerson).where(MailPerson.account_id == acct.id))
    acct.index_history, acct.index_synced_at, acct.index_detail = "", None, ""


# ---- asking -------------------------------------------------------------------------------------

def ready(acct: OAuthAccount) -> bool:
    return acct.index_on and acct.index_synced_at is not None


def person(db: Session, acct: OAuthAccount, email: str) -> MailPerson | None:
    return db.scalar(select(MailPerson).where(MailPerson.account_id == acct.id, MailPerson.email == email.lower()))


def subject(m: MailMessage) -> str:
    return decrypt(m.subject_enc) or "" if m.subject_enc else ""


def loops(db: Session, acct: OAuthAccount, now: datetime | None = None, limit: int = 20) -> dict:
    """waiting_on_me: the last email in the thread is from someone they've written to, unanswered.
    gone_quiet: the last email is theirs, and nobody has answered it in QUIET."""
    now = now or datetime.now(timezone.utc)
    known = {p.email: p for p in db.scalars(select(MailPerson).where(MailPerson.account_id == acct.id, MailPerson.sent > 0))}
    last: dict[str, MailMessage] = {}
    for m in db.scalars(select(MailMessage).where(MailMessage.account_id == acct.id,
                                                  MailMessage.at >= now - timedelta(days=LOOP_DAYS)).order_by(MailMessage.at)):
        last[m.thread_id] = m
    mine, theirs = [], []
    for m in last.values():
        age = now - utc(m.at)
        if not m.from_me and m.sender in known and not ROBOT.match(m.sender):
            p = known[m.sender]
            mine.append({"thread_id": m.thread_id, "email_id": m.gmail_id, "subject": subject(m), "with": p.name or p.email,
                         "email": p.email, "at": utc(m.at).isoformat(), "days": age.days})
        elif m.from_me and age >= QUIET and (people := [x for x in m.people if not ROBOT.match(x)]):
            who = known.get(people[0])
            theirs.append({"thread_id": m.thread_id, "email_id": m.gmail_id, "subject": subject(m),
                           "with": (who.name if who and who.name else people[0]) + (f" +{len(people) - 1}" if len(people) > 1 else ""),
                           "email": people[0], "at": utc(m.at).isoformat(), "days": age.days})
    by_age = lambda x: x["at"]  # noqa: E731
    return {"waiting_on_me": sorted(mine, key=by_age)[:limit], "gone_quiet": sorted(theirs, key=by_age)[:limit]}


def find_people(db: Session, acct: OAuthAccount, query: str, limit: int = 10) -> list[dict]:
    q = f"%{query.strip().lower()}%"
    rows = db.scalars(select(MailPerson).where(MailPerson.account_id == acct.id,
                                               or_(MailPerson.email.like(q), MailPerson.name.ilike(q)))
                      .order_by(MailPerson.sent.desc(), MailPerson.received.desc()).limit(limit))
    rows = rows.all()
    mail = db.scalars(select(MailMessage).where(MailMessage.account_id == acct.id).order_by(MailMessage.at.desc())).all() if rows else []
    out = []
    for p in rows:
        recent = [m for m in mail if p.email in m.people][:5]
        out.append({"email": p.email, "name": p.name, "you_wrote_to_them": p.sent, "they_wrote_to_you": p.received,
                    "last_you_wrote": utc(p.last_sent_at).isoformat() if p.last_sent_at else None,
                    "last_they_wrote": utc(p.last_received_at).isoformat() if p.last_received_at else None,
                    "recent": [{"subject": subject(m), "at": utc(m.at).isoformat(), "from_you": m.from_me,
                                "thread_id": m.thread_id, "email_id": m.gmail_id} for m in recent]})
    return out


NAMES = {"find_people", "open_loops"}      # Gmail tools answered from the index (google.TOOLS), not by Google


def call(db: Session, acct: OAuthAccount, name: str, args: dict) -> dict:
    if not acct.index_on:
        return {"error": "The person turned off Agent Town's email index, so this isn't available. Use search_emails."}
    if acct.index_synced_at is None:
        return {"error": "Agent Town is still building the email index (a few minutes after connecting Gmail). "
                         "Use search_emails for now."}
    if name == "find_people":
        return {"people": find_people(db, acct, str(args.get("query", "")))}
    return loops(db, acct)


# ---- the background loop ------------------------------------------------------------------------

def due(db: Session, now: datetime) -> list[OAuthAccount]:
    watched = set(db.scalars(select(Routine.owner_id).where(Routine.trigger == "email", Routine.enabled.is_(True))))
    out = []
    for a in db.scalars(select(OAuthAccount).where(OAuthAccount.provider == "google", OAuthAccount.index_on.is_(True),
                                                   OAuthAccount.status == "connected")):
        if "gmail" not in google.apps_granted(a.scopes):
            continue
        if a.index_claimed_until and utc(a.index_claimed_until) > now:
            continue
        every = EVERY_WATCHED if a.owner_id in watched else EVERY
        if a.index_synced_at is None or now - utc(a.index_synced_at) >= every:
            out.append(a)
    return out


def claim(db: Session, a: OAuthAccount, now: datetime) -> bool:
    was = a.index_claimed_until
    got = db.execute(update(OAuthAccount).where(OAuthAccount.id == a.id, OAuthAccount.index_claimed_until.is_(None) if was is None
                                                else OAuthAccount.index_claimed_until == was)
                     .values(index_claimed_until=now + CLAIM)).rowcount
    db.commit()
    return bool(got)


def tick(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    for a in due(db, now):
        if not claim(db, a, now):
            continue                                   # another process has it
        db.refresh(a)
        try:
            new = sync(db, a)
            a.index_claimed_until = None
            db.commit()
            trigger(db, a, new, now)
        except google.Expired:
            db.rollback()
            a.index_claimed_until, a.index_detail = None, "The Google sign-in expired: connect Gmail again"
            db.commit()
        except Exception as e:  # noqa: BLE001  (one account mustn't stop the others)
            log.exception("mail index sync failed for account %s", a.id)
            db.rollback()
            a.index_claimed_until, a.index_detail = None, f"Couldn't update: {type(e).__name__}: {e}"[:300]
            db.commit()


def trigger(db: Session, acct: OAuthAccount, new: list[MailMessage], now: datetime) -> None:
    """Start each email routine of this person's for mail that arrived from someone they've written to.
    The mail comes from the index, not from what this sync fetched: seen_until is the routine's cursor,
    so mail that arrived while its last run was still going (or past the day's limit) is still there
    for the next tick instead of being lost. `new` only says whether there's any point looking."""
    from . import routines
    if not any(not m.from_me for m in new):
        return
    known = {p.email for p in db.scalars(select(MailPerson).where(MailPerson.account_id == acct.id, MailPerson.sent > 0))}
    for r in db.scalars(select(Routine).where(Routine.owner_id == acct.owner_id, Routine.trigger == "email",
                                              Routine.enabled.is_(True))):
        since = utc(r.seen_until) if r.seen_until else now - timedelta(days=1)
        rows = db.scalars(select(MailMessage).where(MailMessage.account_id == acct.id, MailMessage.from_me.is_(False),
                                                    MailMessage.at > since).order_by(MailMessage.at))
        mail = [m for m in rows if m.sender in known and not ROBOT.match(m.sender)]
        if not mail:
            continue
        runs = db.scalars(select(Run.id).where(Run.routine_id == r.id, Run.created_at >= now - timedelta(days=1))).all()
        if len(runs) >= TRIGGER_RUNS_PER_DAY:
            continue
        if routines.fire(db, r, now, mail=[{"email_id": m.gmail_id, "from": m.sender, "subject": subject(m),
                                            "at": utc(m.at).isoformat()} for m in mail]) is not None:
            r.seen_until = max(utc(m.at) for m in mail)
            db.commit()


def start(make_session: sessionmaker, stop: threading.Event) -> None:
    """The sync loop, in its own daemon thread: a first sync can take a minute, and routines mustn't wait."""
    def loop():
        while not stop.wait(LOOP_SECONDS):
            db = make_session()
            try:
                tick(db)
            except Exception:  # noqa: BLE001
                log.exception("mail index loop failed")
            finally:
                db.close()
    threading.Thread(target=loop, name="mailindex", daemon=True).start()
