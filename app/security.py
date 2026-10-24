"""Security and cache headers applied to every response."""

from __future__ import annotations

from flask import Flask, request

_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "form-action 'none'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'"
)


def register_security_headers(app: Flask) -> None:
    @app.after_request
    def apply_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)

        # Status and sensor availability must never be served from a stale
        # browser/proxy cache.
        if request.path.startswith("/api/") or request.endpoint == "pages.dashboard":
            response.headers["Cache-Control"] = "no-store"

        return response
