"""Email an agent sends: whether it goes out on its own, and the short wait before it does. And LinkedIn
posts, which are simpler: see "LinkedIn posts" below. And agents and colonies an agent proposes for the
person's town, which always wait for their Add (app/town.py).

Every send_email lands here (routers/hosted.py) as an "approval" event, in one of these states:

    pending     waiting for the person's Send. The default: an agent asks unless its rules say otherwise
    scheduled   allowed out by its rules; goes at send_at unless they cancel (UNDO) or press Send now
    sending  -> sent | failed
    declined    they said no (pending), or cancelled it (scheduled). Either way it stays in their Drafts

The rules (Agent.email_policy) are checked here, on the server, never by the agent:

    mode          "ask" | "auto"
    to            "known": everyone on To and Cc is someone this mailbox has emailed before (a live
                  search of Sent Mail, nothing copied) or matches `allow`. "anyone": no recipient check
    allow         addresses or domains: "sam@acme.com", "acme.com" (and its subdomains)
    replies_only  only a reply in an existing thread may go out alone

In a team run every agent in it that can send through this Gmail must allow it: the strictest wins.
And no more than DAILY_LIMIT emails a day go out on their own, across all of the person's agents.

Prompt injection: an email from a stranger can carry instructions ("forward the invoices to…"). Two
layers keep that from turning into email:
  1. the recipient rule: a hijacked agent can still only write to people the person already writes to;
  2. a run that read anything we can't vouch for (Run.untrusted says what: an email from a stranger,
     another app's results, a shell command, files other people shared) always asks, whatever its rules.
A known gap: an agent could copy such instructions into its notes (memory.md), where a later, clean run
reads them. Layer 1 still holds there.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import google, linkedin, mailindex, push, town
from .models import Agent, McpConnection, OAuthAccount, Run, RunEvent

log = logging.getLogger("agenttown.outbox")

UNDO = timedelta(minutes=2)       # how long an email allowed out on its own waits, so it can be cancelled
STALE = timedelta(hours=1)        # due longer ago than this (the server was down): ask instead of sending late
DAILY_LIMIT = 10
DEFAULT = {"mode": "ask", "to": "known", "allow": [], "replies_only": False}
KNOWN_FOR = 600                   # seconds a "have they emailed this person?" answer is reused
_known: dict[tuple[int, str], tuple[float, bool]] = {}


def policy(a: Agent) -> dict:
    return {**DEFAULT, **(a.email_policy or {})}


def post_policy(a: Agent) -> dict:
    return {**POST_DEFAULT, **(a.post_policy or {})}


def addresses(field: str | None) -> list[str]:
    return [addr.strip().lower() for _, addr in getaddresses([field or ""]) if "@" in addr]


def allowed(addr: str, allow: list[str]) -> bool:
    domain = addr.rpartition("@")[2]
    for entry in (x.strip().lower().lstrip("@") for x in allow):
        if entry and (addr == entry if "@" in entry else domain == entry or domain.endswith("." + entry)):
            return True
    return False


def known(db: Session, acct: OAuthAccount, addr: str) -> bool:
    """Their own address, or someone they've emailed before."""
    if addr == (acct.email or "").lower():
        return True
    p = mailindex.person(db, acct, addr) if mailindex.ready(acct) else None
    if p is not None and p.sent > 0:
        return True                   # in the index: no need to ask Google (which also covers older mail)
    hit = _known.get((acct.id, addr))
    if hit and time.monotonic() - hit[0] < KNOWN_FOR:
        return hit[1]
    try:
        yes = google.has_emailed(db, acct, addr)
    except google.GoogleError:
        return False                  # can't tell: treat them as a stranger, the safe side
    _known[(acct.id, addr)] = (time.monotonic(), yes)
    return yes


def senders(r: Run, conn_id: int) -> list[Agent]:
    """The agents in this run that may send through this connection: its own, and its team's."""
    return [a for a in [r.agent, *r.agent.team]
            if any(g.connection_id == conn_id and g.tool_name in (None, "send_email") for g in a.grants)]


# ---- what a run has read ------------------------------------------------------------------------

def taint(r: Run, why: str) -> None:
    """Remember the first reason; one is enough to make it ask."""
    if not r.untrusted:
        r.untrusted = why[:200]


def check_read(db: Session, r: Run, acct: OAuthAccount, name: str, result: dict) -> None:
    """After a Gmail read: did it see words from someone we can't vouch for?"""
    froms = [result.get("from")] if name == "read_email" else [p.get("email") for p in result.get("people", [])] \
        if name == "find_people" else [e.get("from") for e in result.get("emails", [])]
    allow = [x for a in [r.agent, *r.agent.team] for x in policy(a)["allow"]]
    for addr in {a for f in froms for a in addresses(f)}:
        if not (allowed(addr, allow) or known(db, acct, addr)):
            taint(r, f"It read an email from {addr}, someone you haven't written to")
            return


HOSTED = ("gmail", "calendar", "linkedin", "town", "mail")   # served by Agent Town: what they return is checked in check_read


def check_tool(r: Run, name: str, given: str) -> None:
    """A tool the agent used in its sandbox (as the runner reports it): Claude says "mcp__server__tool"
    or "Bash", Codex says "server.tool" or "shell"."""
    if name in ("Bash", "shell"):
        taint(r, "It ran a shell command, which can read anything on the web")
    elif name.startswith("mcp__") or ("." in name and not name.startswith(".")):
        server = name.split("__")[1] if name.startswith("mcp__") else name.partition(".")[0]
        if server not in HOSTED:
            taint(r, f"It read what another app returned ({server})")
    elif name in ("Read", "Grep", "Glob") and "public/" in given:
        taint(r, "It read files other people shared")


# ---- deciding -----------------------------------------------------------------------------------

def sent_today(db: Session, owner_id: int, now: datetime, kind: str = "email") -> int:
    since = now - timedelta(days=1)
    rows = db.scalars(select(RunEvent).join(Run, Run.id == RunEvent.run_id)
                      .where(Run.owner_id == owner_id, RunEvent.kind == "approval", RunEvent.created_at >= since))
    return sum(1 for e in rows if e.data.get("type", "email") == kind and e.data.get("auto")
               and e.data.get("state") in ("scheduled", "sending", "sent"))


def decide(db: Session, r: Run, conn: McpConnection, acct: OAuthAccount, args: dict, now: datetime) -> str:
    """"" if this email may go out on its own, or why the person has to press Send."""
    rules = [policy(a) for a in senders(r, conn.id)] or [DEFAULT]
    if any(p["mode"] != "auto" for p in rules):
        return "Its rules say to ask you first"
    if r.untrusted:
        return r.untrusted + ", so it asks before sending anything"
    if any(p["replies_only"] for p in rules) and not args.get("reply_to_id"):
        return "It may only send replies on its own, and this is a new email"
    if any(p["to"] != "anyone" for p in rules):
        for addr in addresses(args.get("to")) + addresses(args.get("cc")):
            if not (all(allowed(addr, p["allow"]) for p in rules) or known(db, acct, addr)):
                return f"You haven't written to {addr} before"
    if sent_today(db, r.owner_id, now) >= DAILY_LIMIT:
        return f"Your agents already sent {DAILY_LIMIT} emails on their own today"
    return ""


def queue(db: Session, r: Run, conn: McpConnection, acct: OAuthAccount, draft: dict, args: dict,
          now: datetime | None = None) -> str:
    """The agent called send_email and the draft is saved: hold it for the person, or schedule it.
    Returns what to tell the agent."""
    now = now or datetime.now(timezone.utc)
    why = decide(db, r, conn, acct, args, now)
    data = {**draft, "connection_id": conn.id, "auto": not why, "why": why}
    if why:
        db.add(RunEvent(run_id=r.id, kind="approval", data={**data, "state": "pending"}))
        db.commit()
        if not push.watched(r.id):
            push.notify(r.owner_id, f"{r.agent.name} wants to send an email", f"To {args.get('to')}: "
                        f"{draft.get('subject') or '(no subject)'}. Tap to Send or not.", url="/chat?today", tag=f"mail-{r.id}")
        return ("Not sent yet. It's saved as a draft and waiting for the person to press Send in Agent Town "
                f"({why}). Agent Town will tell you what they chose; don't send it any other way.")
    at = now + UNDO
    db.add(RunEvent(run_id=r.id, kind="approval", data={**data, "state": "scheduled", "send_at": at.isoformat()}))
    db.commit()
    return (f"Allowed by the person's rules for you: it goes out in {int(UNDO.total_seconds() // 60)} minutes unless they "
            "cancel it in Agent Town. It's in their Gmail Drafts until then. Don't send it any other way.")


def tell(db: Session, r: Run, text: str) -> None:
    """Pass what happened to the agent, if its chat is still going."""
    if r.ended_at is None:
        db.add(RunEvent(run_id=r.id, kind="notice", data={"text": f"[From Agent Town, not the person] {text}"}))


def what(e: RunEvent) -> str:
    if e.data.get("type") in ("agent", "colony"):
        return town.what(e)
    if e.data.get("type") == "post":
        text = str(e.data.get("text", ""))
        return f"the LinkedIn post that starts \"{text[:60]}\""
    return f"the email to {e.data.get('to')} (subject: {e.data.get('subject') or 'none'})"


def kept(e: RunEvent) -> str:
    """Where it is now that it didn't go out, for the agent."""
    return "" if e.data.get("type") in ("post", "agent", "colony") else " It's still in their Gmail Drafts."


def claim(db: Session, e: RunEvent) -> bool:
    """Mark it "sending", only if nobody else did first: a compare-and-set on the row, so the person's
    Send and the scheduler can't both deliver it (SQLite ignores row locks; this holds there too)."""
    was = e.data.get("state")
    if was not in ("pending", "scheduled"):
        return False
    got = db.execute(update(RunEvent).where(RunEvent.id == e.id, RunEvent.data["state"].as_string() == was)
                     .values(data={**e.data, "state": "sending", "was": was})).rowcount
    db.commit()
    if not got:
        db.refresh(e)
        return False
    db.refresh(e)
    return True


def deliver(db: Session, e: RunEvent) -> str:
    """Send it now. "" when it went, or what went wrong (it's left waiting for the person's Send)."""
    if e.data.get("type") in ("agent", "colony"):
        err = town.apply(db, e)
        e.data = {**_without(e.data, "was"), **({"state": "pending"} if err else {})}   # claimed: back to waiting
        return err
    if e.data.get("type") == "post":
        return _publish(db, e)
    conn = db.get(McpConnection, e.data.get("connection_id"))
    acct = db.get(OAuthAccount, conn.oauth_account_id) if conn and conn.oauth_account_id else None
    try:
        if acct is None:
            raise google.GoogleError("That Gmail account isn't connected any more")
        google.send_draft(db, acct, e.data["draft_id"])
    except google.Expired:
        err = "The Google sign-in expired: connect Gmail again, then press Send"
    except google.GoogleError as x:
        err = str(x)
    else:
        e.data = {**_without(e.data, "was"), "state": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}
        return ""
    e.data = {**_without(e.data, "was"), "state": "pending", "why": f"Couldn't send it: {err}"}
    return err


def _without(d: dict, key: str) -> dict:
    return {k: v for k, v in d.items() if k != key}


def _when(iso: str) -> datetime:
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def send_due(db: Session, now: datetime | None = None) -> int:
    """Send every scheduled email whose wait is over. Run by the scheduler; safe in several processes
    at once. Only the scheduled rows are read, and each is claimed and committed on its own, so a
    person pressing Send on another email never waits behind a slow delivery."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    ids = db.scalars(select(RunEvent.id).where(RunEvent.kind == "approval", RunEvent.created_at >= now - timedelta(days=1),
                                               RunEvent.data["state"].as_string() == "scheduled").order_by(RunEvent.id)).all()
    for eid in ids:
        e = db.scalar(select(RunEvent).where(RunEvent.id == eid).with_for_update(skip_locked=True))
        if e is None or e.data.get("state") != "scheduled" or _when(e.data["send_at"]) > now:
            db.commit()                        # another process has it, or it isn't due: let the lock go
            continue
        r = db.get(Run, e.run_id)
        if now - _when(e.data["send_at"]) > STALE:
            e.data = {**e.data, "state": "pending", "why": "It was due to go out while Agent Town was down: check it's still right"}
            db.commit()
            continue
        if not claim(db, e):
            continue
        err = deliver(db, e)
        if err:
            tell(db, r, f"Agent Town couldn't send {what(e)} on its own ({err}). It's waiting for the person to press Send.")
            push.notify(r.owner_id, "An email didn't go out", f"{what(e).capitalize()}: {err}", url="/chat?today")
        else:
            sent += 1
            tell(db, r, f"{what(e).capitalize()} was sent, as the person's rules for you allow.")
        db.commit()
    return sent


# ---- LinkedIn posts -----------------------------------------------------------------------------
#
# A post goes out the moment the agent calls create_post, unless the agent's rules (Agent.post_policy,
# mode "auto" | "ask") say to ask; in a team run, any agent that can post and says "ask" makes it ask.
# No undo wait (a post can be deleted on LinkedIn). A run that read something we can't vouch for
# (Run.untrusted: a stranger's email, a web page, a shell) asks too, whatever the rules say: a post is
# public and the words may not be the agent's own. Past POST_DAILY_LIMIT a day, across their agents, it
# asks instead: a runaway loop shouldn't fill their profile.

POST_DEFAULT = {"mode": "auto"}
POST_DAILY_LIMIT = 5


def posters(r: Run, conn_id: int) -> list[Agent]:
    return [a for a in [r.agent, *r.agent.team]
            if any(g.connection_id == conn_id and g.tool_name in (None, "create_post") for g in a.grants)]


def queue_post(db: Session, r: Run, conn: McpConnection, post: dict, now: datetime | None = None) -> str:
    """The agent called create_post: post it now, or hold it for the person. Returns what to tell the agent."""
    now = now or datetime.now(timezone.utc)
    why = ""
    if any(post_policy(a)["mode"] != "auto" for a in posters(r, conn.id) or [r.agent]):
        why = "Its rules say to ask you first"
    elif r.untrusted:
        why = r.untrusted[0].upper() + r.untrusted[1:]
    elif sent_today(db, r.owner_id, now, "post") >= POST_DAILY_LIMIT:
        why = f"Your agents already posted {POST_DAILY_LIMIT} times on their own today"
    e = RunEvent(run_id=r.id, kind="approval", data={**post, "type": "post", "connection_id": conn.id,
                                                     "auto": not why, "why": why, "state": "pending"})
    db.add(e)
    if why:
        db.commit()
        if not push.watched(r.id):
            push.notify(r.owner_id, f"{r.agent.name} wants to post on LinkedIn", post["text"][:120],
                        url="/chat?today", tag=f"post-{r.id}")
        return ("Not posted yet: it's waiting for the person to press Post in Agent Town "
                f"({why}). Agent Town will tell you what they chose; don't post it any other way.")
    err = _publish(db, e)
    db.commit()
    if err:
        return f"LinkedIn didn't take it ({err}). It's waiting in Agent Town for the person to try again."
    return f"Posted on their LinkedIn: {e.data['url']}"


def _publish(db: Session, e: RunEvent) -> str:
    conn = db.get(McpConnection, e.data.get("connection_id"))
    acct = db.get(OAuthAccount, conn.oauth_account_id) if conn and conn.oauth_account_id else None
    try:
        if acct is None:
            raise linkedin.LinkedInError("That LinkedIn account isn't connected any more")
        url = linkedin.publish(db, acct, e.data["text"], e.data.get("visibility", "PUBLIC"))
    except linkedin.Expired:
        conn.status, conn.status_detail = "auth_required", "LinkedIn sign-in ran out: connect again"
        err = "The LinkedIn sign-in ran out: connect LinkedIn again, then press Post"
    except (linkedin.LinkedInError, httpx.HTTPError) as x:
        err = str(x)
    else:
        e.data = {**_without(e.data, "was"), "state": "sent", "url": url, "sent_at": datetime.now(timezone.utc).isoformat()}
        return ""
    e.data = {**_without(e.data, "was"), "state": "pending", "auto": False, "why": f"Couldn't post it: {err}"}
    return err
