"""Signing in to an app's MCP server, the way Claude and Codex connectors do (see app/mcp_auth.py).

  GET /api/connect/mcp/{id}/start     → the app's sign-in page (registering Agent Town first if needed)
  GET /api/connect/mcp/callback       ← the app sends the person back here with a code

Same guard rails as Google sign-in (routers/connect.py): the `state` is encrypted, expires in 10
minutes and is tied to this browser by a one-time cookie, so nobody can link their app to your town.
"""

import json
import secrets
from urllib.parse import urlparse

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import google, mcp_auth
from ..auth import current_user, refuse_cross_site
from ..config import settings
from ..db import get_db
from ..models import Agent, AgentToolGrant, McpConnection, User
from ..runs import end_open_runs
from ..security import _fernet
from .connect import _back
from .mcp import run_check

router = APIRouter(prefix="/api/connect/mcp", tags=["connect"])
NONCE = "agenttown_mcp_oauth"
TTL = 600


@router.get("/{conn_id}/start")
def start(conn_id: int, request: Request, agent: int | None = None,
          user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    """`agent`: connecting for that agent, so give it access once signed in."""
    refuse_cross_site(request)
    if user is None or getattr(request.state, "auth", None) != "session":
        raise HTTPException(401, "Sign in to Agent Town first")
    c = db.get(McpConnection, conn_id)
    if c is None or c.owner_id != user.id or c.transport != "http":
        raise HTTPException(404, "No such connection")
    if urlparse(str(request.base_url)).netloc != urlparse(settings().app_url).netloc:
        raise HTTPException(400, f"Open Agent Town at {settings().app_url} to sign in")
    o = mcp_auth.oauth(c)
    if not o.get("authorization_endpoint"):
        run_check(db, c)                              # maybe it only just started asking
        o = mcp_auth.oauth(c)
        if not o.get("authorization_endpoint"):
            return _back(connect_error=f"{c.name} doesn't offer a sign-in. Add a token or header instead.")
    try:
        o = mcp_auth.register(o)
    except mcp_auth.AuthError as e:
        return _back(connect_error=f"{c.name}: {e}")
    mcp_auth.set_oauth(c, o)
    db.commit()
    verifier, challenge = google.pkce()
    nonce = secrets.token_urlsafe(16)
    state = _fernet().encrypt(json.dumps({"u": user.id, "c": c.id, "n": nonce, "v": verifier, "g": agent}).encode()).decode()
    resp = RedirectResponse(mcp_auth.authorize_url(o, state, challenge), status_code=303)
    resp.set_cookie(NONCE, nonce, max_age=TTL, httponly=True, samesite="lax", secure=settings().cookie_secure,
                    path="/api/connect/mcp")
    return resp


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = "", error: str = "", error_description: str = "",
             user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    try:
        s = json.loads(_fernet().decrypt(state.encode(), ttl=TTL))
    except (InvalidToken, ValueError):
        return _back(connect_error="That sign-in link expired. Try again.")
    if not user or user.id != s["u"] or request.cookies.get(NONCE) != s["n"]:
        return _back(connect_error="That sign-in didn't start in this browser. Try again.")
    c = db.get(McpConnection, s["c"])
    if c is None or c.owner_id != user.id:
        return _back(connect_error="That app was removed while you were signing in.")
    if error or not code:
        return _back(connect_error="Sign-in was cancelled." if error == "access_denied"
                     else f"{c.name} said: {error_description or error or 'no code'}")
    try:
        mcp_auth.exchange(c, code, s["v"])
    except mcp_auth.AuthError as e:
        return _back(connect_error=f"{c.name}: {e}")
    db.commit()
    run_check(db, c)
    a = db.get(Agent, s.get("g")) if s.get("g") else None
    if a is not None and a.owner_id == user.id and not any(g.connection_id == c.id for g in a.grants):
        a.grants.append(AgentToolGrant(connection_id=c.id, tool_name=None))
        end_open_runs(db, a, "It can use new apps now: your next message starts a fresh chat with them.")
        db.commit()
    resp = _back(connected=c.name) if c.status == "connected" else _back(connect_error=f"{c.name}: {c.status_detail}")
    resp.delete_cookie(NONCE, path="/api/connect/mcp")
    return resp
