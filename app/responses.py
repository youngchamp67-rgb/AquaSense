"""Consistent JSON response helpers for the AquaSense API."""

from __future__ import annotations

from typing import Any

from flask import Response, jsonify

from .time_utils import to_utc_iso, utc_now


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string ending in ``Z``."""
    return to_utc_iso(utc_now())


def success_response(data: Any, status: int = 200) -> Response:
    """Build a successful API response using the shared envelope."""
    return _json_response(
        {
            "ok": True,
            "data": data,
            "error": None,
            "timestamp": utc_now_iso(),
        },
        status=status,
    )


def error_response(code: str, message: str, status: int) -> Response:
    """Build an error response without exposing internal exception details."""
    return _json_response(
        {
            "ok": False,
            "data": None,
            "error": {
                "code": code,
                "message": message,
            },
            "timestamp": utc_now_iso(),
        },
        status=status,
    )


def _json_response(payload: dict[str, Any], status: int) -> Response:
    response = jsonify(payload)
    response.status_code = status
    return response
