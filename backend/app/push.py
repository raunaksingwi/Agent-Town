"""Web push: notifications on someone's phone or computer, even when Agent Town isn't open.

The browser (the installed app on a phone) subscribes with our public key and hands us an endpoint
at its push service (Google's, Apple's, Mozilla's). To notify, we encrypt a small JSON payload for that
subscription and POST it there; the service worker (frontend/public/sw.js) shows it.

    notify(user_id, title, body, url)    from anywhere: never blocks, never raises

The key pair (VAPID) is derived from AGENTTOWN_SECRET_KEY, so there's nothing to set up, and it stays
the same across restarts (a new key would orphan every subscription). What we send is short: who and
what ("Maya: your morning brief is ready"), never an email's text.

When: an email waits for your Send, a routine finished, or an agent answered while nobody was watching
its chat (watching(run_id) is called by the chat's polling).
"""

import base64
import hashlib
import hmac
import json
import logging
import threading
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import PushSubscription

log = logging.getLogger("agenttown.push")

WATCH_SECONDS = 20                       # a chat polled this recently has someone looking at it
_watched: dict[int, float] = {}
_session: sessionmaker | None = None     # set at startup (main.py); tests set their own
_send_sync = False                       # tests: send in the caller's thread


def _key() -> ec.EllipticCurvePrivateKey:
    seed = hmac.new(settings().secret_key.encode(), b"agent-town web push v1", hashlib.sha256).digest()
    n = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551   # P-256's group order
    return ec.derive_private_key(int.from_bytes(seed, "big") % (n - 1) + 1, ec.SECP256R1())


def public_key() -> str:
    """What the browser subscribes with (applicationServerKey): the raw point, base64url."""
    raw = _key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _pem() -> str:
    return _key().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()


def watching(run_id: int) -> None:
    _watched[run_id] = time.monotonic()


def watched(run_id: int) -> bool:
    return time.monotonic() - _watched.get(run_id, 0) < WATCH_SECONDS


def _deliver(user_id: int, payload: dict) -> None:
    try:
        _send(user_id, payload)
    except Exception:  # noqa: BLE001  (a notification is never worth an error anywhere else)
        log.exception("push to user %s failed", user_id)


def _send(user_id: int, payload: dict) -> None:
    from pywebpush import WebPushException, webpush
    if _session is None:
        return
    db = _session()
    try:
        for s in db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)).all():
            try:
                webpush({"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}, json.dumps(payload),
                        vapid_private_key=_pem(), vapid_claims={"sub": f"mailto:push@{_host()}"}, ttl=86400, timeout=10)
            except WebPushException as e:
                if e.response is not None and e.response.status_code in (404, 410):
                    db.delete(s)              # unsubscribed, or the app was removed: forget it
                else:
                    log.warning("push to user %s failed: %s", user_id, e)
        db.commit()
    finally:
        db.close()


def _host() -> str:
    from urllib.parse import urlparse
    return urlparse(settings().app_url).hostname or "localhost"


def notify(user_id: int, title: str, body: str, url: str = "/chat", tag: str | None = None) -> None:
    """Fire and forget. `tag` replaces an earlier notification with the same tag instead of stacking."""
    payload = {"title": title[:80], "body": body[:200], "url": url, **({"tag": tag} if tag else {})}
    if _send_sync:
        _deliver(user_id, payload)
    else:
        threading.Thread(target=_deliver, args=(user_id, payload), daemon=True).start()
