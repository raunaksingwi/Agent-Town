"""Signing in to LinkedIn so agents can post as you (see app/linkedin.py). Same shape as Google's
(routers/connect.py), including the one-time cookie that ties the sign-in to this browser.

  GET    /api/connect/linkedin              is it set up here, and which LinkedIn accounts you've connected
  GET    /api/connect/linkedin/start        → LinkedIn's consent screen
  GET    /api/connect/linkedin/callback     ← LinkedIn sends the person back here with a code
  DELETE /api/connect/linkedin/{id}         disconnect: revoke at LinkedIn and delete our copy
"""

import json
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import google, linkedin
from ..auth import current_user, refuse_cross_site, require_user
from ..config import settings
from ..db import get_db
from ..models import Agent, McpConnection, OAuthAccount, User
from ..security import _fernet
from ..timeutil import iso
from .connect import TTL, _back, grant_signed_in

router = APIRouter(prefix="/api/connect/linkedin", tags=["connect"])
NONCE = "agenttown_linkedin"
PATH = "/api/connect/linkedin"


def account_view(a: OAuthAccount) -> dict:
    return {"id": a.id, "email": a.email, "status": a.status,
            "expires_at": iso(a.expires_at)}


@router.get("")
def status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(OAuthAccount).where(OAuthAccount.owner_id == user.id, OAuthAccount.provider == "linkedin"))
    return {"configured": linkedin.configured(), "app_url": settings().app_url.rstrip("/"),
            "accounts": [account_view(a) for a in rows]}


@router.get("/start")
def start(request: Request, agent: int | None = None, user: User | None = Depends(current_user)):
    """`agent`: connecting from that agent's "Make it your own", so give it access once connected."""
    refuse_cross_site(request)
    if not linkedin.configured():
        raise HTTPException(404, "LinkedIn isn't set up on this server")
    if user is None or getattr(request.state, "auth", None) != "session":
        raise HTTPException(401, "Sign in to Agent Town first")
    if urlparse(str(request.base_url)).netloc != urlparse(settings().app_url).netloc:
        raise HTTPException(400, f"Open Agent Town at {settings().app_url} to connect LinkedIn")
    nonce = secrets.token_urlsafe(16)
    state = _fernet().encrypt(json.dumps({"u": user.id, "n": nonce, "g": agent}).encode()).decode()
    resp = RedirectResponse(linkedin.authorize_url(state), status_code=303)
    resp.set_cookie(NONCE, nonce, max_age=TTL, httponly=True, samesite="lax", secure=settings().cookie_secure, path=PATH)
    return resp


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = "", error: str = "", error_description: str = "",
             user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    try:
        s = json.loads(_fernet().decrypt(state.encode(), ttl=TTL))
    except (InvalidToken, ValueError):
        return _back(connect_error="That sign-in link expired. Try connecting again.")
    if not user or user.id != s["u"] or request.cookies.get(NONCE) != s["n"]:
        return _back(connect_error="That sign-in didn't start in this browser. Try connecting again.")
    if error or not code:
        cancelled = error in ("user_cancelled_login", "user_cancelled_authorize")
        return _back(connect_error="LinkedIn sign-in was cancelled." if cancelled else f"LinkedIn said: {error_description or error or 'no code'}")
    try:
        tok = linkedin.exchange(code)
        info = linkedin.userinfo(tok["access_token"])
    except linkedin.LinkedInError as e:
        return _back(connect_error=str(e))

    acct = db.scalar(select(OAuthAccount).where(OAuthAccount.owner_id == user.id, OAuthAccount.provider == "linkedin",
                                                OAuthAccount.subject == info["sub"]))
    if acct is None:
        acct = OAuthAccount(owner_id=user.id, provider="linkedin", subject=info["sub"], index_on=False)
        db.add(acct)
    acct.email = info.get("email") or info.get("name") or ""
    linkedin.store_tokens(acct, tok)
    db.flush()
    conn = db.scalar(select(McpConnection).where(McpConnection.oauth_account_id == acct.id))
    if conn is None:
        name = "LinkedIn"
        if db.scalar(select(McpConnection).where(McpConnection.owner_id == user.id, McpConnection.name == name)):
            name = f"LinkedIn ({acct.email})"
        conn = McpConnection(owner_id=user.id, name=name[:60], transport="hosted", oauth_account_id=acct.id, app="linkedin")
        db.add(conn)
    google.sync_tools(conn)
    conn.status, conn.status_detail = "connected", f"Signed in as {info.get('name') or acct.email}"
    conn.server_name, conn.last_checked_at = "Agent Town (hosted)", datetime.now(timezone.utc)
    a = db.get(Agent, s.get("g")) if s.get("g") else None
    if a is not None and a.owner_id == user.id:
        db.flush()
        grant_signed_in(db, a, [conn])
    db.commit()
    resp = _back(connected="linkedin")
    resp.delete_cookie(NONCE, path=PATH)
    return resp


@router.delete("/{account_id}")
def disconnect(account_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    acct = db.get(OAuthAccount, account_id)
    if acct is None or acct.owner_id != user.id or acct.provider != "linkedin":
        raise HTTPException(404, "No such account")
    linkedin.revoke(acct)
    db.delete(acct)                                 # its connection (and agents' access) go with it
    db.commit()
    return {"ok": True}
