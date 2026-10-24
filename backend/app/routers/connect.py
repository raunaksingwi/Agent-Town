"""Signing in to Google so agents can use Gmail and Calendar (see app/google.py).

  GET    /api/connect/google              is it set up here, and which Google accounts you've connected
  GET    /api/connect/google/start        → Google's consent screen
  GET    /api/connect/google/callback     ← Google sends the person back here with a code
  DELETE /api/connect/google/{id}         disconnect: revoke at Google and delete our copy

The `state` sent to Google is encrypted and expires in 10 minutes, and it's tied to this browser by
a one-time cookie. Without that, someone could send you a link that connects *your* Gmail to *their*
Agent Town account (OAuth's classic login-CSRF).
"""

import json
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import google, mailindex, views
from ..auth import current_user, refuse_cross_site, require_user
from ..config import settings
from ..db import get_db
from ..models import Agent, AgentToolGrant, MailPerson, McpConnection, OAuthAccount, User
from ..runs import end_open_runs
from ..security import _fernet
from ..timeutil import iso

router = APIRouter(prefix="/api/connect/google", tags=["connect"])
NONCE = "agenttown_oauth"
TTL = 600


def account_view(db: Session, a: OAuthAccount) -> dict:
    people = db.scalar(select(func.count()).select_from(MailPerson).where(MailPerson.account_id == a.id, MailPerson.sent > 0))
    return {"id": a.id, "email": a.email, "status": a.status, "apps": google.apps_granted(a.scopes),
            "index": {"on": a.index_on, "synced_at": iso(a.index_synced_at),
                      "people": people, "problem": a.index_detail}}


@router.get("")
def status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(OAuthAccount).where(OAuthAccount.owner_id == user.id, OAuthAccount.provider == "google"))
    return {"configured": google.configured(), "app_url": settings().app_url.rstrip("/"),
            "accounts": [account_view(db, a) for a in rows]}


class AccountPatch(BaseModel):
    index: bool


@router.patch("/{account_id}")
def update_account(account_id: int, body: AccountPatch, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Turn the email index (app/mailindex.py) on or off. Off deletes it at once; on builds it within minutes."""
    acct = db.get(OAuthAccount, account_id)
    if acct is None or acct.owner_id != user.id:
        raise HTTPException(404, "No such account")
    if acct.index_on and not body.index:
        mailindex.forget(db, acct)
    acct.index_on = body.index
    db.commit()
    return account_view(db, acct)


def _back(**params) -> RedirectResponse:
    return RedirectResponse(settings().app_url.rstrip("/") + "/" + ("?" + urlencode(params) if params else ""), status_code=303)


@router.get("/start")
def start(request: Request, apps: str = "gmail", agent: int | None = None, user: User | None = Depends(current_user)):
    """`agent`: connecting from that agent's "Make it your own", so give it access once connected."""
    refuse_cross_site(request)
    if not google.configured():
        raise HTTPException(404, "Google isn't set up on this server")
    if user is None or getattr(request.state, "auth", None) != "session":
        raise HTTPException(401, "Sign in to Agent Town first")
    want = [a for a in apps.split(",") if a in google.SCOPES] or ["gmail"]
    if urlparse(str(request.base_url)).netloc != urlparse(settings().app_url).netloc:
        # Google only sends people back to the registered address; starting anywhere else loses the cookie.
        raise HTTPException(400, f"Open Agent Town at {settings().app_url} to connect Google")
    verifier, challenge = google.pkce()
    nonce = secrets.token_urlsafe(16)
    state = _fernet().encrypt(json.dumps({"u": user.id, "n": nonce, "v": verifier, "a": want, "g": agent}).encode()).decode()
    resp = RedirectResponse(google.authorize_url(state, challenge, want), status_code=303)
    resp.set_cookie(NONCE, nonce, max_age=TTL, httponly=True, samesite="lax", secure=settings().cookie_secure,
                    path="/api/connect/google")
    return resp


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = "", error: str = "",
             user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    try:
        s = json.loads(_fernet().decrypt(state.encode(), ttl=TTL))
    except (InvalidToken, ValueError):
        return _back(connect_error="That sign-in link expired. Try connecting again.")
    if s.get("login"):                              # signing in to Agent Town itself (routers/auth.py)
        from .auth import finish_google_signin  # here, not at the top: auth imports this module

        if request.cookies.get(NONCE) != s["n"]:
            return _back(signin_error="That sign-in didn't start in this browser. Try again.")
        return finish_google_signin(db, request, s, code, error)
    if not user or user.id != s["u"] or request.cookies.get(NONCE) != s["n"]:
        return _back(connect_error="That sign-in didn't start in this browser. Try connecting again.")
    if error or not code:
        return _back(connect_error="Google sign-in was cancelled." if error == "access_denied" else f"Google said: {error or 'no code'}")
    try:
        tok = google.exchange(code, s["v"])
        info = google.userinfo(tok["access_token"])
    except google.GoogleError as e:
        return _back(connect_error=str(e))

    acct = db.scalar(select(OAuthAccount).where(OAuthAccount.owner_id == user.id, OAuthAccount.provider == "google",
                                                OAuthAccount.subject == info["sub"]))
    if acct is None:
        acct = OAuthAccount(owner_id=user.id, provider="google", subject=info["sub"])
        db.add(acct)
    acct.email = info.get("email", "")
    google.store_tokens(acct, tok)
    db.flush()
    granted = google.apps_granted(acct.scopes)
    for app in granted:                             # one connection per app, with its fixed tools
        conn = db.scalar(select(McpConnection).where(McpConnection.oauth_account_id == acct.id, McpConnection.app == app))
        if conn is None:
            name = google.APP_NAMES[app]
            if db.scalar(select(McpConnection).where(McpConnection.owner_id == user.id, McpConnection.name == name)):
                name = f"{name} ({acct.email})"
            conn = McpConnection(owner_id=user.id, name=name[:60], transport="hosted", oauth_account_id=acct.id, app=app)
            db.add(conn)
        google.sync_tools(conn)
        conn.status, conn.status_detail = "connected", f"Signed in as {acct.email}"
        conn.server_name, conn.last_checked_at = "Agent Town (hosted)", datetime.now(timezone.utc)
    a = db.get(Agent, s.get("g")) if s.get("g") else None
    if a is not None and a.owner_id == user.id:
        db.flush()
        grant_signed_in(db, a, list(db.scalars(select(McpConnection).where(McpConnection.oauth_account_id == acct.id))))
    db.commit()
    resp = _back(connected=",".join(granted) or "none")
    resp.delete_cookie(NONCE, path="/api/connect/google")
    return resp


# A market agent's `tools:` names apps the market way; a sign-in's connections name them like this.
MARKET_APP = {"gmail": "gmail", "google-calendar": "calendar", "linkedin": "linkedin"}


def grant_signed_in(db: Session, a: Agent, conns: list[McpConnection]) -> None:
    """Signing in from an agent's house grants it those apps. From a colony's lead, also its members
    whose AGENT.md says they work with them (Ava's sign-in covers Cleo and Finn): one sign-in sets up
    the colony, and a member that never asked for an app doesn't get it."""
    for agent in [a, *a.team]:
        wanted = {MARKET_APP.get(t) for t in _tools(agent)}
        new = [c for c in conns if (agent is a or c.app in wanted) and not any(g.connection_id == c.id for g in agent.grants)]
        agent.grants += [AgentToolGrant(connection_id=c.id, tool_name=None) for c in new]
        if new or agent is a:
            end_open_runs(db, agent, "It can use new apps now: your next message starts a fresh chat with them.")


def _tools(a: Agent) -> list[str]:
    f = views.definition(a)
    meta = views.frontmatter(f.content)[0] if f else {}
    return [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]


@router.delete("/{account_id}")
def disconnect(account_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    acct = db.get(OAuthAccount, account_id)
    if acct is None or acct.owner_id != user.id:
        raise HTTPException(404, "No such account")
    google.revoke(acct)
    db.delete(acct)                                 # its connections (and agents' access) go with it
    db.commit()
    return {"ok": True}
