import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import google, mcp_auth, mcp_client, mcp_import, town, views, webapi
from ..auth import require_user
from ..config import settings
from ..db import get_db
from ..models import Agent, AgentToolGrant, McpConnection, McpTool, OAuthAccount, User
from ..runs import end_open_runs
from ..schemas import McpImportIn, McpIn, McpPatch
from ..security import encrypt

TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,200}$")

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def own_connection(db: Session, user: User, conn_id: int) -> McpConnection:
    c = db.get(McpConnection, conn_id)
    if c is None or c.owner_id != user.id:
        raise HTTPException(404, "No such connection")
    return c


def view(db: Session, c: McpConnection) -> dict:
    rows = db.execute(select(Agent.id, Agent.name, AgentToolGrant.tool_name)
                      .join(AgentToolGrant, AgentToolGrant.agent_id == Agent.id)
                      .where(AgentToolGrant.connection_id == c.id)).all()
    return views.connection(c, [{"agent_id": i, "agent": n, "tool_name": t} for i, n, t in rows])


def run_check(db: Session, c: McpConnection) -> None:
    """Handshake with the server and store what it says. stdio servers only ever start
    inside an agent's sandbox, so they can't be checked from here."""
    c.last_checked_at = datetime.now(timezone.utc)
    if c.transport == "hosted" and c.app == town.APP:  # Agent Town's own tools: nothing to sign in to
        c.status, c.status_detail = "connected", "Built in: lets an agent propose new agents and colonies"
        google.sync_tools(c)
        db.commit()
        return
    if c.transport == "hosted":                       # Gmail/Calendar/LinkedIn: as good as the sign-in behind it
        acct = db.get(OAuthAccount, c.oauth_account_id)
        ok = acct is not None and acct.status == "connected"
        again = "Connect LinkedIn again" if c.app == "linkedin" else "Connect Google again"
        c.status, c.status_detail = ("connected", f"Signed in as {acct.email}") if ok else ("auth_required", again)
        google.sync_tools(c)
        db.commit()
        return
    if c.transport == "web":                          # a plain API Agent Town calls itself, GET only
        try:
            c.status, c.status_detail = webapi.check(webapi.base_url(c))
        except webapi.WebError as e:
            c.status, c.status_detail = "error", str(e)
        webapi.sync_tools(c)
        db.commit()
        return
    if c.transport == "stdio":
        c.status, c.status_detail = "needs_sandbox", "stdio servers start inside the agent's sandbox"
        db.commit()
        return
    try:
        headers = mcp_auth.request_headers(c)        # refreshes a sign-in that's about to run out
    except mcp_auth.Expired:
        c.status, c.status_detail = "auth_required", "The sign-in expired: sign in again"
        db.commit()
        return
    except mcp_auth.AuthError as e:
        c.status, c.status_detail = "error", f"Couldn't renew the sign-in: {e}"[:2000]
        db.commit()
        return
    r = mcp_client.check(c.url or "", headers, allow_private=settings().allow_private_mcp_hosts)
    c.status, c.status_detail = r.status, r.detail[:2000]
    if r.status == "auth_required":
        offer_sign_in(c, r.www_authenticate)
    if r.status == "connected":
        c.server_name, c.server_version = r.server_name[:200], r.server_version[:80]
        by_name = {t.name: t for t in c.tools}
        seen = set()
        for t in r.tools:
            name = str(t.get("name", ""))[:200]
            if not TOOL_NAME.fullmatch(name) or name in seen:   # a comma or space would break --allowedTools
                continue
            seen.add(name)
            row = by_name.get(name) or McpTool(name=name)
            row.description = str(t.get("description") or "")[:4000]
            row.input_schema = t.get("inputSchema") or {}
            if name not in by_name:
                c.tools.append(row)
        c.tools = [t for t in c.tools if t.name in seen]
        # a tool that disappeared can't stay granted
        for g in db.scalars(select(AgentToolGrant).where(AgentToolGrant.connection_id == c.id)):
            if g.tool_name is not None and g.tool_name not in seen:
                db.delete(g)
    db.commit()


def offer_sign_in(c: McpConnection, www_authenticate: str) -> None:
    """The server wants credentials: if it has a sign-in of its own, remember where, so the person
    gets a "Sign in" button instead of having to find a token."""
    meta = mcp_auth.discover(c.url or "", www_authenticate)
    if meta is None:
        return
    o = mcp_auth.oauth(c)
    # keep the client they gave us, and ours if it's still the same app; the tokens didn't work
    keep = {k: o[k] for k in ("client_id", "client_secret", "registered_for") if k in o}
    if "registered_for" in o and o.get("authorization_endpoint") != meta["authorization_endpoint"]:
        keep = {}
    mcp_auth.set_oauth(c, {**meta, **keep})
    c.status_detail = ("The sign-in stopped working: sign in again" if o.get("access_token")
                       else f"Sign in with {urlparse(meta['authorization_endpoint']).hostname} to connect")


def _validate(transport: str, url: str | None, command: str | None) -> None:
    if transport in ("http", "web") and not url:
        raise HTTPException(422, f"A {transport} connection needs a url")
    if transport == "stdio" and not command:
        raise HTTPException(422, "A stdio connection needs a command")


@router.get("")
def my_connections(user: User = Depends(require_user), db: Session = Depends(get_db)):
    conns = db.scalars(select(McpConnection).where(McpConnection.owner_id == user.id)
                       .order_by(McpConnection.created_at)).all()
    return [view(db, c) for c in conns]


def create(db: Session, user: User, body: McpIn) -> McpConnection:
    _validate(body.transport, body.url, body.command)
    if db.scalar(select(McpConnection).where(McpConnection.owner_id == user.id, McpConnection.name == body.name)):
        raise HTTPException(409, "You already have a connection with that name")
    c = McpConnection(owner_id=user.id, name=body.name, transport=body.transport,
                      url=body.url if body.transport == "http" else None,
                      command=body.command if body.transport == "stdio" else None,
                      auth_header_enc=encrypt(body.auth_header) if body.auth_header else None)
    if body.transport == "web":
        webapi.set_base(c, body.url)
    if body.transport == "http":
        mcp_auth.set_headers(c, body.headers)
        if body.oauth_client_id:
            mcp_auth.set_oauth(c, {"client_id": body.oauth_client_id, "client_secret": body.oauth_client_secret or ""})
    if body.transport == "stdio":
        mcp_auth.set_env(c, body.env)
    db.add(c)
    db.commit()
    run_check(db, c)
    return c


@router.post("")
def add_connection(body: McpIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return view(db, create(db, user, body))


@router.post("/import")
def import_connections(body: McpImportIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Every server in a pasted config, each as its own connection. A name that's taken gets a number."""
    try:
        found = mcp_import.parse(body.text)
    except mcp_import.NotAConfig as e:
        raise HTTPException(422, str(e))
    if len(found) > 50:
        raise HTTPException(422, "That's more than 50 servers; paste them in smaller batches")
    taken = set(db.scalars(select(McpConnection.name).where(McpConnection.owner_id == user.id)))
    added, problems = [], []
    for s in found:
        name, n = s["name"][:60], 2
        while name in taken:
            name, n = f"{s['name'][:56]} {n}", n + 1
        taken.add(name)
        try:
            item = McpIn(name=name, transport=s["transport"], url=s["url"], command=s["command"],
                          headers=s["headers"], env=s["env"])
            added.append({**view(db, create(db, user, item)), "warnings": s["warnings"]})
        except (HTTPException, ValueError) as e:
            problems.append({"name": s["name"], "detail": getattr(e, "detail", None) or str(e)})
    return {"added": added, "problems": problems}


@router.patch("/{conn_id}")
def update_connection(conn_id: int, body: McpPatch, user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = own_connection(db, user, conn_id)
    if body.name is not None:
        c.name = body.name
    if body.url is not None and c.transport == "http":
        c.url = body.url
    if body.url is not None and c.transport == "web":
        _validate("web", body.url, None)
        webapi.set_base(c, body.url)
    if body.command is not None and c.transport == "stdio":
        c.command = body.command
    if body.auth_header is not None:
        c.auth_header_enc = encrypt(body.auth_header) if body.auth_header else None
    if body.headers is not None and c.transport == "http":
        mcp_auth.set_headers(c, body.headers)
        if body.auth_header is None:
            c.auth_header_enc = None                  # "replaces them all", Authorization too
    if body.env is not None and c.transport == "stdio":
        mcp_auth.set_env(c, body.env)
    if body.oauth_client_id is not None and c.transport == "http":
        o = {k: v for k, v in mcp_auth.oauth(c).items()
             if k not in ("client_id", "client_secret", "registered_for", "access_token", "refresh_token", "expires_at")}
        if body.oauth_client_id:
            o.update(client_id=body.oauth_client_id, client_secret=body.oauth_client_secret or "")
        mcp_auth.set_oauth(c, o)
    _validate(c.transport, c.url, c.command)
    db.commit()
    run_check(db, c)
    return view(db, c)


@router.post("/{conn_id}/check")
def check_connection(conn_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = own_connection(db, user, conn_id)
    run_check(db, c)
    return view(db, c)


@router.post("/{conn_id}/sign-out")
def sign_out(conn_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = own_connection(db, user, conn_id)
    mcp_auth.sign_out(c)
    run_check(db, c)
    return view(db, c)


@router.delete("/{conn_id}")
def delete_connection(conn_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = own_connection(db, user, conn_id)
    mcp_auth.sign_out(c)                              # revoke it at the app, if it lets us
    users = db.scalars(select(Agent).join(AgentToolGrant, AgentToolGrant.agent_id == Agent.id)
                       .where(AgentToolGrant.connection_id == c.id).distinct())
    for a in users:
        end_open_runs(db, a, f"{c.name} was removed: your next message starts a fresh chat without it.")
    db.delete(c)
    db.commit()
    return {"ok": True}
