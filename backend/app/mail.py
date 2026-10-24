"""Mail: the person's colonies writing to each other, and to the person.

A colony is reached through its front door: its lead, or an agent on its own (a member is reached
through its lead, with the Task tool, as before). Front doors get these tools, served by
routers/hosted.py at /api/runtime/mail like Agent Town's other hosted tools:

    list_colonies   who they can write to: each colony, what it's for, its lead, its AI
    send_message    write to a colony, in a new thread or one they're in
    ask_person      a question for the person, maybe with options: it waits in their mailbox (Today)
    tell_person     something for them to read, no answer needed
    finish_thread   the work in a thread is done: no more mail in it

Delivery. Mail to the person waits in their mailbox; their answer comes back to the asker as mail.
Mail to an agent is handed to its open chat if the person has one going (it shows there), or starts a
run of its own (unattended: like a routine's, it ends once the agent has answered). A new request
waits for the mayor (below) unless it's a reply the agent is waiting on, or comes from the person.
Each run starts with the thread so far, so nothing has to be remembered between runs.

The mayor. One agent per person (Agent.role "mayor", the market's `mayor`). Every MAYOR_EVERY, if mail
is waiting, the scheduler starts the mayor with what's waiting; it wakes the colonies whose mail is
worth doing now (`wake`), and the rest waits for its next look. No mail waiting: no run, nothing spent.
Without a mayor, mail goes straight through.

The loop guard. Agents writing to agents can go round forever, so every thread has limits, checked
here before each message: how many messages, what its runs cost, how long it's been open, and the
same two agents going back and forth with nobody else. Past one, the thread pauses and the person is
asked whether to let it go on. A thread can start at most MAX_CHILDREN threads, and those can't start
their own. And at most MAX_AWAKE unattended runs per person at once: the rest queue.

Prompt injection: mail from a run that read something we can't vouch for carries that (Mail.untrusted),
and the run that reads it inherits it, so its email still waits for the person's Send (app/outbox.py).
"""

import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from . import outbox, push, runs
from .manifest import credential_for
from .models import Agent, AgentTeam, Mail, MailThread, Run, RunEvent, User
from .timeutil import iso, utc

log = logging.getLogger("agenttown.mail")

MAX_HOPS = 30                  # messages in a thread before the person is asked (and again each time they say go on)
MAX_COST_USD = 2.0             # what a thread's runs may cost, likewise
OPEN_HOURS = 24                # how long a thread may run, likewise
PING_PONG = 10                 # the same two agents, nobody else, this many messages in a row
MAX_CHILDREN = 3               # threads one thread may start
MAX_PER_RUN = 20               # mail one run may send
MAX_AWAKE = 4                  # unattended runs at once, per person
MAYOR_EVERY = timedelta(minutes=30)
CONTEXT = 10                   # earlier messages handed over with a new one
CLIP = 1500                    # of each earlier message
MAX_BODY = 20_000
ROLE_MAYOR = "mayor"
MAYOR = "mayor"                 # the market agent that becomes it


class MailError(ValueError):
    """A bad call, said to the agent as the tool's error."""


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---- who's who ------------------------------------------------------------------------------------

def is_member(db: Session, a: Agent) -> bool:
    return db.scalar(select(AgentTeam.lead_id).where(AgentTeam.member_id == a.id).limit(1)) is not None


def front_doors(db: Session, owner_id: int) -> list[Agent]:
    """The agents mail can reach: leads and agents on their own. Not members, not the mayor."""
    members = select(AgentTeam.member_id)
    return list(db.scalars(select(Agent).where(Agent.owner_id == owner_id, Agent.id.not_in(members),
                                               Agent.role != ROLE_MAYOR).order_by(Agent.created_at)))


def mayor_of(db: Session, owner_id: int) -> Agent | None:
    return db.scalar(select(Agent).where(Agent.owner_id == owner_id, Agent.role == ROLE_MAYOR).limit(1))


def colony(a: Agent) -> str:
    return a.colony_name or (f"{a.name}'s colony" if a.team else a.name)


def label(a: Agent | None) -> str:
    """How mail names who wrote it: "ava (Assistant)", "the person"."""
    if a is None:
        return "the person"
    return f"{a.name} ({a.colony_name})" if a.colony_name and a.colony_name != a.name else a.name


def address(db: Session, owner_id: int, to: str) -> Agent:
    """A colony's name or its front door's name, any case."""
    key = " ".join(str(to or "").split()).lower()
    doors = front_doors(db, owner_id)
    hit = next((a for a in doors if a.colony_name and a.colony_name.lower() == key), None) \
        or next((a for a in doors if a.name.lower() == key or colony(a).lower() == key), None)
    if hit is None:
        raise MailError(f"No colony or agent called {to!r} takes mail. Call list_colonies for who does "
                        "(a team member is reached through its lead).")
    return hit


def tools_for(db: Session, a: Agent | None) -> list[dict]:
    """The mail tools an agent gets: front doors and the mayor, not members (nor the caretaker: None)."""
    if a is None:
        return []
    if a.role == ROLE_MAYOR:
        return [t for t in TOOLS if t["name"] in ("ask_person", "tell_person")] + MAYOR_TOOLS
    return [] if is_member(db, a) else TOOLS


# ---- the tools ------------------------------------------------------------------------------------

_THREAD = {"type": "integer", "description": "the thread's number, to write in one you're in (leave out to start a new one)"}
TOOLS = [
    {"name": "list_colonies", "description": "The person's other colonies you can write to: each one's name, what it's "
                                             "for, its lead, which AI it runs on, and whether it's awake now.",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "send_message", "description": "Write to another colony (its lead gets it). They answer by mail, which "
                                            "comes to you as a new message: don't wait for it in this turn. Say what you "
                                            "need, the context they can't see, and what to send back.",
     "inputSchema": {"type": "object", "properties": {
         "to": {"type": "string", "description": "the colony's name (or its lead's)"},
         "body": {"type": "string", "maxLength": MAX_BODY, "description": "the message, in markdown"},
         "subject": {"type": "string", "maxLength": 200, "description": "a few words, for a new thread"},
         "thread_id": _THREAD},
         "required": ["to", "body"]}},
    {"name": "ask_person", "description": "Ask the person something only they can decide. It waits in their mailbox "
                                          "and their answer comes back to you as mail, so carry on with what doesn't "
                                          "depend on it. Give options when the choice is between a few.",
     "inputSchema": {"type": "object", "properties": {
         "question": {"type": "string", "maxLength": 2000},
         "details": {"type": "string", "maxLength": MAX_BODY, "description": "what they need to decide well, in markdown"},
         "options": {"type": "array", "items": {"type": "string", "maxLength": 100}, "maxItems": 6},
         "thread_id": _THREAD},
         "required": ["question"]}},
    {"name": "tell_person", "description": "Leave the person something to read (a result, a draft to look at). No "
                                           "answer comes back.",
     "inputSchema": {"type": "object", "properties": {
         "subject": {"type": "string", "maxLength": 200}, "body": {"type": "string", "maxLength": MAX_BODY},
         "thread_id": _THREAD},
         "required": ["subject", "body"]}},
    {"name": "finish_thread", "description": "The work in a thread is done: close it, so nobody writes in it again. "
                                             "Whoever started a thread finishes it once they have what they asked for.",
     "inputSchema": {"type": "object", "properties": {"thread_id": _THREAD}, "required": ["thread_id"]}},
]
MAYOR_TOOLS = [
    {"name": "mailbag", "description": "The mail waiting for the person's colonies: who it's for, from whom, and "
                                       "what it says.",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "wake", "description": "Hand a colony its waiting mail now: Agent Town starts its lead. Leave mail that "
                                    "can wait: you'll see it again at your next look.",
     "inputSchema": {"type": "object", "properties": {
         "colony": {"type": "string", "description": "the colony (or its lead's name)"},
         "note": {"type": "string", "maxLength": 1000, "description": "optional: what you'd have it do first"}},
         "required": ["colony"]}},
]


def call(db: Session, r: Run, name: str, args: dict) -> str:
    """A tool call from a run. Returns what to tell the agent; MailError for a bad call."""
    if name not in {t["name"] for t in tools_for(db, r.agent)}:
        raise MailError(f"{name!r} isn't one of your mail tools")
    if name == "list_colonies":
        return json.dumps({"colonies": [
            {"colony": colony(a), "lead": a.name, "about": a.colony_about or a.description,
             "team": [m.name for m in a.team], "ai": (credential_for(db, a).provider if credential_for(db, a) else None),
             "awake": _open_run(db, a) is not None}
            for a in front_doors(db, r.owner_id) if a.id != r.agent_id]}, ensure_ascii=False, indent=1)
    if name == "send_message":
        to = address(db, r.owner_id, args.get("to", ""))
        if to.id == r.agent_id:
            raise MailError("That's you")
        m = send(db, r, to, _text(args, "body", MAX_BODY), subject=_text(args, "subject", 200, False),
                 thread_id=args.get("thread_id"))
        how = {"delivered": f"{to.name} has it now", "queued": f"{to.name} gets it as soon as there's room",
               "waiting": f"it waits for the mayor, who wakes {to.name} when it's worth doing"}[m.state]
        return (f"Sent in thread #{m.thread_id}: {how}. Their answer comes to you as mail; carry on with what "
                "doesn't depend on it, and end your turn when there's nothing more.")
    if name == "ask_person":
        m = send(db, r, None, _text(args, "details", MAX_BODY, False), kind="question",
                 subject=_text(args, "question", 2000), thread_id=args.get("thread_id"), options=_options(args))
        return f"Asked in thread #{m.thread_id}. Their answer comes to you as mail: carry on with what doesn't depend on it."
    if name == "tell_person":
        m = send(db, r, None, _text(args, "body", MAX_BODY), kind="fyi", subject=_text(args, "subject", 200),
                 thread_id=args.get("thread_id"))
        return f"It's in their mailbox (thread #{m.thread_id})."
    if name == "finish_thread":
        t = _thread(db, r, args.get("thread_id"))
        t.status, t.paused_reason = "done", ""
        db.commit()
        return f"Thread #{t.id} is finished."
    if name == "mailbag":
        waiting = _waiting(db, r.owner_id)
        return json.dumps({"waiting": [_brief(m) for m in waiting]} if waiting else {"waiting": [], "note": "Nothing is waiting."},
                          ensure_ascii=False, indent=1)
    if name == "wake":
        to = address(db, r.owner_id, args.get("colony", ""))
        held = [m for m in _waiting(db, r.owner_id) if m.to_id == to.id]
        if not held:
            raise MailError(f"Nothing is waiting for {to.name}")
        note = _text(args, "note", 1000, False)
        deliver(db, held, wake=True, note=f"The mayor woke you for this: {note}" if note else "")
        return f"Woke {to.name} with {len(held)} message{'s' if len(held) > 1 else ''}."
    raise MailError(f"No tool {name}")


def _text(args: dict, key: str, limit: int, required: bool = True) -> str:
    v = args.get(key)
    v = v.strip() if isinstance(v, str) else ""
    if required and not v:
        raise MailError(f"{key} is required")
    if len(v) > limit:
        raise MailError(f"{key} is longer than {limit} characters")
    return v


def _options(args: dict) -> list[str]:
    o = args.get("options") or []
    if not isinstance(o, list) or not all(isinstance(x, str) and x.strip() for x in o):
        raise MailError("options: a list of short answers")
    return [" ".join(x.split())[:100] for x in o][:6]


def _thread(db: Session, r: Run, thread_id) -> MailThread:
    """A thread this run's agent is in."""
    t = db.get(MailThread, thread_id) if isinstance(thread_id, int) else None
    if t is None or t.owner_id != r.owner_id:
        raise MailError(f"No thread #{thread_id}")
    in_it = t.started_by_id == r.agent_id or db.scalar(select(Mail.id).where(
        Mail.thread_id == t.id, (Mail.from_id == r.agent_id) | (Mail.to_id == r.agent_id)).limit(1)) is not None
    if not in_it:
        raise MailError(f"You're not in thread #{thread_id}")
    return t


# ---- sending, and the guard -----------------------------------------------------------------------

def send(db: Session, r: Run | None, to: Agent | None, body: str, kind: str = "message", subject: str = "",
         thread_id=None, options: list[str] | None = None, owner_id: int | None = None) -> Mail:
    """Write and deliver one message. r None: the person wrote it (owner_id is theirs)."""
    sender = r.agent if r else None
    owner_id = r.owner_id if r else owner_id
    t_now = now()
    if r is not None and db.scalar(select(func.count()).select_from(Mail).where(Mail.from_run_id == r.id)) >= MAX_PER_RUN:
        raise MailError(f"This chat has sent {MAX_PER_RUN} messages already: finish what's in hand, or ask the person")
    if thread_id is not None:
        t = _thread(db, r, thread_id) if r else db.get(MailThread, thread_id)
        if t is None or t.owner_id != owner_id:
            raise MailError(f"No thread #{thread_id}")
    else:
        t = _new_thread(db, r, owner_id, subject or (body.split("\n", 1)[0][:80] if body else ""), t_now)
    if r is not None:
        guard(db, t, sender, to, t_now)
    m = Mail(owner_id=owner_id, thread_id=t.id, from_id=sender.id if sender else None, to_id=to.id if to else None,
             kind=kind, body=(f"**{subject}**\n\n{body}".strip() if kind in ("question", "fyi") and subject else body),
             options=options or [], state="new", from_run_id=r.id if r else None,
             untrusted=r.untrusted if r else "", created_at=t_now)
    db.add(m)
    t.hops += 1
    t.updated_at = t_now
    if t.status == "done" and r is None:          # the person writing in a finished thread opens it again
        t.status = "open"
    db.flush()
    deliver(db, [m])
    return m


def _new_thread(db: Session, r: Run | None, owner_id: int, subject: str, t_now: datetime) -> MailThread:
    # only a run nobody is watching starts child threads: in a chat, the person is the one steering
    parent = db.get(MailThread, r.thread_id) if r is not None and r.unattended and r.thread_id else None
    if parent is not None:
        if parent.parent_id is not None:
            raise MailError(f"You're working on thread #{parent.id}, which another thread started: write in it "
                            "(thread_id) rather than starting more")
        kids = db.scalar(select(func.count()).select_from(MailThread).where(MailThread.parent_id == parent.id))
        if kids >= MAX_CHILDREN:
            raise MailError(f"Thread #{parent.id} has started {MAX_CHILDREN} threads already: write in one of those")
    t = MailThread(owner_id=owner_id, subject=" ".join(subject.split())[:200], started_by_id=r.agent_id if r else None,
                   parent_id=parent.id if parent else None, max_hops=MAX_HOPS, max_cost_usd=MAX_COST_USD,
                   open_until=t_now + timedelta(hours=OPEN_HOURS), created_at=t_now, updated_at=t_now)
    db.add(t)
    db.flush()
    return t


def guard(db: Session, t: MailThread, sender: Agent | None, to: Agent | None, t_now: datetime) -> None:
    """Before an agent's message: is this thread still allowed to go on? Past a limit it pauses and the
    person is asked; the agent is told to stop rather than retry."""
    if t.status == "done":
        raise MailError(f"Thread #{t.id} is finished: start a new one if there's new work")
    if t.status == "paused":
        raise MailError(f"Thread #{t.id} is paused ({t.paused_reason}): the person decides whether it goes on. "
                        "Don't write in it again until they do; end your turn.")
    why = None
    if t.hops >= t.max_hops:
        why = f"it reached {t.hops} messages"
    elif t.cost_usd >= t.max_cost_usd:
        why = f"its runs have cost ${t.cost_usd:.2f}"
    elif t_now > utc(t.open_until):
        why = "it has been going for a day"
    elif to is not None and sender is not None and _ping_pong(db, t, {sender.id, to.id}):
        why = f"{sender.name} and {to.name} have gone back and forth {PING_PONG} times"
    if why:
        pause(db, t, why)
        raise MailError(f"Thread #{t.id} is paused because {why}. The person decides whether it goes on: "
                        "don't write in it again until they do; end your turn.")


def _ping_pong(db: Session, t: MailThread, pair: set[int]) -> bool:
    last = db.scalars(select(Mail).where(Mail.thread_id == t.id).order_by(Mail.id.desc()).limit(PING_PONG - 1)).all()
    return len(last) == PING_PONG - 1 and all({m.from_id, m.to_id} == pair for m in last)


def pause(db: Session, t: MailThread, why: str) -> None:
    t.status, t.paused_reason = "paused", why[:300]
    db.add(Mail(owner_id=t.owner_id, thread_id=t.id, kind="guard", state="new", options=["Let it go on", "Stop it"],
                body=f"**Thread #{t.id} \"{t.subject}\" paused: {why}.**\n\nLet it go on (for another {MAX_HOPS} messages, "
                     f"${MAX_COST_USD:.2f} and a day), or stop it here?"))
    db.commit()                                       # kept, though the agent's call fails
    push.notify(t.owner_id, "A thread between your colonies paused", why, url="/chat?today", tag=f"thread-{t.id}")


def go_on(db: Session, t: MailThread) -> None:
    """The person let a paused thread go on: new limits from here."""
    t.status, t.paused_reason = "open", ""
    t.max_hops, t.max_cost_usd = t.hops + MAX_HOPS, t.cost_usd + MAX_COST_USD
    t.open_until = now() + timedelta(hours=OPEN_HOURS)
    deliver(db, list(db.scalars(select(Mail).where(Mail.thread_id == t.id, Mail.state == "held"))))


def spent(db: Session, r: Run, cost_usd) -> None:
    """A turn finished: what it cost counts against the thread its run is working on (a chat's turns are the
    person's own doing, so they don't)."""
    if r.unattended and r.thread_id and isinstance(cost_usd, (int, float)) and cost_usd > 0:
        db.execute(update(MailThread).where(MailThread.id == r.thread_id).values(cost_usd=MailThread.cost_usd + cost_usd))


# ---- delivering -----------------------------------------------------------------------------------

def _open_run(db: Session, a: Agent, chat: bool | None = None) -> Run | None:
    """Its open run: a chat (the person is talking to it), or one started by mail. Not a routine's."""
    q = select(Run).where(Run.agent_id == a.id, Run.ended_at.is_(None), Run.routine_id.is_(None))
    if chat is not None:
        q = q.where(Run.unattended.is_(not chat))
    for r in db.scalars(q.order_by(Run.id)):
        runs.reap(db, r)
        if r.ended_at is None:
            return r
    return None


def _awake(db: Session, owner_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Run).where(Run.owner_id == owner_id, Run.unattended.is_(True),
                                                                Run.ended_at.is_(None))) or 0


def _needs_mayor(db: Session, m: Mail) -> bool:
    """A new request from an agent waits for the mayor's look. A reply the agent is waiting on doesn't."""
    if m.from_id is None or mayor_of(db, m.owner_id) is None:
        return False
    asked = db.scalar(select(Mail.id).where(Mail.thread_id == m.thread_id, Mail.from_id == m.to_id).limit(1))
    return asked is None


def deliver(db: Session, mail: list[Mail], wake: bool = False, note: str = "") -> None:
    """Hand each message to where it goes now, or leave it waiting/queued. Commits."""
    by_to: dict[int, list[Mail]] = {}
    for m in mail:
        t = db.get(MailThread, m.thread_id)
        if t.status == "paused" and m.kind != "guard" and m.to_id is not None:
            m.state = "held"                              # goes once the person lets the thread go on
            continue
        if m.to_id is None:                               # the person's mailbox
            m.state = "new"
            if m.kind in ("question", "fyi"):
                push.notify(m.owner_id, f"{label(m.sender)} asks you" if m.kind == "question" else f"From {label(m.sender)}",
                            " ".join(m.body.split())[:120], url="/chat?today", tag=f"mail-{m.id}")
            continue
        chat = _open_run(db, m.recipient, chat=True)
        if chat is not None:                              # it shows in the chat the person has open
            _hand(db, chat, [m], note)
            continue
        if not wake and m.state != "queued" and _needs_mayor(db, m):
            m.state = "waiting"
            continue
        m.state = "queued"
        by_to.setdefault(m.to_id, []).append(m)
    db.commit()
    for msgs in by_to.values():
        _start(db, msgs, note)


def deliver_queued(db: Session) -> None:
    """The scheduler's sweep: queued mail goes as soon as there's room, and its agent isn't mid-run."""
    queued = db.scalars(select(Mail).where(Mail.state == "queued").order_by(Mail.id)).all()
    by_to: dict[int, list[Mail]] = {}
    for m in queued:
        by_to.setdefault(m.to_id, []).append(m)
    for msgs in by_to.values():
        _start(db, msgs)


def _start(db: Session, msgs: list[Mail], note: str = "") -> None:
    """A run of the recipient for these messages, if it isn't running one already and there's room."""
    to = msgs[0].recipient
    if to is None or _open_run(db, to, chat=False) is not None or _awake(db, to.owner_id) >= MAX_AWAKE:
        return                                            # stays queued: deliver_queued tries again
    chat = _open_run(db, to, chat=True)
    if chat is not None:
        _hand(db, chat, msgs, note)
        db.commit()
        return
    try:
        r, token = runs.new_run(db, to, first=None)
    except runs.CantStart as e:
        db.rollback()
        log.info("mail for agent %s can't start a run: %s", to.id, e.detail)
        return
    r.unattended = True
    _hand(db, r, msgs, note)
    db.commit()
    launch(db, r.id, token)


def launch(db: Session, run_id: int, token: str) -> None:
    """Start the box without holding up the caller: a cold start is slow."""
    threading.Thread(target=runs.launch, args=(sessionmaker(bind=db.get_bind(), expire_on_commit=False), run_id, token),
                     daemon=True).start()


def _hand(db: Session, r: Run, msgs: list[Mail], note: str = "") -> None:
    """Put these messages in a run's inbox, as one, with their threads so far."""
    t_now = now()
    for m in msgs:
        m.state, m.run_id, m.delivered_at = "delivered", r.id, t_now
        if m.untrusted:
            outbox.taint(r, f"It read mail from {label(m.sender)}, whose chat {m.untrusted[0].lower()}{m.untrusted[1:]}")
    r.thread_id = msgs[-1].thread_id
    # text: what the agent reads; said: just the new messages, for the person's view of the chat
    db.add(RunEvent(run_id=r.id, kind="mail", data={"text": text_for(db, msgs, r.unattended, note),
                                                     "mail": [m.id for m in msgs], "from": [label(m.sender) for m in msgs],
                                                     "said": [{"from": label(m.sender), "thread_id": m.thread_id,
                                                               "subject": db.get(MailThread, m.thread_id).subject,
                                                               "body": m.body} for m in msgs]}))
    db.flush()


def text_for(db: Session, msgs: list[Mail], unattended: bool, note: str = "") -> str:
    """What the agent reads: each message with its thread so far, and how to answer."""
    parts = []
    for m in msgs:
        t = db.get(MailThread, m.thread_id)
        earlier = db.scalars(select(Mail).where(Mail.thread_id == t.id, Mail.id < m.id, Mail.kind != "guard")
                             .order_by(Mail.id.desc()).limit(CONTEXT)).all()[::-1]
        lines = [f"Thread #{t.id}: \"{t.subject}\""]
        if earlier:
            lines.append("Earlier in it:")
            for e in earlier:
                said = e.body if len(e.body) <= CLIP else e.body[:CLIP] + " …"
                to = label(e.recipient) if e.to_id else "the person"
                lines.append(f"- {label(e.sender)} to {to}{' (answered: ' + e.answer + ')' if e.answer else ''}:\n{said}")
        who = "The person" if m.from_id is None else label(m.sender)
        lines.append(f"New, from {who}:\n{m.body}" + (f"\n\n(The person answered: {m.answer})" if m.answer else ""))
        parts.append("\n".join(lines))
    how = ("Nobody is watching this live: do the work, then answer by mail with send_message (same thread_id). "
           "If only the person can decide something, ask_person. When a thread you started has what it needed, "
           "finish_thread.") if unattended else \
          ("The person you're chatting with can see this. Answer the sender by mail with send_message (same thread_id).")
    return (f"[Mail in Agent Town. {how}" + (f" {note}" if note else "") + "]\n\n" + "\n\n---\n\n".join(parts))


# ---- the person's side ----------------------------------------------------------------------------

def answer(db: Session, m: Mail, text: str) -> None:
    """The person answered something in their mailbox. A guard's question decides its thread; any other
    goes back to whoever asked, as mail in the same thread."""
    m.answer, m.state = text[:MAX_BODY], "answered"
    t = db.get(MailThread, m.thread_id)
    if m.kind == "guard":
        if text == m.options[0]:
            go_on(db, t)
        else:
            t.status = "done"
            for held in db.scalars(select(Mail).where(Mail.thread_id == t.id, Mail.state == "held")):
                held.state = "dropped"
        db.commit()
        return
    if m.from_id is not None and m.kind == "question":
        reply = Mail(owner_id=m.owner_id, thread_id=t.id, from_id=None, to_id=m.from_id, kind="message", state="new",
                     body=f"Your question: {' '.join(m.body.split())[:300]}\n\nTheir answer: {text}")
        db.add(reply)
        t.hops += 1
        db.flush()
        deliver(db, [reply])
    db.commit()


def _waiting(db: Session, owner_id: int) -> list[Mail]:
    return list(db.scalars(select(Mail).where(Mail.owner_id == owner_id, Mail.state == "waiting").order_by(Mail.id)))


def _brief(m: Mail) -> dict:
    return {"for": colony(m.recipient) if m.recipient else None, "lead": m.recipient.name if m.recipient else None,
            "from": label(m.sender), "thread": m.thread_id, "waiting_since": iso(m.created_at),
            "says": m.body if len(m.body) <= CLIP else m.body[:CLIP] + " …"}


# ---- the mayor ------------------------------------------------------------------------------------

def triage(db: Session, t_now: datetime | None = None) -> list[Run]:
    """The scheduler's look at waiting mail: for each person with some, start their mayor (at most every
    MAYOR_EVERY, and not while it's still at it). No mayor: the mail goes straight through."""
    t_now = t_now or now()
    started = []
    for owner_id in db.scalars(select(Mail.owner_id).where(Mail.state == "waiting").distinct()).all():
        mayor = mayor_of(db, owner_id)
        if mayor is None:
            deliver(db, _waiting(db, owner_id), wake=True)
            continue
        user = db.get(User, owner_id)
        was = user.mayor_checked_at
        if (was is not None and t_now - utc(was) < MAYOR_EVERY) or _open_run(db, mayor) is not None:
            continue
        claimed = db.execute(update(User).where(User.id == owner_id, (User.mayor_checked_at == was) if was is not None
                                                else User.mayor_checked_at.is_(None)).values(mayor_checked_at=t_now)).rowcount
        db.commit()
        if not claimed:                                   # another process is doing this one
            continue
        try:
            r, token = runs.new_run(db, mayor, first=mayor_message(db, owner_id, t_now))
        except runs.CantStart as e:
            db.rollback()
            log.info("mayor of %s can't start: %s", owner_id, e.detail)
            continue
        r.unattended = True
        db.commit()
        launch(db, r.id, token)
        started.append(r)
    return started


def mayor_message(db: Session, owner_id: int, t_now: datetime) -> str:
    waiting = _waiting(db, owner_id)
    lines = []
    for m in waiting:
        b = _brief(m)
        hours = (t_now - utc(m.created_at)).total_seconds() / 3600
        lines.append(f"- for {b['for']} (lead {b['lead']}), from {b['from']}, thread #{b['thread']}, "
                     f"waiting {hours:.1f} h:\n  {' '.join(b['says'].split())[:600]}")
    return ("[From Agent Town: your look at the mail, every 30 minutes. Nobody is watching live. For each colony "
            "below, decide whether its mail is worth working on now (urgent, blocking someone, cheap, or waited long "
            "enough) and wake it; leave the rest, and you'll see it again next time. If something needs the person, "
            "ask_person. Finish with one line on what you woke and what you left.]\n\nWaiting:\n" + "\n".join(lines))
