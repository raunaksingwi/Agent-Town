"""The tables.

users ─┬─ sessions                 browser logins (only a hash of the cookie is stored)
       ├─ api_tokens               "Authorization: Bearer at_…" for scripts and sandboxes (hashed too)
       ├─ push_subscriptions       devices that get notifications (app/push.py)
       ├─ model_credentials        the user's own API key / subscription token, encrypted
       ├─ agents ─┬─ agent_files    the agent's markdown: AGENT.md plus any knowledge files
       │          ├─ agent_team     which of the owner's other agents it may call (its sub-agents)
       │          └─ agent_tool_grants ──┐  which tools this agent may use
       ├─ mcp_connections ─ mcp_tools ◄──┘  a user's MCP servers and the tools they expose
       ├─ oauth_accounts ─┬─ mail_messages   accounts signed in with OAuth (Google): their tokens, encrypted;
       │                  └─ mail_people     and an index of who they email (metadata only, app/mailindex.py)
       ├─ shared_files              knowledge every one of the user's agents can read (private)
       ├─ public_shares             what a user put in the public district
       ├─ routines                  a job an agent does on a schedule ("weekdays at 8: brief me")
       ├─ mail_threads ─ mail       agents writing to each other's colonies, and to the person (app/mail.py)
       ├─ caretaker_turns           what they said with the caretaker, the platform's help (app/caretaker.py)
       └─ runs ─ run_events         an agent running in its own sandbox, and what it said and did
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))   # "" for an account made with Google: no password
    # Google's id for the account they sign in with ("sub"): it stays the same when their email changes
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    # when we last had proof they own `email` (Google said so). None: typed into the sign-up form,
    # unconfirmed, so a Google sign-in for that address takes the account over (routers/auth.py)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # where the user moved buildings on their map: {"agent:12": [x, y], ...}, in tiles from the square
    town: Mapped[dict] = mapped_column(JSON, default=dict)
    # how the map looks: retro | fantasy | office ("" = not chosen here: the browser's own choice, else retro)
    map_style: Mapped[str] = mapped_column(String(20), default="", server_default="")
    # which conversation with the caretaker is current: "Start over" moves on to the next (app/caretaker.py)
    caretaker_conversation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # colonies they named before putting any agents in: [{"name": ..., "about": ...}]. Once one has a
    # lead and a team it lives on the lead like any other (Agent.colony_name) and leaves this list.
    empty_colonies: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # when their mayor last looked at the mail waiting for their colonies (app/mail.py)
    mayor_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agents: Mapped[list["Agent"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # sha256 of the cookie value. A leaked database can't be replayed as cookies.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class ApiToken(Base):
    """A long-lived token for programs: the CLI and scripts. (Sandboxes get a run token instead.)
    Shown once at creation; only its sha256 is stored, like sessions."""
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))  # first characters, so you can tell tokens apart
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship()


class PushSubscription(Base):
    """A browser or installed app that gets notifications. endpoint is at the browser's push service;
    p256dh and auth are its public keys, which we encrypt each notification to."""
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelCredential(Base):
    """What an agent's model calls are paid with: the user's own, never the platform's.
    provider: anthropic | openai.  kind: api_key | subscription (Claude `setup-token`,
    Codex auth.json). The secret is Fernet-encrypted and never leaves the server through the API."""
    __tablename__ = "model_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(80))
    secret_enc: Mapped[str] = mapped_column(Text)
    hint: Mapped[str] = mapped_column(String(12), default="")  # last 4 characters, to recognise it
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # unverified | valid | invalid | error
    status: Mapped[str] = mapped_column(String(20), default="unverified")
    status_detail: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("owner_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(7), default="#8a6fd1")
    # May this agent read what other people shared in the public district?
    can_use_public: Mapped[bool] = mapped_column(Boolean, default=True)
    # Which of the owner's model credentials it runs on (None: the owner's default) and which model.
    model_credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_credentials.id", ondelete="SET NULL"), index=True)
    model: Mapped[str] = mapped_column(String(100), default="")
    # How hard it thinks before answering: low … max ("" = the model's own default). See manifest.EFFORTS.
    thinking: Mapped[str] = mapped_column(String(10), default="")
    # What its building looks like on the map: studio, forge, library… ("" = picked from its description)
    building: Mapped[str] = mapped_column(String(20), default="")
    # What it remembers between chats: memory.md in its sandbox, saved back as it changes. Private to the
    # owner: never part of a share, an export or a teammate's files.
    memory: Mapped[str] = mapped_column(Text, default="")
    # When an email it sends may go out without the owner pressing Send: see app/outbox.py ({} = always ask)
    email_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    # Whether a LinkedIn post it writes goes out at once or waits for the owner: see app/outbox.py ({} = at once)
    post_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    # When it leads a team, that team is a colony: its name and what it's for ("" = named after the lead)
    colony_name: Mapped[str] = mapped_column(String(60), default="")
    colony_about: Mapped[str] = mapped_column(String(300), default="")
    # "mayor": the one agent that looks at waiting mail and wakes colonies for it (app/mail.py). "" = any other
    role: Mapped[str] = mapped_column(String(12), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    owner: Mapped[User] = relationship(back_populates="agents")
    files: Mapped[list["AgentFile"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="AgentFile.path")
    grants: Mapped[list["AgentToolGrant"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan")
    team: Mapped[list["Agent"]] = relationship(
        secondary="agent_team", primaryjoin="Agent.id == AgentTeam.lead_id", secondaryjoin="Agent.id == AgentTeam.member_id",
        order_by="Agent.name")


DEFINITION = "AGENT.md"


class AgentTeam(Base):
    """A lead agent may call a member agent, like Claude Code's sub-agents: both are the same
    owner's, and the member keeps only its own files and tools."""
    __tablename__ = "agent_team"

    lead_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)


class AgentFile(Base):
    __tablename__ = "agent_files"
    __table_args__ = (UniqueConstraint("agent_id", "path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    lines: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    agent: Mapped[Agent] = relationship(back_populates="files")

    def set_content(self, content: str) -> None:
        self.content = content
        self.lines = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
        self.bytes = len(content.encode())


class SharedFile(Base):
    """A file all of its owner's agents can read: a playbook or "about us" that several agents
    use, kept once instead of copied into each. Private, like the agents themselves.
    In a run it's written at its own path, next to the agent's own files (which win on a clash)."""
    __tablename__ = "shared_files"
    __table_args__ = (UniqueConstraint("owner_id", "path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    lines: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    set_content = AgentFile.set_content


class OAuthAccount(Base):
    """An account someone signed into with OAuth, like Composio's "connected account": which provider,
    which of their accounts, which scopes they allowed, and the tokens (encrypted). Agent Town hosts
    the tools for it itself, so the tokens never go into a sandbox.
    status: connected | expired (refreshing failed: they need to sign in again)"""
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("owner_id", "provider", "subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))          # google | linkedin
    subject: Mapped[str] = mapped_column(String(255))          # the provider's id for the account
    email: Mapped[str] = mapped_column(String(320), default="")
    scopes: Mapped[str] = mapped_column(Text, default="")      # space-separated, as granted
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="")
    access_token_enc: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="connected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # The index of who they email (app/mailindex.py): on unless they turn it off, which deletes it.
    index_on: Mapped[bool] = mapped_column(Boolean, default=True)
    index_history: Mapped[str] = mapped_column(String(40), default="")    # Gmail's historyId we're synced up to
    index_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    index_claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # one process syncs it at a time
    index_detail: Mapped[str] = mapped_column(String(300), default="")    # the last problem, for the person


class MailMessage(Base):
    """One email in the index: who, when, which thread, and its subject (encrypted). Never its text.
    people: the other side: its sender if it came in, its recipients if it was sent."""
    __tablename__ = "mail_messages"
    __table_args__ = (UniqueConstraint("account_id", "gmail_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("oauth_accounts.id", ondelete="CASCADE"), index=True)
    gmail_id: Mapped[str] = mapped_column(String(40))
    thread_id: Mapped[str] = mapped_column(String(40), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    from_me: Mapped[bool] = mapped_column(Boolean)
    sender: Mapped[str] = mapped_column(String(320))
    people: Mapped[list] = mapped_column(JSON, default=list)
    subject_enc: Mapped[str] = mapped_column(Text, default="")


class MailPerson(Base):
    """Someone they email or hear from, summed up from mail_messages after each sync."""
    __tablename__ = "mail_people"
    __table_args__ = (UniqueConstraint("account_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("oauth_accounts.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200), default="")
    sent: Mapped[int] = mapped_column(Integer, default=0)          # emails they sent this person
    received: Mapped[int] = mapped_column(Integer, default=0)      # emails this person sent them
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpConnection(Base):
    __tablename__ = "mcp_connections"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    transport: Mapped[str] = mapped_column(String(10))       # "http" | "stdio" | "hosted" | "web"
    url: Mapped[str | None] = mapped_column(Text)            # http: the server; web: only what's shown of it
    url_enc: Mapped[str | None] = mapped_column(Text)        # web: the API's base URL, Fernet-encrypted
    command: Mapped[str | None] = mapped_column(Text)        # stdio: runs in the sandbox, later
    auth_header_enc: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted Authorization value
    # Encrypted JSON, see app/mcp_auth.py: other headers (http), the command's environment (stdio),
    # and its sign-in (the app's endpoints, our client id, the tokens)
    headers_enc: Mapped[str | None] = mapped_column(Text)
    env_enc: Mapped[str | None] = mapped_column(Text)
    oauth_enc: Mapped[str | None] = mapped_column(Text)
    # transport "hosted": tools Agent Town serves itself (Gmail, Calendar) for this signed-in account
    oauth_account_id: Mapped[int | None] = mapped_column(ForeignKey("oauth_accounts.id", ondelete="CASCADE"), index=True)
    app: Mapped[str] = mapped_column(String(30), default="")  # hosted: gmail | calendar | linkedin
    # unknown | connected | auth_required | error | needs_sandbox
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    status_detail: Mapped[str] = mapped_column(Text, default="")
    server_name: Mapped[str] = mapped_column(String(200), default="")
    server_version: Mapped[str] = mapped_column(String(80), default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    tools: Mapped[list["McpTool"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan", order_by="McpTool.name")


class McpTool(Base):
    __tablename__ = "mcp_tools"
    __table_args__ = (UniqueConstraint("connection_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("mcp_connections.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)

    connection: Mapped[McpConnection] = relationship(back_populates="tools")


class AgentToolGrant(Base):
    """Agent may use a connection's tools: all of them (tool_name NULL) or one by name."""
    __tablename__ = "agent_tool_grants"
    __table_args__ = (UniqueConstraint("agent_id", "connection_id", "tool_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("mcp_connections.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str | None] = mapped_column(String(200))

    agent: Mapped[Agent] = relationship(back_populates="grants")
    connection: Mapped[McpConnection] = relationship()


class PublicShare(Base):
    """Something a user put in the public district: a whole agent, or one of its files.
    Everyone can see it; other people's agents can use it if allow_agent_use."""
    __tablename__ = "public_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))   # "agent" | "file"
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("agent_files.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")  # what it's for / how to use it
    allow_agent_use: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    owner: Mapped[User] = relationship()
    agent: Mapped[Agent | None] = relationship()
    file: Mapped[AgentFile | None] = relationship()


class Routine(Base):
    """A job an agent does on its own, on a schedule: "every weekday at 8:00, brief me". When it's
    due, Agent Town starts a run, hands the agent `prompt` as the first message, and ends the run
    once it has answered. The answer lands on the owner's Today page.

    days: which weekdays, as digits Monday=0 … Sunday=6 ("01234" = weekdays). at: "HH:MM" in `timezone`.
    next_run_at is when it's due next (UTC), kept up to date so the scheduler only compares times."""
    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    prompt: Mapped[str] = mapped_column(Text)
    days: Mapped[str] = mapped_column(String(7), default="01234")
    at: Mapped[str] = mapped_column(String(5), default="08:00")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # "schedule": on its days at its time. "email": when mail arrives from someone they've written to
    # (app/mailindex.py); seen_until is the newest such email it has already run for.
    trigger: Mapped[str] = mapped_column(String(10), default="schedule")
    seen_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    agent: Mapped[Agent] = relationship()


class Run(Base):
    """One sandbox for one agent: started when its owner opens a chat (or a routine is due), stopped
    when they close it or it goes idle. Many turns (messages) happen in one run.
    kind "caretaker": the caretaker's own sandbox, no agent (app/caretaker.py), for people whose AI is
    a subscription, which only works inside Claude Code.

    status: starting -> ready <-> busy -> stopped | error.
    The sandbox authenticates with a run token ("rt_…"): only its sha256 is stored, it works only
    for this run, and only until the run ends."""
    __tablename__ = "runs"
    __table_args__ = (
        # One open run per routine: the scheduler and a "Run now" click firing together can't both start a box
        Index("ix_runs_routine_open", "routine_id", unique=True,
              postgresql_where=text("ended_at IS NULL"), sqlite_where=text("ended_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="agent", server_default="agent")   # agent | caretaker
    # Started by a routine, not a chat: nobody is watching, and it ends once the agent has answered.
    routine_id: Mapped[int | None] = mapped_column(ForeignKey("routines.id", ondelete="SET NULL"), index=True)
    credential_id: Mapped[int | None] = mapped_column(ForeignKey("model_credentials.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="starting")
    detail: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(20))         # local | modal
    sandbox_id: Mapped[str] = mapped_column(String(200), default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)  # owner's last message
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)    # sandbox's last poll
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)   # open runs: WHERE ended_at IS NULL
    # Why we can't vouch for everything this run read ("" = we can): an email from a stranger, another
    # app, a shell command. Such a run never sends email on its own (app/outbox.py).
    untrusted: Mapped[str] = mapped_column(String(200), default="")
    # Started by mail or for the mayor, not by a chat: like a routine's, nobody is watching and it ends
    # once the agent has answered (app/mail.py)
    unattended: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # The mail thread it is working on: what its turns cost counts against that thread's limit
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("mail_threads.id", ondelete="SET NULL"))

    agent: Mapped[Agent | None] = relationship()


class RunEvent(Base):
    """Everything in a run's conversation, in order (id is the cursor). kind:
    user | text | tool | tool_result | done | status | error, from the sandbox (but `user`), and two
    from Agent Town: approval (an email the agent sent, or a LinkedIn post: waiting for the owner's
    yes, about to go out by their rules, or gone; see app/outbox.py) and notice (what happened to it, handed to the agent like a
    message)."""
    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_kind_created_at", "kind", "created_at"),)   # the outbox reads approvals by date

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MailThread(Base):
    """A conversation by mail between the person's colonies (and them). The loop guard's counters live
    here: a thread that runs too long, costs too much or goes back and forth too often pauses and asks
    the person (app/mail.py). status: open | paused | done."""
    __tablename__ = "mail_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(10), default="open")
    paused_reason: Mapped[str] = mapped_column(String(300), default="")
    started_by_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))   # None: the person
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("mail_threads.id", ondelete="SET NULL"), index=True)
    # the guard: mail sent in it, what its turns cost, and how far the person has let it go
    hops: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    max_hops: Mapped[int] = mapped_column(Integer, default=30)
    max_cost_usd: Mapped[float] = mapped_column(Float, default=2.0)
    open_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Mail(Base):
    """One message in a thread. from_id/to_id are agents (a colony's lead, or an agent on its own);
    None is the person. kind: message | question (wants the person's answer, maybe from options) | fyi.

    state, mail to an agent:   waiting (for the mayor) | queued (to go as soon as there's room) | delivered
    state, mail to the person: new | answered | read"""
    __tablename__ = "mail"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("mail_threads.id", ondelete="CASCADE"), index=True)
    from_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    to_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="message")
    body: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(10), index=True)
    # the run that wrote it, and the one it was handed to
    from_run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    # Why we can't vouch for it: the run that wrote it read something untrusted. Its reader inherits that.
    untrusted: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sender: Mapped[Agent | None] = relationship(foreign_keys=[from_id])
    recipient: Mapped[Agent | None] = relationship(foreign_keys=[to_id])


class CaretakerTurn(Base):
    """One message to the caretaker and everything it did about it (app/caretaker.py).

    messages: this turn's part of the conversation exactly as the model API takes it back (the user's
    message, the model's replies with their tool calls, the tool results), so the next turn can resend it.
    proposals: agents and colonies it proposed, each waiting for the person's Add, like an agent's.
    undo: what the turn changed, as it was before (None: it changed nothing), for the Undo button."""
    __tablename__ = "caretaker_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation: Mapped[int] = mapped_column(Integer, default=1)   # "Start over" begins the next one
    provider: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)                          # what the person said
    messages: Mapped[list] = mapped_column(JSON, default=list)
    reply: Mapped[str] = mapped_column(Text, default="")
    actions: Mapped[list] = mapped_column(JSON, default=list)        # for the browser: focus a building, open a screen
    proposals: Mapped[list] = mapped_column(JSON, default=list)
    undo: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))   # SQL NULL, not JSON null, so queries can test it
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    # done | working (its sandbox is still on it: only on a subscription, see app/caretaker.py) | failed
    state: Mapped[str] = mapped_column(String(10), default="done", server_default="done")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    layout: Mapped[dict] = mapped_column(JSON, default=dict)        # the map as the browser drew it, for its tools
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
