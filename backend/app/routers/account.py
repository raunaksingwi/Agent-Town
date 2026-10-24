"""Account → API tokens and model credentials. Browser session only (see require_session)."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import codex_login, google, linkedin, model_check, ratelimit, town, views
from ..auth import COOKIE, end_other_sessions, require_session
from ..config import settings
from ..db import get_db
from ..models import ApiToken, ModelCredential, OAuthAccount, Run, User
from ..runs import end
from ..schemas import CredentialIn, CredentialPatch, EmptyColoniesIn, PreferencesIn, Slug, TokenIn, TownIn
from ..security import decrypt, encrypt, hash_password, new_api_token, verify_password

router = APIRouter(prefix="/api/account", tags=["account"])

LABELS = {("anthropic", "api_key"): "Anthropic API key", ("anthropic", "subscription"): "Claude subscription",
          ("openai", "api_key"): "OpenAI API key", ("openai", "subscription"): "ChatGPT subscription"}


# ---- the password and sessions -------------------------------------------------------------

class PasswordIn(BaseModel):
    password: str
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/password")
def change_password(body: PasswordIn, request: Request, user: User = Depends(require_session),
                    db: Session = Depends(get_db)):
    """A new password signs out every other browser: if the old one leaked, so did their sessions."""
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(403, "That password isn't right")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True, "signed_out": end_other_sessions(db, user, request)}


class UsernameIn(BaseModel):
    username: str = Slug


@router.patch("/username")
def rename(body: UsernameIn, user: User = Depends(require_session), db: Session = Depends(get_db)):
    """Your @name. A Google sign-up starts with one made from their first name, so this is how they pick their own."""
    if body.username != user.username and db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, "That name is taken: pick another")
    user.username = body.username
    db.commit()
    return views.user(user)


@router.post("/sessions/sign-out-others")
def sign_out_others(request: Request, user: User = Depends(require_session), db: Session = Depends(get_db)):
    return {"ok": True, "signed_out": end_other_sessions(db, user, request)}


# ---- API tokens ---------------------------------------------------------------------------

@router.get("/tokens")
def list_tokens(user: User = Depends(require_session), db: Session = Depends(get_db)):
    rows = db.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at))
    return [views.api_token(t) for t in rows]


@router.post("/tokens")
def create_token(body: TokenIn, user: User = Depends(require_session), db: Session = Depends(get_db)):
    token, token_hash = new_api_token()
    expires = datetime.now(timezone.utc) + timedelta(days=body.expires_days) if body.expires_days else None
    t = ApiToken(user_id=user.id, name=body.name, token_hash=token_hash, prefix=token[:10], expires_at=expires)
    db.add(t)
    db.commit()
    # The only time the token itself is ever returned.
    return {**views.api_token(t), "token": token}


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: int, user: User = Depends(require_session), db: Session = Depends(get_db)):
    t = db.get(ApiToken, token_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(404, "No such token")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ---- model credentials --------------------------------------------------------------------

def own_credential(db: Session, user: User, cred_id: int) -> ModelCredential:
    c = db.get(ModelCredential, cred_id)
    if c is None or c.owner_id != user.id:
        raise HTTPException(404, "No such credential")
    return c


@router.get("/credentials")
def list_credentials(user: User = Depends(require_session), db: Session = Depends(get_db)):
    rows = db.scalars(select(ModelCredential).where(ModelCredential.owner_id == user.id)
                      .order_by(ModelCredential.created_at))
    return {"allow_subscription_tokens": settings().allow_subscription_tokens,
            "credentials": [views.credential(c) for c in rows]}


@router.post("/credentials")
def add_credential(body: CredentialIn, user: User = Depends(require_session), db: Session = Depends(get_db)):
    if body.kind == "subscription" and not settings().allow_subscription_tokens:
        raise HTTPException(403, "Subscription tokens are off on this server; use an API key "
                                 "(AGENTTOWN_ALLOW_SUBSCRIPTION_TOKENS turns them on).")
    problem = model_check.shape_error(body.provider, body.kind, body.secret)
    if problem:
        raise HTTPException(422, problem)
    return views.credential(_store(db, user, body.provider, body.kind, body.secret.strip(), body.label))


def _store(db: Session, user: User, provider: str, kind: str, secret: str, label: str | None = None) -> ModelCredential:
    first = db.scalar(select(ModelCredential.id).where(ModelCredential.owner_id == user.id)) is None
    c = ModelCredential(owner_id=user.id, provider=provider, kind=kind, label=label or LABELS[(provider, kind)],
                        secret_enc=encrypt(secret), hint=secret[-4:] if kind == "api_key" else "",
                        is_default=first)
    db.add(c)
    db.commit()
    _run_check(db, c, secret)
    return c


# Sign in with ChatGPT: a one-time code instead of pasting ~/.codex/auth.json (codex_login.py).

class ChatGptPollIn(BaseModel):
    handle: str = Field(max_length=4000)


def _subs_on() -> None:
    if not settings().allow_subscription_tokens:
        raise HTTPException(403, "Subscription sign-in is off on this server; use an API key.")


@router.post("/credentials/chatgpt/start")
def chatgpt_start(user: User = Depends(require_session)):
    _subs_on()
    ratelimit.check(f"chatgpt-start:{user.id}", 10, 3600, "ChatGPT sign-ins")
    try:
        return codex_login.start(user.id)
    except codex_login.LoginError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/credentials/chatgpt/poll")
def chatgpt_poll(body: ChatGptPollIn, user: User = Depends(require_session), db: Session = Depends(get_db)):
    """Pending until the user approves the code on OpenAI's page; then the saved credential."""
    _subs_on()
    ratelimit.check(f"chatgpt-poll:{user.id}", 600, 3600, "sign-in checks")
    try:
        auth = codex_login.poll(user.id, body.handle)
    except codex_login.LoginError as e:
        raise HTTPException(400, str(e)) from e
    if auth is None:
        return {"pending": True}
    return {"pending": False, "credential": views.credential(_store(db, user, "openai", "subscription", auth))}


def _run_check(db: Session, c: ModelCredential, secret: str) -> None:
    r = model_check.check(c.provider, c.kind, secret)
    c.status, c.status_detail, c.last_checked_at = r.status, r.detail, datetime.now(timezone.utc)
    db.commit()


@router.post("/credentials/{cred_id}/check")
def check_credential(cred_id: int, user: User = Depends(require_session), db: Session = Depends(get_db)):
    c = own_credential(db, user, cred_id)
    secret = decrypt(c.secret_enc)
    if secret is None:
        c.status, c.status_detail = "error", "Can't decrypt: the server's secret key changed. Add it again."
        db.commit()
    else:
        _run_check(db, c, secret)
    return views.credential(c)


@router.patch("/credentials/{cred_id}")
def update_credential(cred_id: int, body: CredentialPatch, user: User = Depends(require_session),
                      db: Session = Depends(get_db)):
    c = own_credential(db, user, cred_id)
    if body.label is not None:
        c.label = body.label
    if body.is_default:
        db.execute(update(ModelCredential).where(ModelCredential.owner_id == user.id).values(is_default=False))
        c.is_default = True
    db.commit()
    return views.credential(c)


@router.delete("/credentials/{cred_id}")
def delete_credential(cred_id: int, user: User = Depends(require_session), db: Session = Depends(get_db)):
    c = own_credential(db, user, cred_id)
    was_default = c.is_default
    db.delete(c)
    db.commit()
    if was_default:  # hand the default to the oldest remaining one
        nxt = db.scalar(select(ModelCredential).where(ModelCredential.owner_id == user.id)
                        .order_by(ModelCredential.created_at))
        if nxt:
            nxt.is_default = True
            db.commit()
    return {"ok": True}


# ---- your map ------------------------------------------------------------------------------

@router.put("/town")
def set_town(body: TownIn, user: User = Depends(require_session), db: Session = Depends(get_db)):
    """Where you moved buildings on your map. The whole set each time; an empty set puts every
    building back on its road. Keys for things you no longer have are harmless and dropped."""
    user.town = {k: [round(x, 2), round(y, 2)] for k, (x, y) in body.positions.items()}
    db.commit()
    return {"town": user.town}


@router.put("/empty-colonies")
def set_empty_colonies(body: EmptyColoniesIn, user: User = Depends(require_session), db: Session = Depends(get_db)):
    """Colonies they named before putting agents in (the Colonies screen). Blank names and repeats are dropped."""
    seen, out = set(), []
    for c in body.colonies:
        name = " ".join(c.name.split())
        if name and name.lower() not in seen:
            if (lead := town.colony_taken_by(db, user, name)) is not None:
                raise HTTPException(422, f"{lead.name[0].upper()}{lead.name[1:]} already leads a colony called {lead.colony_name}")
            seen.add(name.lower())
            out.append({"name": name, "about": " ".join(c.about.split())})
    user.empty_colonies = out
    db.commit()
    return {"empty_colonies": user.empty_colonies}


@router.patch("/preferences")
def set_preferences(body: PreferencesIn, user: User = Depends(require_session), db: Session = Depends(get_db)):
    """How the map looks, kept with the account so it's the same on every device (and the caretaker can change it)."""
    if body.map_style is not None:
        user.map_style = body.map_style
    db.commit()
    return {"map_style": user.map_style}


# ---- deleting your account ----------------------------------------------------------------

class DeleteAccountIn(BaseModel):
    password: str = ""
    username: str = ""          # an account made with Google has no password: they type their @name instead


@router.delete("")
def delete_account(body: DeleteAccountIn, response: Response, user: User = Depends(require_session),
                   db: Session = Depends(get_db)):
    """Delete the account and everything in it: agents, files, chats, keys, connections, shares.
    Browser session only, and the password again (or, with no password, their @name), so a stolen API
    token can't do it and a stray click can't either."""
    if user.password_hash and not verify_password(user.password_hash, body.password):
        raise HTTPException(403, "That password isn't right")
    if not user.password_hash and body.username.strip().lstrip("@") != user.username:
        raise HTTPException(403, f"Type @{user.username} to confirm")
    for r in db.scalars(select(Run).where(Run.owner_id == user.id, Run.ended_at.is_(None))):
        end(db, r, "stopped", "The account was deleted")
    for acct in db.scalars(select(OAuthAccount).where(OAuthAccount.owner_id == user.id)):
        (linkedin if acct.provider == "linkedin" else google).revoke(acct)   # tell them too, not just forget the token
    db.delete(user)                                     # every table cascades from the user
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
