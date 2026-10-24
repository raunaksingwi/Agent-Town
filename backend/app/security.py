"""Passwords, session tokens and secrets at rest."""

import base64
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_hasher = PasswordHasher()  # argon2id with the library's tuned defaults


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_session_token() -> tuple[str, str]:
    """(cookie value, what the database stores). Only the hash is ever written down."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


API_TOKEN_PREFIX = "at_"


def new_api_token() -> tuple[str, str]:
    """Like a session token, but with a recognisable prefix so leaked tokens are easy to spot
    (and secret scanners can be taught the pattern)."""
    token = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token)


RUN_TOKEN_PREFIX = "rt_"


def new_run_token() -> tuple[str, str]:
    """What a sandbox uses to talk to us. Unlike an API token it's good for one run only."""
    token = RUN_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    key = hashlib.sha256(settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None
