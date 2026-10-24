"""AquaSense application factory.

Phase 2 adds validated local SQLite persistence, history queries, and an
internal CLI ingestion path. There is still no receiver transport or public
write endpoint, and no measurement is ever simulated.
"""

from __future__ import annotations

import mimetypes
import os
import secrets
import time
from pathlib import Path
from typing import Any

from flask import Flask
from sqlalchemy.engine import make_url

from .cli import register_cli
from .errors import register_error_handlers
from .extensions import db
from .routes.api import api_bp
from .routes.pages import pages_bp
from .security import register_security_headers
from .services.readings import DEFAULT_STALE_AFTER_SECONDS, ReadingService

APP_VERSION = "0.2.0"

# Windows can inherit a registry mapping of .js to text/plain, which browsers
# reject for strict MIME checking. Pin the types this application serves.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create and configure the AquaSense Flask application."""
    app = Flask(__name__)

    app.config.from_mapping(
        APP_NAME="AquaSense",
        APP_VERSION=APP_VERSION,
        # No sessions are used yet. An ephemeral key keeps development simple
        # and still allows an operator to provide a stable key via environment.
        SECRET_KEY=os.environ.get("AQUASENSE_SECRET_KEY") or secrets.token_hex(32),
        # Phase 2 has no receiver transport. Tests may override this to verify
        # the "WAITING FOR DATA" state without inventing sensor values.
        DATA_SOURCE_CONFIGURED=False,
        SQLALCHEMY_DATABASE_URI=_default_database_uri(app),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        STALE_AFTER_SECONDS=_positive_int_from_env(
            "AQUASENSE_STALE_AFTER_SECONDS",
            DEFAULT_STALE_AFTER_SECONDS,
        ),
    )

    if test_config:
        app.config.update(test_config)

    _ensure_sqlite_parent_directory(app.config["SQLALCHEMY_DATABASE_URI"])

    # Preserve declaration order in JSON responses for readable payloads.
    app.json.sort_keys = False

    db.init_app(app)

    app.extensions["readings"] = ReadingService(
        source_configured=bool(app.config["DATA_SOURCE_CONFIGURED"]),
        stale_after_seconds=int(app.config["STALE_AFTER_SECONDS"]),
    )
    app.extensions["started_at"] = time.monotonic()

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    register_cli(app)

    register_error_handlers(app)
    register_security_headers(app)

    @app.context_processor
    def inject_app_metadata() -> dict[str, str]:
        return {
            "app_name": app.config["APP_NAME"],
            "app_version": app.config["APP_VERSION"],
        }

    # This local application has no migration tooling yet. Creating missing
    # tables at startup makes a fresh checkout usable without a setup step.
    with app.app_context():
        db.create_all()

    return app


def _default_database_uri(app: Flask) -> str:
    configured = os.environ.get("AQUASENSE_DATABASE_URL")
    if configured:
        return configured

    database_path = Path(app.instance_path) / "aquasense.sqlite3"
    return f"sqlite:///{database_path.as_posix()}"


def _ensure_sqlite_parent_directory(database_uri: str) -> None:
    url = make_url(database_uri)
    if url.get_backend_name() != "sqlite":
        return

    database = url.database
    if not database or database == ":memory:":
        return

    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _positive_int_from_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw_value!r}.") from exc

    if value < 1:
        raise RuntimeError(f"{name} must be at least 1, got {value}.")

    return value
