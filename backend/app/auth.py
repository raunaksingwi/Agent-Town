"""Who is making this request?

Two ways in, both resolved to a user on the server; no endpoint ever takes a user id from the
client:
  - browsers: the session cookie set at login
  - programs: "Authorization: Bearer at_…", an API token made in Account → API tokens
Either way only a sha256 of the secret is stored, so a leaked database can't be replayed.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import ApiToken, AuthSession, User
from .security import API_TOKEN_PREFIX, hash_token, new_session_token
from .timeutil import utc

COOKIE = "agenttown_session"
LAST_USED_EVERY = timedelta(seconds=15)


def start_session(db: Session, user: User, response: Response) -> None:
    token, token_hash = new_session_token()
    expires = datetime.now(timezone.utc) + timedelta(days=settings().session_days)
    db.add(AuthSession(user_id=user.id, token_hash=token_hash, expires_at=expires))
    db.commit()
    response.set_cookie(
        COOKIE, token, max_age=settings().session_days * 86400, httponly=True,
        samesite="lax", secure=settings().cookie_secure, path="/")


def prune_sessions(db: Session) -> None:
    """Expired sessions are useless rows; sweep them now and then (each login does)."""
    db.query(AuthSession).filter(AuthSession.expires_at < datetime.now(timezone.utc)).delete()
    db.commit()


def end_other_sessions(db: Session, user: User, request: Request) -> int:
    """Sign out every browser but this one (after a password change, or on request)."""
    keep = hash_token(request.cookies.get(COOKIE, ""))
    n = db.query(AuthSession).filter(AuthSession.user_id == user.id, AuthSession.token_hash != keep).delete()
    db.commit()
    return n


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        found = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        if found:
            db.delete(found)
            db.commit()
    response.delete_cookie(COOKIE, path="/")


def _from_bearer(db: Session, header: str) -> User:
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.startswith(API_TOKEN_PREFIX):
        raise HTTPException(401, "Use: Authorization: Bearer at_…", headers={"WWW-Authenticate": "Bearer"})
    t = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(token.strip())))
    now = datetime.now(timezone.utc)
    if t is None or (t.expires_at and utc(t.expires_at) < now):
        # A bad token is an error, not "signed out": a script should fail loudly.
        raise HTTPException(401, "Invalid or expired API token", headers={"WWW-Authenticate": "Bearer"})
    if t.last_used_at is None or now - utc(t.last_used_at) > LAST_USED_EVERY:   # not a write per request
        t.last_used_at = now
        db.commit()
    return t.user


def _from_cookie(db: Session, request: Request) -> User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if s is None:
        return None
    if utc(s.expires_at) < datetime.now(timezone.utc):
        db.delete(s)
        db.commit()
        return None
    return s.user


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    header = request.headers.get("authorization")
    if header:
        request.state.auth = "token"
        return _from_bearer(db, header)
    request.state.auth = "session"
    return _from_cookie(db, request)


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "Sign in first")
    return user


def refuse_cross_site(request: Request) -> None:
    """For GET routes that do something (start a sign-in): a link on another site must not be able
    to kick one off with the person's cookie. Browsers label such navigations in Sec-Fetch-Site."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(403, "Open this from Agent Town itself")


def require_session(request: Request, user: User = Depends(require_user)) -> User:
    """For managing credentials themselves: a stolen API token must not be able to mint more
    tokens or read which keys exist. Only a signed-in browser can."""
    if getattr(request.state, "auth", None) != "session":
        raise HTTPException(403, "Sign in with a browser session to manage tokens and keys")
    return user
