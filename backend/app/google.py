"""Gmail and Google Calendar for agents: a small version of what Composio does, for one provider.

  sign in   /api/connect/google/start → Google's consent screen → /callback (routers/connect.py).
            OAuth 2.0 authorization code flow with PKCE; we keep the refresh token, encrypted.
  refresh   an access token lasts about an hour; we get a new one with the refresh token when needed.
            If Google says no (access revoked, or a Testing-mode token past its 7 days), the account
            is marked expired and the person signs in again.
  tools     Agent Town serves them itself (routers/hosted.py): the sandbox asks with its run token,
            this module calls Google with the person's token. The token never enters a sandbox.

Deliberately limited: agents can read mail and write drafts. An email they send goes out only when the
person presses Send, or when the rules the person set for that agent allow it (app/outbox.py). They read
and add calendar events without inviting anyone.
"""

import base64
import hashlib
import html
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import OAuthAccount
from .security import decrypt, encrypt

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary"

SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"],
    "calendar": ["https://www.googleapis.com/auth/calendar.events"],
}
APP_NAMES = {"gmail": "Gmail", "calendar": "Google Calendar"}
MAX_TEXT = 20_000


class GoogleError(Exception):
    status = 0                    # Google's HTTP status, when it answered with an error


class Expired(GoogleError):
    """Google won't refresh this account's token any more: sign in again."""


def http() -> httpx.Client:
    return httpx.Client(timeout=20)


def configured() -> bool:
    return bool(settings().google_client_id and settings().google_client_secret)


def redirect_uri() -> str:
    return settings().app_url.rstrip("/") + "/api/connect/google/callback"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce() -> tuple[str, str]:
    """(verifier, challenge): we send the challenge now and prove we hold the verifier later, so a
    stolen authorization code is useless on its own."""
    verifier = secrets.token_urlsafe(48)
    return verifier, b64url(hashlib.sha256(verifier.encode()).digest())


def authorize_url(state: str, challenge: str, apps: list[str]) -> str:
    scopes = ["openid", "email"] + [s for a in apps for s in SCOPES[a]]
    return AUTH_URL + "?" + urlencode({
        "client_id": settings().google_client_id, "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": " ".join(scopes), "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline",           # we want a refresh token…
        "prompt": "consent",                # …every time, even if they connected before
        "include_granted_scopes": "true",   # connecting Calendar later keeps Gmail
    })


def signin_url(state: str, challenge: str) -> str:
    """Signing in to Agent Town itself: who they are and nothing else. No refresh token is asked for,
    since nothing is kept; Gmail and Calendar are a separate consent (authorize_url)."""
    return AUTH_URL + "?" + urlencode({
        "client_id": settings().google_client_id, "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": "openid email profile", "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "prompt": "select_account",         # someone with two Google accounts picks which one
    })


def _token_request(data: dict) -> dict:
    with http() as c:
        r = c.post(TOKEN_URL, data={"client_id": settings().google_client_id,
                                    "client_secret": settings().google_client_secret, **data})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        if body.get("error") == "invalid_grant":
            raise Expired(body.get("error_description") or "Google won't refresh this sign-in any more")
        raise GoogleError(f"Google said {r.status_code}: {body.get('error_description') or body.get('error') or r.text[:200]}")
    return body


def exchange(code: str, verifier: str) -> dict:
    return _token_request({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                           "redirect_uri": redirect_uri()})


def userinfo(access_token: str) -> dict:
    with http() as c:
        r = c.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code >= 400:
        raise GoogleError(f"Couldn't read the Google account ({r.status_code})")
    return r.json()


def store_tokens(acct: OAuthAccount, tok: dict) -> None:
    acct.access_token_enc = encrypt(tok["access_token"])
    acct.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))
    if tok.get("refresh_token"):        # Google only sends one on consent; keep the old one otherwise
        acct.refresh_token_enc = encrypt(tok["refresh_token"])
    if tok.get("scope"):
        acct.scopes = tok["scope"]
    acct.status = "connected"


def access_token(db: Session, acct: OAuthAccount) -> str:
    """A working access token for this account, refreshing it when it's about to run out."""
    exp = acct.expires_at.replace(tzinfo=timezone.utc) if acct.expires_at and not acct.expires_at.tzinfo else acct.expires_at
    if acct.access_token_enc and exp and exp - datetime.now(timezone.utc) > timedelta(seconds=60):
        token = decrypt(acct.access_token_enc)
        if token:
            return token
    refresh = decrypt(acct.refresh_token_enc) if acct.refresh_token_enc else None
    if not refresh:
        acct.status = "expired"
        db.commit()
        raise Expired("No refresh token stored: sign in again")
    try:
        store_tokens(acct, _token_request({"grant_type": "refresh_token", "refresh_token": refresh}))
    except Expired:
        acct.status = "expired"
        db.commit()
        raise
    db.commit()
    return decrypt(acct.access_token_enc) or ""


def revoke(acct: OAuthAccount) -> None:
    token = decrypt(acct.refresh_token_enc) if acct.refresh_token_enc else None
    if token:
        try:
            with http() as c:
                c.post(REVOKE_URL, data={"token": token})
        except httpx.HTTPError:
            pass                          # we delete our copy either way


def apps_granted(scopes: str) -> list[str]:
    have = set(scopes.split())
    return [a for a, need in SCOPES.items() if all(s in have for s in need)]


# ---- the tools ------------------------------------------------------------------------------

def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


TOOLS = {
    "gmail": [
        {"name": "search_emails", "description": "Search the mailbox with Gmail search syntax (e.g. `is:unread newer_than:2d`, "
                                                 "`from:sam@example.com`). Returns sender, subject, date and a snippet.",
         "inputSchema": _schema({"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 25}})},
        {"name": "read_email", "description": "Read one email in full by its id (from search_emails).",
         "inputSchema": _schema({"id": {"type": "string"}}, ["id"])},
        {"name": "draft_email", "description": "Save a draft in Gmail's Drafts folder. Nothing is sent: the person reviews and "
                                                "sends it. Give reply_to_id to draft a reply in the same thread.",
         "inputSchema": _schema({"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                                 "cc": {"type": "string"}, "reply_to_id": {"type": "string"}}, ["to", "body"])},
        {"name": "send_email", "description": "Send an email. Agent Town saves it as a draft, then either shows the person a "
                                              "Send button or, if the rules they set for you allow it, sends it after a short "
                                              "wait they can cancel. The result says which. Either way it's Agent Town's check, "
                                              "not yours: don't also ask them in words. Give reply_to_id to reply in the same thread.",
         "inputSchema": _schema({"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                                 "cc": {"type": "string"}, "reply_to_id": {"type": "string"}}, ["to", "body"])},
        # answered from Agent Town's index of who they email (app/mailindex.py), not by Google
        {"name": "find_people", "description": "Look someone up in the person's email history (the last 90 days, from Agent "
                                               "Town's index): how often each of you wrote, when last, and the subjects of "
                                               "your latest emails. Search by name or address.",
         "inputSchema": _schema({"query": {"type": "string"}}, ["query"])},
        {"name": "open_loops", "description": "Email threads waiting on someone: waiting_on_me (the last email is from "
                                              "someone the person has written to, and they haven't answered) and gone_quiet "
                                              "(the person wrote last, over 3 days ago, and nobody answered). Oldest first. "
                                              "Use read_email with email_id for the text.",
         "inputSchema": _schema({})},
    ],
    "calendar": [
        {"name": "list_events", "description": "Events on the primary calendar, soonest first. Defaults to the next 7 days. "
                                               "Times are ISO 8601 (e.g. 2026-10-12T09:00:00Z).",
         "inputSchema": _schema({"time_min": {"type": "string"}, "time_max": {"type": "string"}, "query": {"type": "string"},
                                 "max_results": {"type": "integer", "minimum": 1, "maximum": 50}})},
        {"name": "create_event", "description": "Add an event to the primary calendar. start/end are ISO 8601 date-times, or "
                                                "dates (YYYY-MM-DD) for an all-day event. No invitations are sent.",
         "inputSchema": _schema({"summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
                                 "description": {"type": "string"}, "location": {"type": "string"},
                                 "time_zone": {"type": "string", "description": "e.g. Asia/Kolkata"}}, ["summary", "start", "end"])},
    ],
}


MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def message_id(value) -> str:
    """Gmail ids are hex-ish; anything else (a slash, a dot-dot) would change the URL we call."""
    v = str(value or "")
    if not MESSAGE_ID.fullmatch(v):
        raise GoogleError(f"Not a message id: {v[:40]!r}")
    return v


def _get(c: httpx.Client, url: str, token: str, **params) -> dict:
    r = c.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
    if r.status_code >= 400:
        err = GoogleError(f"Google said {r.status_code}: {r.json().get('error', {}).get('message', r.text[:200]) if r.content else ''}")
        err.status = r.status_code
        raise err
    return r.json()


def _post(c: httpx.Client, url: str, token: str, body: dict, **params) -> dict:
    r = c.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, params=params)
    if r.status_code >= 400:
        raise GoogleError(f"Google said {r.status_code}: {r.json().get('error', {}).get('message', r.text[:200]) if r.content else ''}")
    return r.json()


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body(payload: dict) -> tuple[str, list[str]]:
    """The message's text (plain if there is one, else the HTML with tags removed) and attachment names."""
    plain, rich, files = [], [], []
    def walk(p: dict):
        if p.get("filename"):
            files.append(p["filename"])
        elif p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
            plain.append(_decode(p["body"]["data"]))
        elif p.get("mimeType") == "text/html" and p.get("body", {}).get("data"):
            rich.append(_decode(p["body"]["data"]))
        for part in p.get("parts", []) or []:
            walk(part)
    walk(payload)
    text = "\n".join(plain) or html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", "\n".join(rich))))
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()
    return text[:MAX_TEXT] + ("…" if len(text) > MAX_TEXT else ""), files


def call(db: Session, acct: OAuthAccount, app: str, name: str, args: dict) -> dict:
    token = access_token(db, acct)
    with http() as c:
        if app == "gmail" and name == "search_emails":
            n = max(1, min(25, int(args.get("max_results") or 10)))
            found = _get(c, f"{GMAIL}/messages", token, q=args.get("query", ""), maxResults=n).get("messages", [])
            out = []
            for m in found:
                msg = _get(c, f"{GMAIL}/messages/{m['id']}", token, format="metadata",
                           metadataHeaders=["From", "To", "Subject", "Date"])
                h = _headers(msg.get("payload", {}))
                out.append({"id": msg["id"], "thread_id": msg.get("threadId"), "from": h.get("from"), "to": h.get("to"),
                            "subject": h.get("subject"), "date": h.get("date"), "snippet": html.unescape(msg.get("snippet", "")),
                            "unread": "UNREAD" in msg.get("labelIds", [])})
            return {"emails": out, "count": len(out)}
        if app == "gmail" and name == "read_email":
            msg = _get(c, f"{GMAIL}/messages/{message_id(args.get('id'))}", token, format="full")
            h = _headers(msg.get("payload", {}))
            text, files = _body(msg.get("payload", {}))
            return {"id": msg["id"], "thread_id": msg.get("threadId"), "from": h.get("from"), "to": h.get("to"),
                    "cc": h.get("cc"), "subject": h.get("subject"), "date": h.get("date"), "body": text, "attachments": files}
        if app == "gmail" and name in ("draft_email", "send_email"):
            em = EmailMessage()
            em["To"] = args["to"]
            if args.get("cc"):
                em["Cc"] = args["cc"]
            subject, thread = args.get("subject", ""), None
            if args.get("reply_to_id"):
                orig = _get(c, f"{GMAIL}/messages/{message_id(args['reply_to_id'])}", token, format="metadata",
                            metadataHeaders=["Message-ID", "Subject", "References"])
                h, thread = _headers(orig.get("payload", {})), orig.get("threadId")
                if h.get("message-id"):
                    em["In-Reply-To"] = h["message-id"]
                    em["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
                subject = subject or ("Re: " + h.get("subject", "")).replace("Re: Re:", "Re:")
            em["Subject"] = subject
            em.set_content(args["body"])
            draft = _post(c, f"{GMAIL}/drafts", token,
                          {"message": {"raw": b64url(em.as_bytes()), **({"threadId": thread} if thread else {})}})
            if name == "send_email":                 # the person decides: see routers/runs.py decide()
                return {"draft_id": draft.get("id"), "to": args["to"], "cc": args.get("cc") or "", "subject": subject,
                        "body": args["body"]}
            return {"draft_id": draft.get("id"), "saved": "In Gmail's Drafts. Nothing was sent."}
        if app == "calendar" and name == "list_events":
            now = datetime.now(timezone.utc)
            params = {"singleEvents": "true", "orderBy": "startTime",
                      "timeMin": args.get("time_min") or now.isoformat(),
                      "timeMax": args.get("time_max") or (now + timedelta(days=7)).isoformat(),
                      "maxResults": max(1, min(50, int(args.get("max_results") or 20)))}
            if args.get("query"):
                params["q"] = args["query"]
            items = _get(c, f"{CALENDAR}/events", token, **params).get("items", [])
            return {"events": [{"id": e.get("id"), "summary": e.get("summary"), "start": e.get("start"), "end": e.get("end"),
                                "location": e.get("location"), "attendees": [a.get("email") for a in e.get("attendees", [])],
                                "link": e.get("htmlLink")} for e in items]}
        if app == "calendar" and name == "create_event":
            def when(v: str) -> dict:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                    return {"date": v}
                return {"dateTime": v, **({"timeZone": args["time_zone"]} if args.get("time_zone") else {})}
            body = {"summary": args["summary"], "start": when(args["start"]), "end": when(args["end"])}
            for k in ("description", "location"):
                if args.get(k):
                    body[k] = args[k]
            e = _post(c, f"{CALENDAR}/events", token, body, sendUpdates="none")
            return {"id": e.get("id"), "link": e.get("htmlLink"), "added": "On the calendar. No invitations were sent."}
    raise GoogleError(f"No tool {name!r} for {app}")


def send_draft(db: Session, acct: OAuthAccount, draft_id: str) -> str:
    """Send a saved draft. Only ever called by app/outbox.py: the person pressed Send, or their rules allowed it."""
    token = access_token(db, acct)
    with http() as c:
        return _post(c, f"{GMAIL}/drafts/send", token, {"id": draft_id}).get("id", "")


def has_emailed(db: Session, acct: OAuthAccount, address: str) -> bool:
    """Has this mailbox ever sent mail to `address`? A live search of Sent Mail: nothing is copied or kept."""
    token = access_token(db, acct)
    with http() as c:
        return bool(_get(c, f"{GMAIL}/messages", token, q=f"in:sent to:{address}", maxResults=1).get("messages"))


def sync_tools(conn) -> None:
    """Keep a hosted connection's tool rows in step with TOOLS (names can change between versions).
    LinkedIn's and Agent Town's own hosted tools too (app/linkedin.py, app/town.py)."""
    from . import linkedin, town
    from .models import McpTool
    want = {t["name"]: t for t in {**TOOLS, **linkedin.TOOLS, **town.TOOLS}.get(conn.app, [])}
    conn.tools = [t for t in conn.tools if t.name in want]
    have = {t.name for t in conn.tools}
    conn.tools += [McpTool(name=n, description=t["description"], input_schema=t["inputSchema"]) for n, t in want.items() if n not in have]


def tool_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=1)[:MAX_TEXT * 2]
