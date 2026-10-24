"""Sign in with ChatGPT, for agents that think with Codex on the user's ChatGPT plan.

The same device-code login `codex login --device-auth` does (codex-rs/login/src/device_code_auth.rs):
  1. ask OpenAI for a one-time code; the user types it at auth.openai.com/codex/device and approves
  2. poll until they have: OpenAI then hands back an authorization code plus its PKCE pair
  3. trade that for tokens at /oauth/token, and write them as the auth.json Codex reads
A web app can't use Codex's browser login: OpenAI only redirects that one to localhost. The device
code needs no redirect, so a hosted server can run it. Each step is one short request; the browser
polls (step 2) so no server thread waits on the user.

The login handle the browser holds is encrypted with the server key and names its user, so it is
useless to anyone else, and the device_auth_id never reaches the page.
"""

import base64
import json
import time
from datetime import datetime, timezone

import httpx

from .security import decrypt, encrypt

ISSUER = "https://auth.openai.com"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"      # Codex CLI's public client (codex-rs/login/src/auth)
VERIFY_URL = f"{ISSUER}/codex/device"
EXPIRES = 15 * 60                                # OpenAI's code lifetime
now = time.time                                  # patched in tests


class LoginError(Exception):
    pass


def http() -> httpx.Client:
    return httpx.Client(timeout=15)


def start(user_id: int) -> dict:
    """Step 1: a code for the user to enter, and the handle the browser polls with."""
    with http() as c:
        try:
            r = c.post(f"{ISSUER}/api/accounts/deviceauth/usercode", json={"client_id": CLIENT_ID})
        except httpx.HTTPError as e:
            raise LoginError(f"Couldn't reach OpenAI ({type(e).__name__}). Try again in a minute.") from e
    if r.status_code == 404:
        raise LoginError("OpenAI turned off sign-in with a code. Paste your auth.json instead.")
    if r.status_code != 200:
        raise LoginError(f"OpenAI answered HTTP {r.status_code}. Try again in a minute.")
    d = r.json()
    code = d.get("user_code") or d.get("usercode")
    interval = int(str(d.get("interval") or 5).strip())
    handle = encrypt(json.dumps({"u": user_id, "d": d["device_auth_id"], "c": code, "exp": now() + EXPIRES}))
    return {"handle": handle, "code": code, "url": VERIFY_URL, "interval": max(interval, 2), "expires_in": EXPIRES}


def poll(user_id: int, handle: str) -> str | None:
    """Step 2 and 3: None while the user hasn't approved yet, then the auth.json to store."""
    raw = decrypt(handle)
    h = json.loads(raw) if raw else None
    if not h or h["u"] != user_id:
        raise LoginError("That sign-in isn't yours. Start again.")
    if now() > h["exp"]:
        raise LoginError("The code expired. Start again.")
    with http() as c:
        try:
            r = c.post(f"{ISSUER}/api/accounts/deviceauth/token", json={"device_auth_id": h["d"], "user_code": h["c"]})
            if r.status_code in (403, 404):          # not approved yet
                return None
            if r.status_code != 200:
                raise LoginError(f"OpenAI answered HTTP {r.status_code}. Start again.")
            got = r.json()
            t = c.post(f"{ISSUER}/oauth/token", data={
                "grant_type": "authorization_code", "code": got["authorization_code"],
                "redirect_uri": f"{ISSUER}/deviceauth/callback", "client_id": CLIENT_ID,
                "code_verifier": got["code_verifier"]})
        except httpx.HTTPError as e:
            raise LoginError(f"Couldn't reach OpenAI ({type(e).__name__}). Try again.") from e
    if t.status_code != 200:
        raise LoginError(f"OpenAI didn't finish the sign-in (HTTP {t.status_code}). Start again.")
    return auth_json(t.json())


def auth_json(tok: dict) -> str:
    """The file Codex reads (AuthDotJson in codex-rs/login/src/auth/storage.rs)."""
    return json.dumps({
        "OPENAI_API_KEY": None,
        "tokens": {"id_token": tok["id_token"], "access_token": tok["access_token"],
                   "refresh_token": tok["refresh_token"], "account_id": account_id(tok["id_token"])},
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })


def account_id(id_token: str) -> str | None:
    """The ChatGPT workspace, from the id token's claims (Codex reads it the same way)."""
    try:
        part = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None
    return (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
