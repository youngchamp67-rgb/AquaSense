"""HTML and JSON error handling for AquaSense."""

from __future__ import annotations

from flask import Flask, current_app, render_template, request
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from .extensions import db
from .responses import error_response

_HTTP_ERRORS = {
    400: ("bad_request", "The request could not be understood."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "That HTTP method is not allowed for this resource."),
    413: ("payload_too_large", "The request payload is too large."),
    415: ("unsupported_media_type", "The request content type is not supported."),
}
_DEFAULT_HTTP_ERROR = ("request_error", "The request could not be completed.")

_PAGE_TITLES = {
    400: "Bad request",
    404: "Page not found",
    405: "Method not allowed",
}

_DEFAULT_PAGE_MESSAGE = "The server could not complete this request."


def register_error_handlers(app: Flask) -> None:
    """Attach handlers that keep API errors JSON and page errors friendly."""

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        status = error.code if isinstance(error.code, int) else 500
        code, message = _HTTP_ERRORS.get(status, _DEFAULT_HTTP_ERROR)

        if _is_api_request():
            return error_response(code, message, status)

        return (
            render_template(
                "error.html",
                error_code=status,
                error_title=_PAGE_TITLES.get(status, "Request failed"),
                error_message=_DEFAULT_PAGE_MESSAGE if status >= 500 else message,
            ),
            status,
        )

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error: SQLAlchemyError):
        # Roll back the request session so a failed transaction cannot leak
        # into a later request. Details stay in the server log.
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive cleanup only
            pass

        current_app.logger.exception(
            "Database error while serving %s", request.path
        )

        if _is_api_request():
            return error_response(
                "database_error",
                "The database could not complete this request.",
                500,
            )

        return (
            render_template(
                "error.html",
                error_code=500,
                error_title="Database unavailable",
                error_message="The local reading database could not complete this request.",
            ),
            500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        # Full details stay in the server log; dashboard users get a generic
        # message so tracebacks and filesystem paths are never exposed.
        current_app.logger.exception(
            "Unhandled exception while serving %s", request.path
        )

        if _is_api_request():
            return error_response(
                "internal_error",
                "An unexpected server error occurred.",
                500,
            )

        return (
            render_template(
                "error.html",
                error_code=500,
                error_title="Something went wrong",
                error_message="The server could not complete this request. Please try again.",
            ),
            500,
        )


def _is_api_request() -> bool:
    return request.path == "/api" or request.path.startswith("/api/")
