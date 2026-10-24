"""UTC timestamp helpers shared by persistence, validation, and the API."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to UTC, treating naive database values as UTC.

    SQLite does not retain timezone information for ``DateTime`` columns. The
    application always writes UTC, so a naive stored value is interpreted as
    UTC rather than silently applying the local machine timezone.
    """
    if not isinstance(value, datetime):
        raise TypeError("Expected a datetime value.")

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def parse_utc_timestamp(value: object) -> datetime:
    """Parse a timezone-aware ISO 8601 timestamp and normalize it to UTC.

    The timestamp must include an explicit offset or ``Z``. Rejecting naive
    timestamps avoids guessing a timezone and silently shifting a measurement.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("must be a non-empty ISO 8601 timestamp")

        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"

        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(
                "must be an ISO 8601 timestamp with a UTC offset or Z suffix"
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("must be an ISO 8601 string")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("must include a timezone offset or Z suffix")

    return parsed.astimezone(timezone.utc)


def to_utc_iso(value: datetime) -> str:
    """Format a datetime as a UTC ISO 8601 string ending in ``Z``."""
    return ensure_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")
