"""Accounts: signing up and in, with Google (when the server has a Google client) or a password.

Google sign-in shares Gmail's callback (/api/connect/google/callback, so the Google client needs no
second redirect URI): the encrypted `state` says which it is, and that route hands sign-ins to
finish_google_signin here. Same protections as connecting Gmail: PKCE, a 10-minute state, and a
one-time cookie tying it to this browser, so nobody can sign you in to *their* account (login CSRF).
"""

import json
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import google, ratelimit, views
from ..auth import current_user, end_session, prune_sessions, refuse_cross_site, start_session
from ..config import settings
from ..db import get_db
from ..models import ApiToken, AuthSession, User
from ..schemas import LoginIn, SignupIn, StarterIn
from ..security import _fernet, hash_password, verify_password
from .connect import NONCE, TTL, _back
from .files import assistant_name_problem, install_starter

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Verifying against a real hash when the user doesn't exist keeps "no such user" and
# "wrong password" equally slow, so response time doesn't reveal which emails have accounts.
_DUMMY_HASH = hash_password("not-a-real-password")
NOT_INVITED = "Agent Town is invite-only here for now: ask whoever runs it to add {email}."


@router.get("/options")
def options():
    """How people sign in here: with Google when this server has a Google client, and whether a
    new account can be made with a password."""
    return {"google": google.configured(), "password_signup": settings().password_signup}


@router.get("/google")
def google_start(request: Request, assistant: str = ""):
    """→ Google's account picker. `assistant`: what a new account calls its assistant (the sign-up form)."""
    refuse_cross_site(request)
    if not google.configured():
        raise HTTPException(404, "Google sign-in isn't set up on this server")
    if urlparse(str(request.base_url)).netloc != urlparse(settings().app_url).netloc:
        raise HTTPException(400, f"Open Agent Town at {settings().app_url} to sign in with Google")
    try:
        name = StarterIn(assistant_name=assistant or None).assistant_name
    except ValidationError:     # a page visit, not a fetch: back to the sign-in, which shows why
        return _back(signin_error="Your assistant's name: letters, spaces, ' and -, up to 30 characters.")
    verifier, challenge = google.pkce()
    nonce = secrets.token_urlsafe(16)
    state = _fernet().encrypt(json.dumps({"login": True, "n": nonce, "v": verifier, "an": name}).encode()).decode()
    resp = RedirectResponse(google.signin_url(state, challenge), status_code=303)
    resp.set_cookie(NONCE, nonce, max_age=TTL, httponly=True, samesite="lax", secure=settings().cookie_secure,
                    path="/api/connect/google")
    return resp


def finish_google_signin(db: Session, request: Request, s: dict, code: str, error: str) -> RedirectResponse:
    if error or not code:
        return _back(signin_error="Google sign-in was cancelled." if error == "access_denied" else f"Google said: {error or 'no code'}")
    try:
        info = google.userinfo(google.exchange(code, s["v"])["access_token"])
    except google.GoogleError as e:
        return _back(signin_error=str(e))
    if not info.get("email") or not info.get("email_verified"):
        return _back(signin_error="Google hasn't confirmed that account's email address, so it can't sign in here.")
    u = db.scalar(select(User).where(User.google_sub == info["sub"]))
    new = False
    if u is None:
        email = info["email"].lower()
        u = db.scalar(select(User).where(User.email == email))
        if u is not None and u.google_sub:
            return _back(signin_error=f"{email} already signs in with a different Google account.")
        if u is not None:
            if u.email_verified_at is None:
                claim_unverified(db, u)
            u.google_sub = info["sub"]          # their account from before: Google vouches the email is theirs
        else:
            if not settings().email_allowed(email):
                return _back(signin_error=NOT_INVITED.format(email=email))
            if not ratelimit.hit(f"signup:{ratelimit.client_ip(request)}", 10, 3600):
                return _back(signin_error="Too many new accounts from this address; wait a few minutes and try again.")
            u = User(email=email, username=free_username(db, info), password_hash="", google_sub=info["sub"],
                     email_verified_at=datetime.now(timezone.utc))
            db.add(u)
            db.flush()
            name = s.get("an")
            install_starter(db, u, None if assistant_name_problem(db, None, name) else name)
            new = True
    db.commit()
    prune_sessions(db)
    resp = _back(signed_up="1") if new else _back()
    start_session(db, u, resp)
    resp.delete_cookie(NONCE, path="/api/connect/google")
    return resp


def claim_unverified(db: Session, u: User) -> None:
    """Google proves this person owns the email; whoever typed it into the sign-up form never did.
    It may have been someone else, keeping the password so they could get back in once the real
    owner moved in ("account pre-hijacking"). So every way in that came before goes: the password,
    signed-in browsers, API tokens. If it was them all along, they sign in with Google from now on."""
    u.password_hash = ""
    db.query(AuthSession).filter(AuthSession.user_id == u.id).delete()
    db.query(ApiToken).filter(ApiToken.user_id == u.id).delete()
    u.email_verified_at = datetime.now(timezone.utc)


def free_username(db: Session, info: dict) -> str:
    """A first name as a username (Sam Lee → sam, then sam-2…): they can change it under Account."""
    def slug(text: str) -> str:
        ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9_-]+", "-", ascii_).strip("-_")[:24]
    base = next((b for b in (slug(info.get("given_name") or ""), slug(info.get("name") or ""),
                             slug(info["email"].split("@")[0])) if len(b) >= 3), "resident")
    name, n = base, 1
    while db.scalar(select(User.id).where(User.username == name)):
        n += 1
        name = f"{base}-{n}"
    return name


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if not settings().password_signup:
        raise HTTPException(403, "New accounts here are made with Google")
    ratelimit.check(f"signup:{ratelimit.client_ip(request)}", 10, 3600, "new accounts from this address")
    email = body.email.lower()
    if not settings().email_allowed(email):
        raise HTTPException(403, NOT_INVITED.format(email=email))
    taken = db.scalar(select(User).where(or_(func.lower(User.email) == email, User.username == body.username)))
    if taken:
        raise HTTPException(409, "That email or username is taken")
    if body.starter and (problem := assistant_name_problem(db, None, body.assistant_name)):
        raise HTTPException(422, problem)
    u = User(email=email, username=body.username, password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    if body.starter:
        install_starter(db, u, body.assistant_name)
    db.commit()
    start_session(db, u, response)
    return views.user(u)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = body.login.strip().lower()
    # Guessing is slowed per address and per account, so a flood from one place or at one
    # account both stop; a right password clears the account's count.
    ratelimit.check(f"login-ip:{ratelimit.client_ip(request)}", 30, 900, "sign-in attempts from this address")
    ratelimit.check(f"login:{key}", 10, 900, "sign-in attempts for this account")
    u = db.scalar(select(User).where(or_(User.email == key, User.username == key)))   # emails are stored lowercase
    if not verify_password(u.password_hash if u else _DUMMY_HASH, body.password) or u is None:
        raise HTTPException(401, "Wrong email/username or password")
    ratelimit.forget(f"login:{key}")
    prune_sessions(db)
    start_session(db, u, response)
    return views.user(u)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request, response)
    return {"ok": True}


@router.get("/me")
def me(u: User | None = Depends(current_user)):
    return views.user(u) if u else None
