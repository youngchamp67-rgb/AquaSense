"""Shared, test-isolated pytest fixtures."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import create_app
from app.extensions import db
from app.services.ingestion import IngestionService


# These values exist only inside the test suite. The application, dashboard,
# and documented examples never generate or display test measurements.
def _test_payload() -> dict[str, object]:
    return {
        "ph": 7.25,
        "tds_ppm": 321.0,
        "temperature_c": 21.5,
        "recorded_at": "2026-10-24T12:00:00Z",
        "source": "pytest-test-only",
        "packet_sequence": None,
    }


@pytest.fixture()
def app_factory(tmp_path):
    """Create apps backed by separate temporary SQLite files."""
    applications = []
    counter = 0

    def factory(**overrides):
        nonlocal counter
        counter += 1
        database_path = tmp_path / f"aquasense-test-{counter}.sqlite3"

        config = {
            "TESTING": True,
            "SECRET_KEY": "test-only-key",
            "PROPAGATE_EXCEPTIONS": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "STALE_AFTER_SECONDS": 300,
            "DATA_SOURCE_CONFIGURED": False,
        }
        config.update(overrides)
        application = create_app(config)
        applications.append(application)
        return application

    yield factory

    for application in applications:
        with application.app_context():
            db.session.remove()
            db.drop_all()


@pytest.fixture()
def app(app_factory):
    return app_factory()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def reading_payload():
    """Return a clearly labelled test-only payload factory."""
    def make(**overrides):
        payload = _test_payload()
        payload.update(overrides)
        return payload

    return make


@pytest.fixture()
def store_reading(app):
    """Persist a test-only reading and return its database id."""
    def store(payload=None, *, received_at=None):
        candidate = _test_payload() if payload is None else payload
        with app.app_context():
            reading = IngestionService().ingest(
                candidate,
                received_at=received_at or datetime.now(timezone.utc),
            )
            return reading.id

    return store
