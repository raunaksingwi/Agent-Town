"""What a connection needs to get in: its headers (an Authorization header, any others), the
environment for a command, or a sign-in with the app itself.

Sign-in is MCP's own authorization (spec: Authorization, 2025-06-18), the "connectors" Claude and
Codex have, so any app that supports it connects without setup:

  1. discover  the server answers 401; its protected-resource metadata (from the WWW-Authenticate
               header, or /.well-known/oauth-protected-resource) names its authorization server,
               whose metadata lists the endpoints. Older servers serve that metadata themselves.
  2. register  dynamic client registration: Agent Town introduces itself and gets a client id.
               An app that doesn't allow that needs a client id (and secret) from its owner.
  3. sign in   authorization code + PKCE, with `resource` set to the server, like Google sign-in.
  4. use       the access token goes out as "Authorization: Bearer …"; refreshed when near expiry.

Everything here is stored encrypted on the connection (`oauth_enc`), and none of it is returned
by the API. Every URL a server points us at goes through the same SSRF guard as the server itself.
"""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import httpx

from .config import settings
from .mcp_client import McpError, fetch, guard_url
from .models import McpConnection
from .security import decrypt, encrypt

TIMEOUT = 15.0
REFRESH_EARLY = timedelta(minutes=5)


class AuthError(Exception):
    pass


class Expired(AuthError):
    """The app won't refresh this sign-in any more: sign in again."""


def http() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False)


def redirect_uri() -> str:
    return settings().app_url.rstrip("/") + "/api/connect/mcp/callback"


# ---- stored secrets ---------------------------------------------------------------------------

def _load(blob: str | None) -> dict:
    if not blob:
        return {}
    try:
        return json.loads(decrypt(blob) or "{}")
    except ValueError:
        return {}


def _dump(d: dict) -> str | None:
    return encrypt(json.dumps(d)) if d else None


def headers(c: McpConnection) -> dict[str, str]:
    return _load(c.headers_enc)


def set_headers(c: McpConnection, h: dict[str, str]) -> None:
    c.headers_enc = _dump(h)


def env(c: McpConnection) -> dict[str, str]:
    return _load(c.env_enc)


def set_env(c: McpConnection, e: dict[str, str]) -> None:
    c.env_enc = _dump(e)


def oauth(c: McpConnection) -> dict:
    return _load(c.oauth_enc)


def set_oauth(c: McpConnection, o: dict) -> None:
    c.oauth_enc = _dump(o)


def sign_in_state(c: McpConnection) -> str:
    """For the UI: none (no sign-in), available (it has one, not signed in yet) or signed_in."""
    o = oauth(c)
    return "signed_in" if o.get("access_token") else "available" if o.get("authorization_endpoint") else "none"


def request_headers(c: McpConnection) -> dict[str, str]:
    """Every header a request to this server carries. The sign-in wins over a pasted Authorization
    header, which wins over one among the other headers."""
    h = headers(c)
    if c.auth_header_enc:
        h = {k: v for k, v in h.items() if k.lower() != "authorization"}
        h["Authorization"] = decrypt(c.auth_header_enc) or ""
    token = access_token(c)
    if token:
        h = {k: v for k, v in h.items() if k.lower() != "authorization"}
        h["Authorization"] = f"Bearer {token}"
    return h


# ---- discovery --------------------------------------------------------------------------------

def _get_json(client: httpx.Client, url: str) -> dict | None:
    guard_url(url, settings().allow_private_mcp_hosts)
    try:
        r = fetch(client, "GET", url, headers={"Accept": "application/json", "MCP-Protocol-Version": "2025-06-18"})
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        body = r.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _well_known(base: str, name: str) -> list[str]:
    """RFC 8414 / 9728: the well-known name goes between the host and the path; then the root."""
    u = urlparse(base)
    root = f"{u.scheme}://{u.netloc}"
    path = u.path.rstrip("/")
    return [f"{root}/.well-known/{name}{path}", f"{root}/.well-known/{name}"] if path else [f"{root}/.well-known/{name}"]


def _param(www_authenticate: str, key: str) -> str | None:
    for part in www_authenticate.replace("Bearer ", "", 1).split(","):
        k, _, v = part.strip().partition("=")
        if k.strip() == key and v:
            return v.strip().strip('"')
    return None


def discover(server_url: str, www_authenticate: str = "") -> dict | None:
    """The server's sign-in endpoints, or None if it doesn't offer a sign-in."""
    with http() as client:
        try:
            prm_urls = ([u] if (u := _param(www_authenticate, "resource_metadata")) else []) \
                + _well_known(server_url, "oauth-protected-resource")
            prm = next((p for p in (_get_json(client, u) for u in prm_urls) if p and p.get("authorization_servers")), None)
            issuer = prm["authorization_servers"][0] if prm else server_url  # older servers: the server is its own
            meta = None
            for name in ("oauth-authorization-server", "openid-configuration"):
                meta = next((m for m in (_get_json(client, u) for u in _well_known(issuer, name))
                             if m and m.get("authorization_endpoint") and m.get("token_endpoint")), None)
                if meta:
                    break
            if not meta:
                return None
            scope = _param(www_authenticate, "scope") or " ".join((prm or {}).get("scopes_supported") or [])
            return {"authorization_endpoint": meta["authorization_endpoint"], "token_endpoint": meta["token_endpoint"],
                    "registration_endpoint": meta.get("registration_endpoint", ""),
                    "revocation_endpoint": meta.get("revocation_endpoint", ""),
                    "resource": (prm or {}).get("resource") or server_url, "scope": scope}
        except McpError:
            return None


# ---- signing in -------------------------------------------------------------------------------

def _post(url: str, **kw) -> httpx.Response:
    try:
        guard_url(url, settings().allow_private_mcp_hosts)
        with http() as client:
            return fetch(client, "POST", url, **kw)
    except McpError as e:
        raise AuthError(str(e)) from e
    except httpx.HTTPError as e:
        raise AuthError(f"{type(e).__name__}: {e}") from e


def register(o: dict) -> dict:
    """Dynamic client registration (RFC 7591), once per connection and redirect address."""
    if o.get("client_id") and (o.get("registered_for") in (None, redirect_uri())):
        return o
    if not o.get("registration_endpoint"):
        raise AuthError("This app doesn't let new apps register themselves. Add a client ID from the app's "
                        "developer settings (with redirect URL " + redirect_uri() + "), then sign in again.")
    r = _post(o["registration_endpoint"], json={
        "client_name": "Agent Town", "redirect_uris": [redirect_uri()],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none"})
    if r.status_code >= 400:
        raise AuthError(f"The app refused to register Agent Town (HTTP {r.status_code}): {r.text[:200]}")
    body = r.json()
    return {**o, "client_id": body["client_id"], "client_secret": body.get("client_secret", ""),
            "registered_for": redirect_uri()}


def authorize_url(o: dict, state: str, challenge: str) -> str:
    q = {"response_type": "code", "client_id": o["client_id"], "redirect_uri": redirect_uri(), "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256", "resource": o["resource"]}
    if o.get("scope"):
        q["scope"] = o["scope"]
    sep = "&" if "?" in o["authorization_endpoint"] else "?"
    return o["authorization_endpoint"] + sep + urlencode(q)


def _token(o: dict, data: dict) -> dict:
    data = {**data, "client_id": o["client_id"], "resource": o["resource"]}
    auth = None
    if o.get("client_secret"):
        auth = (o["client_id"], o["client_secret"])
    r = _post(o["token_endpoint"], data=data, auth=auth, headers={"Accept": "application/json"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400 or "access_token" not in body:
        if body.get("error") == "invalid_grant":
            raise Expired(body.get("error_description") or "The app won't refresh this sign-in any more")
        raise AuthError(f"The app said {r.status_code}: {body.get('error_description') or body.get('error') or r.text[:200]}")
    return body


def _store(o: dict, tok: dict) -> dict:
    expires = tok.get("expires_in")
    return {**o, "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token") or o.get("refresh_token", ""),
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(expires))).isoformat() if expires else ""}


def exchange(c: McpConnection, code: str, verifier: str) -> None:
    o = oauth(c)
    tok = _token(o, {"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                     "redirect_uri": redirect_uri()})
    set_oauth(c, _store(o, tok))


def access_token(c: McpConnection) -> str | None:
    """The current access token, refreshed first if it's about to run out. Expired: sign in again."""
    o = oauth(c)
    if not o.get("access_token"):
        return None
    exp = datetime.fromisoformat(o["expires_at"]) if o.get("expires_at") else None
    if exp is None or exp - datetime.now(timezone.utc) > REFRESH_EARLY:
        return o["access_token"]
    if not o.get("refresh_token"):
        raise Expired("The sign-in ran out and the app gave no way to renew it")
    try:
        o = _store(o, _token(o, {"grant_type": "refresh_token", "refresh_token": o["refresh_token"]}))
    except Expired:
        set_oauth(c, {k: v for k, v in o.items() if k not in ("access_token", "refresh_token", "expires_at")})
        raise
    set_oauth(c, o)
    return o["access_token"]


def sign_out(c: McpConnection) -> None:
    o = oauth(c)
    if o.get("revocation_endpoint") and o.get("refresh_token"):
        try:
            _post(o["revocation_endpoint"], data={"token": o["refresh_token"], "client_id": o["client_id"]})
        except AuthError:
            pass  # best effort: our copy goes either way
    set_oauth(c, {k: v for k, v in o.items() if k not in ("access_token", "refresh_token", "expires_at")})

