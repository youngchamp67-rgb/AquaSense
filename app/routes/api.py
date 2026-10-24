"""Read-only JSON API for the AquaSense dashboard."""

from __future__ import annotations

import re
import time

from flask import Blueprint, Response, current_app, request

from ..responses import error_response, success_response

api_bp = Blueprint("api", __name__)

_MAX_HISTORY_OFFSET = 1_000_000


@api_bp.get("/health")
def health() -> Response:
    """Report application health without implying the receiver is online."""
    service = current_app.extensions["readings"]
    started_at = current_app.extensions["started_at"]
    uptime = max(0.0, time.monotonic() - started_at)

    payload = {
        "status": "ok",
        "service": "aquasense",
        "version": current_app.config["APP_VERSION"],
        "uptime_seconds": round(uptime, 3),
        "data_source": {
            "configured": service.source_configured,
            "receiver_status": service.receiver_status,
        },
    }
    return success_response(payload)


@api_bp.get("/readings/latest")
def latest_reading() -> Response:
    """Return the latest persisted reading or an explicit no-data state.

    ``available: false`` with null sensor values is a successful response, not
    an error. A stored partial reading is valid and preserves unavailable
    measurements as ``null``.
    """
    service = current_app.extensions["readings"]
    return success_response(service.latest_payload())


@api_bp.get("/readings/history")
def reading_history() -> Response:
    """Return a bounded page of persisted readings, newest first."""
    service = current_app.extensions["readings"]
    try:
        limit = _query_integer("limit", default=20, minimum=1, maximum=100)
        offset = _query_integer(
            "offset",
            default=0,
            minimum=0,
            maximum=_MAX_HISTORY_OFFSET,
        )
    except ValueError as exc:
        return error_response("invalid_query_parameter", str(exc), 400)

    return success_response(service.history_payload(limit=limit, offset=offset))


def _query_integer(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw_value = request.args.get(name)
    if raw_value is None:
        return default

    if re.fullmatch(r"[0-9]+", raw_value) is None:
        raise ValueError(
            f"{name} must be an integer between {minimum} and {maximum}."
        )

    value = int(raw_value)
    if not minimum <= value <= maximum:
        raise ValueError(
            f"{name} must be an integer between {minimum} and {maximum}."
        )
    return value
