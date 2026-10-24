"""Slowing down password guessing and sign-up floods.

A sliding window per key, in this process's memory. That's enough for one API process (what
render.yaml runs); with several, each one allows its own share, which still caps the total.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)
enabled = True   # tests turn it off, except the ones about it


def client_ip(request: Request) -> str:
    """Behind Render's proxy the real address is the first X-Forwarded-For hop; anywhere else that
    header could be forged, so only trust it when the proxy says it added one."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and request.headers.get("x-forwarded-proto"):
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Record one attempt for key. False when key already had `limit` attempts in the window."""
    if not enabled:
        return True
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and q[0] < now - window_seconds:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def check(key: str, limit: int, window_seconds: int, what: str) -> None:
    if not hit(key, limit, window_seconds):
        raise HTTPException(429, f"Too many {what}; wait a few minutes and try again", headers={"Retry-After": "300"})


def forget(key: str) -> None:
    """A success clears the count for the key (a right password after a few wrong ones)."""
    with _lock:
        _hits.pop(key, None)


def reset() -> None:
    with _lock:
        _hits.clear()
