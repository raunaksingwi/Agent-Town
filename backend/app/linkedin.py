"""LinkedIn for agents: who you are, and posting as you. Hosted by Agent Town, like Gmail (app/google.py).

  sign in   /api/connect/linkedin/start → LinkedIn's consent screen → /callback (routers/connect_linkedin.py).
            OAuth 2.0 authorization code flow with our client secret (LinkedIn only offers PKCE to native apps).
  tokens    an access token lasts 60 days and LinkedIn gives apps like this no refresh token, so when it
            runs out the account is marked expired and the person signs in again.
  tools     served by routers/hosted.py with the run token; the LinkedIn token never enters a sandbox.

Why so little: LinkedIn has no official MCP server, and the self-serve API products only give an app the
person's name, email and photo, and posting as them. Reading the feed, connections or messages needs
partner approval. Scrapers that drive a logged-in browser exist, but they break LinkedIn's terms and get
accounts restricted, so we don't use them.

A post goes out at once unless the person's rules for that agent say to ask first (app/outbox.py).
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import OAuthAccount
from .security import decrypt, encrypt

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
REVOKE_URL = "https://www.linkedin.com/oauth/v2/revoke"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
POSTS_URL = "https://api.linkedin.com/rest/posts"
SCOPES = ["openid", "profile", "email", "w_member_social"]
MAX_POST = 3000                    # LinkedIn's limit on a post's text


class LinkedInError(Exception):
    pass


class Expired(LinkedInError):
    """The 60 days are up (or they revoked it): sign in again."""


def http() -> httpx.Client:
    return httpx.Client(timeout=20)


def configured() -> bool:
    return bool(settings().linkedin_client_id and settings().linkedin_client_secret)


def redirect_uri() -> str:
    return settings().app_url.rstrip("/") + "/api/connect/linkedin/callback"


def authorize_url(state: str) -> str:
    return AUTH_URL + "?" + urlencode({"response_type": "code", "client_id": settings().linkedin_client_id,
                                       "redirect_uri": redirect_uri(), "state": state, "scope": " ".join(SCOPES)})


def _form(url: str, data: dict) -> httpx.Response:
    with http() as c:
        return c.post(url, data={"client_id": settings().linkedin_client_id,
                                 "client_secret": settings().linkedin_client_secret, **data})


def exchange(code: str) -> dict:
    r = _form(TOKEN_URL, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400 or "access_token" not in body:
        raise LinkedInError(f"LinkedIn said {r.status_code}: {body.get('error_description') or body.get('error') or r.text[:200]}")
    return body


def userinfo(access_token: str) -> dict:
    """OpenID Connect: sub, name, email, picture."""
    with http() as c:
        r = c.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code >= 400:
        raise LinkedInError(f"Couldn't read the LinkedIn account ({r.status_code})")
    return r.json()


def store_tokens(acct: OAuthAccount, tok: dict) -> None:
    acct.access_token_enc = encrypt(tok["access_token"])
    acct.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 60 * 86400)))
    acct.scopes = tok.get("scope", "").replace(",", " ")
    acct.status = "connected"


def access_token(db: Session, acct: OAuthAccount) -> str:
    exp = acct.expires_at.replace(tzinfo=timezone.utc) if acct.expires_at and not acct.expires_at.tzinfo else acct.expires_at
    token = decrypt(acct.access_token_enc) if acct.access_token_enc else None
    if not token or not exp or exp <= datetime.now(timezone.utc):
        acct.status = "expired"
        db.commit()
        raise Expired("The LinkedIn sign-in has run out (they last 60 days)")
    return token


def revoke(acct: OAuthAccount) -> None:
    token = decrypt(acct.access_token_enc) if acct.access_token_enc else None
    if token:
        try:
            _form(REVOKE_URL, {"token": token})
        except httpx.HTTPError:
            pass                          # we delete our copy either way


# ---- the tools ------------------------------------------------------------------------------

TOOLS = {
    "linkedin": [
        {"name": "get_profile", "description": "The person's LinkedIn name, email and photo. LinkedIn doesn't let apps "
                                               "read their headline, feed, connections or messages.",
         "inputSchema": {"type": "object", "properties": {}, "required": []}},
        {"name": "create_post", "description": "Post on the person's LinkedIn, as them. Plain text, up to 3,000 characters "
                                               "(no markdown: LinkedIn shows it as typed). Agent Town posts it at once, or, if "
                                               "the person's rules for you say so, asks them first. The result says which: "
                                               "don't also ask them in words.",
         "inputSchema": {"type": "object", "properties": {
             "text": {"type": "string", "maxLength": MAX_POST},
             "visibility": {"type": "string", "enum": ["PUBLIC", "CONNECTIONS"], "description": "default PUBLIC"}},
             "required": ["text"]}},
    ],
}


def call(db: Session, acct: OAuthAccount, name: str, args: dict) -> dict:
    if name == "get_profile":
        info = userinfo(access_token(db, acct))
        return {k: info.get(k) for k in ("name", "email", "picture")}
    if name == "create_post":                # checked and published by app/outbox.py
        text = str(args.get("text") or "").strip()
        if not text:
            raise ValueError("The post has no text")
        if len(text) > MAX_POST:
            raise ValueError(f"LinkedIn posts are at most {MAX_POST} characters; this one is {len(text)}")
        return {"text": text, "visibility": "CONNECTIONS" if args.get("visibility") == "CONNECTIONS" else "PUBLIC"}
    raise LinkedInError(f"No tool {name!r} for LinkedIn")


# A post's text is LinkedIn's "little text" format, where these characters are markup: unescaped, a "(" can
# cut the post short. Hashtags are markup too, written {hashtag|\#|word}.
_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
_HASHTAG = re.compile(r"(?<![\w&])#(\w+)")


def little_text(text: str) -> str:
    parts = _HASHTAG.split(text)            # plain, tag, plain, tag, …
    return "".join(_RESERVED.sub(r"\\\1", p) if i % 2 == 0 else "{hashtag|\\#|" + p + "}" for i, p in enumerate(parts))


def publish(db: Session, acct: OAuthAccount, text: str, visibility: str = "PUBLIC") -> str:
    """Post it now; returns its address. Only ever called by app/outbox.py."""
    token = access_token(db, acct)
    body = {"author": f"urn:li:person:{acct.subject}", "commentary": little_text(text),
            "visibility": visibility, "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}}
    with http() as c:
        r = c.post(POSTS_URL, json=body, headers={"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0",
                                                  "LinkedIn-Version": settings().linkedin_api_version})
    if r.status_code == 401:
        acct.status = "expired"
        db.commit()
        raise Expired("LinkedIn no longer accepts this sign-in")
    if r.status_code >= 400:
        detail = r.json().get("message", "") if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        raise LinkedInError(f"LinkedIn said {r.status_code}: {detail}")
    urn = r.headers.get("x-restli-id", "")
    return f"https://www.linkedin.com/feed/update/{quote(urn)}/" if urn else "https://www.linkedin.com/feed/"


def tool_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=1)
