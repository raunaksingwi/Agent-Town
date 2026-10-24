"""The agent manifest: everything an agent is given when it runs.

This is the contract with the sandbox (runner/runner.py). The sandbox gets this JSON,
writes the files, connects only the listed tools, and starts the agent with AGENT.md as its
instructions. Secrets are NOT in here: the sandbox fetches the model credential and MCP auth headers
separately (/api/runtime/setup, with its run token), so a manifest can be logged or shown safely.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import views
from .config import settings
from .models import DEFINITION, Agent, McpConnection, ModelCredential, PublicShare, Run, RunEvent, SharedFile
from .timeutil import iso

DEFAULT_MODEL = {"anthropic": "claude-sonnet-5-5", "openai": ""}  # "": the provider's CLI default
# Thinking effort, from quick to thorough. Claude Code takes these as --effort; Codex has no "max",
# so the runner caps it at "xhigh" there.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
RECENT_CHATS = 5            # how many past chats it is shown, newest first
RECENT_CHARS = 30_000       # and at most this much of them; one long chat shouldn't crowd out the rest
RECENT_SAID = 2_000         # of any single message
ABOUT_ME = "about-me.md"    # what its owner told it alone: answers to its `ask:` questions, by form or in chat


def credential_for(db: Session, a: Agent) -> ModelCredential | None:
    """The agent's own credential, else its owner's default."""
    if a.model_credential_id:
        return db.get(ModelCredential, a.model_credential_id)
    return default_credential(db, a.owner_id)


def default_credential(db: Session, owner_id: int) -> ModelCredential | None:
    """Remembered for the session: the map asks for every agent's brain at once."""
    cache = db.info.setdefault("default_credential", {})
    if owner_id not in cache:
        cache[owner_id] = db.scalar(select(ModelCredential).where(ModelCredential.owner_id == owner_id,
                                                                   ModelCredential.is_default.is_(True)))
    return cache[owner_id]


def brain(db: Session, a: Agent) -> dict | None:
    """What it thinks with, for drawing its character: no secrets, just the provider and the names."""
    cred = credential_for(db, a)
    return {"provider": cred.provider, "model": a.model or DEFAULT_MODEL[cred.provider], "thinking": a.thinking} if cred else None


def granted_tools(a: Agent) -> list[dict]:
    tools = []
    for g in a.grants:
        c: McpConnection = g.connection
        usable = c.status == "connected" or c.status == "needs_sandbox"
        names = [t.name for t in c.tools] if g.tool_name is None else [g.tool_name]
        hosted = c.transport in ("hosted", "web")  # Gmail, Calendar, web APIs: served by Agent Town, reached with the run token
        tools.append({
            "connection_id": c.id, "connection": c.name, "transport": "http" if hosted else c.transport,
            "url": f"{settings().public_url.rstrip('/')}/api/runtime/mcp/{c.id}" if hosted else c.url,
            "hosted": hosted, "server": c.app if hosted else None,     # hosted: mcp__gmail__…, mcp__calendar__…
            "command": c.command, "status": c.status, "usable": usable,
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
                      for t in c.tools if t.name in names],
            "all_tools": g.tool_name is None,
        })
    return tools


def recent_chats(db: Session, a: Agent) -> list[dict]:
    """Its last few finished chats, words only (what was asked and what it answered, not its tool
    calls), so a new chat can pick up where the last one left off. Newest first, within a budget."""
    out, left = [], RECENT_CHARS
    runs = db.scalars(select(Run).where(Run.agent_id == a.id, Run.ended_at.is_not(None))
                      .order_by(Run.created_at.desc(), Run.id.desc()).limit(RECENT_CHATS))
    for r in runs:
        said = []
        for e in db.scalars(select(RunEvent).where(RunEvent.run_id == r.id, RunEvent.kind.in_(("user", "mail", "text")))
                            .order_by(RunEvent.id)):
            text = str(e.data.get("text", "")).strip()
            if text:
                said.append({"who": {"user": "owner", "mail": "mail"}.get(e.kind, "agent"),
                             "text": text if len(text) <= RECENT_SAID else text[:RECENT_SAID] + " …"})
        kept = []
        for x in reversed(said):            # a chat that doesn't fit keeps its latest words
            if len(x["text"]) > left:
                break
            kept.insert(0, x)
            left -= len(x["text"])
        if kept:
            out.append({"started_at": iso(r.created_at), "messages": kept, "cut": len(kept) < len(said)})
        if len(kept) < len(said):
            break                           # the budget is spent: older chats are left out
    return out


def interview(a: Agent, meta: dict[str, str]) -> list[str]:
    """Its `ask:` questions, while nobody has answered them yet: its first chat starts by getting to know
    its owner, in conversation, instead of a form. Once about-me.md exists (from that chat, or from
    Make it your own) there's nothing left to ask."""
    if any(f.path == ABOUT_ME for f in a.files):
        return []
    return [q.strip() for q in meta.get("ask", "").split("|") if q.strip()]


def build_manifest(db: Session, a: Agent) -> dict:
    own = views.definition(a)
    meta, body = views.frontmatter(own.content if own else "")
    tools = granted_tools(a)

    # its team: each member as a sub-agent, with its own instructions, files and tools (one level deep)
    team = []
    for m in a.team:
        md = views.definition(m)
        m_meta, m_body = views.frontmatter(md.content if md else "")
        team.append({"id": m.id, "name": m.name, "slug": m.slug, "description": m.description or m_meta.get("description", ""),
                     "instructions": m_body.strip(), "tools": granted_tools(m),
                     "files": [views.file_full(f) for f in m.files if f.path != DEFINITION]})

    public = []
    if a.can_use_public:
        for s in db.scalars(select(PublicShare).where(PublicShare.allow_agent_use.is_(True))
                            .order_by(PublicShare.created_at)):
            item = views.share(s, with_content=True)
            if s.kind == "agent" and s.agent_id == a.id:
                continue
            public.append(item)

    from . import mail  # here, not at the top: mail.py reads credentials from this module
    if mail.tools_for(db, a):                # a front door, or the mayor: mail, served by Agent Town (app/mail.py)
        tools.append({"connection_id": None, "connection": "Mail", "transport": "http", "hosted": True, "server": "mail",
                      "url": f"{settings().public_url.rstrip('/')}/api/runtime/mail", "command": None,
                      "status": "connected", "usable": True, "all_tools": True,
                      "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
                                for t in mail.tools_for(db, a)]})

    cred = credential_for(db, a)
    model = None
    if cred:
        model = {"credential_id": cred.id, "provider": cred.provider, "kind": cred.kind,
                 "status": cred.status, "model": a.model or DEFAULT_MODEL[cred.provider], "thinking": a.thinking}

    return {
        "version": 1,
        # The run is billed to this, the owner's own credential. None: they must add one first.
        "model": model,
        "agent": {"id": a.id, "owner": a.owner.username, "name": a.name, "slug": a.slug,
                  "description": a.description, "frontmatter": meta},
        "instructions": body.strip(),
        "files": [views.file_full(f) for f in a.files],
        # the owner's shared files: every one of their agents gets these
        "shared": [{"path": f.path, "lines": f.lines, "content": f.content} for f in db.scalars(
            select(SharedFile).where(SharedFile.owner_id == a.owner_id).order_by(SharedFile.path))],
        "tools": tools,
        "team": team,
        # what it remembers: its own notes (memory.md, saved back as it edits them) and its last chats
        "memory": a.memory,
        "recent_chats": recent_chats(db, a),
        # its own questions, still unanswered: it asks them in chat and writes the answers to about-me.md
        "interview": interview(a, meta),
        "public": public,
    }
