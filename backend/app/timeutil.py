"""Datetimes the same way everywhere. SQLite hands back naive datetimes (it drops the offset) and
Postgres aware ones; every JSON the API emits must say "+00:00" on both, or the browser reads a
naive stamp as local time and dev and production disagree by the user's UTC offset."""

from datetime import datetime, timezone


def utc(dt: datetime) -> datetime:
    """An aware UTC datetime. Everything we store is UTC, so a naive one is UTC that lost its label."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return utc(dt).isoformat() if dt else None


def now() -> datetime:
    return datetime.now(timezone.utc)
