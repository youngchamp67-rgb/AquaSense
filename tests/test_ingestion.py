"""Validation, persistence, duplicate, and CLI ingestion tests."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Reading
from app.services.ingestion import (
    DuplicateReadingError,
    IngestionService,
    ReadingValidationError,
)
from app.time_utils import ensure_utc


def stored_count(app) -> int:
    with app.app_context():
        return int(
            db.session.scalar(select(func.count()).select_from(Reading)) or 0
        )


def test_valid_reading_is_persisted(app, reading_payload):
    payload = reading_payload(packet_sequence=17)
    received_at = datetime(2026, 10, 24, 12, 1, 2, tzinfo=timezone.utc)

    with app.app_context():
        reading = IngestionService().ingest(payload, received_at=received_at)
        reading_id = reading.id

        stored = db.session.get(Reading, reading_id)
        assert stored is not None
        assert stored.ph == pytest.approx(7.25)
        assert stored.tds_ppm == pytest.approx(321.0)
        assert stored.temperature_c == pytest.approx(21.5)
        assert stored.source == "pytest-test-only"
        assert stored.packet_sequence == 17
        assert ensure_utc(stored.recorded_at) == datetime(
            2026, 10, 24, 12, 0, tzinfo=timezone.utc
        )
        assert ensure_utc(stored.received_at) == received_at

    assert stored_count(app) == 1


def test_partial_reading_preserves_missing_measurements(app, reading_payload):
    payload = reading_payload()
    del payload["tds_ppm"]
    del payload["temperature_c"]

    with app.app_context():
        reading = IngestionService().ingest(payload)
        reading_id = reading.id

        stored = db.session.get(Reading, reading_id)
        assert stored is not None
        assert stored.ph == pytest.approx(7.25)
        assert stored.tds_ppm is None
        assert stored.temperature_c is None

    latest = app.test_client().get("/api/readings/latest").get_json()["data"]
    assert latest["available"] is True
    assert latest["state"] == "ok"
    assert latest["readings"] == {
        "ph": 7.25,
        "tds_ppm": None,
        "temperature_c": None,
    }
    assert latest["receiver"]["status"] == "RECENT_DATA"


def test_zero_is_not_substituted_for_missing_measurements(app, reading_payload):
    payload = reading_payload()
    for key in ("tds_ppm", "temperature_c"):
        del payload[key]

    with app.app_context():
        persisted = IngestionService().ingest(payload)
        persisted_id = persisted.id

    with app.app_context():
        stored = db.session.get(Reading, persisted_id)
        assert stored is not None
        assert stored.tds_ppm is None
        assert stored.temperature_c is None


def test_reading_without_any_measurement_is_rejected(app, reading_payload):
    payload = reading_payload(ph=None, tds_ppm=None, temperature_c=None)

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert "readings" in exc_info.value.errors
    assert stored_count(app) == 0


@pytest.mark.parametrize("value", ["7.2", True, [], {}])
@pytest.mark.parametrize("key", ["ph", "tds_ppm", "temperature_c"])
def test_malformed_measurement_types_are_rejected(
    app, reading_payload, key, value
):
    payload = reading_payload(**{key: value})

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert key in exc_info.value.errors
    assert stored_count(app) == 0


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, -math.inf],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
@pytest.mark.parametrize("key", ["ph", "tds_ppm", "temperature_c"])
def test_non_finite_measurements_are_rejected(app, reading_payload, key, value):
    payload = reading_payload(**{key: value})

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert "finite" in exc_info.value.errors[key]
    assert stored_count(app) == 0


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ph", -0.1),
        ("ph", 14.1),
        ("temperature_c", -55.1),
        ("temperature_c", 125.1),
        ("tds_ppm", -0.1),
    ],
)
def test_out_of_range_measurements_are_rejected(
    app, reading_payload, key, value
):
    payload = reading_payload(**{key: value})

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert key in exc_info.value.errors
    assert stored_count(app) == 0


def test_documented_sensor_boundaries_are_accepted(app, reading_payload):
    payload = reading_payload(
        ph=0.0,
        tds_ppm=0.0,
        temperature_c=-55.0,
        packet_sequence=1,
    )

    with app.app_context():
        reading = IngestionService().ingest(payload)
        assert reading.id is not None

    payload = reading_payload(
        ph=14.0,
        tds_ppm=0.0,
        temperature_c=125.0,
        packet_sequence=2,
    )
    with app.app_context():
        reading = IngestionService().ingest(payload)
        assert reading.id is not None


@pytest.mark.parametrize(
    "recorded_at",
    [
        "not-a-timestamp",
        "2026-10-24T12:00:00",
        "2026-10-24",
        "",
        123,
        None,
        "2026-13-40T12:00:00Z",
    ],
)
def test_invalid_timestamps_are_rejected(app, reading_payload, recorded_at):
    payload = reading_payload(recorded_at=recorded_at)

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert "recorded_at" in exc_info.value.errors
    assert stored_count(app) == 0


def test_timestamp_is_normalized_to_utc(app, reading_payload, store_reading):
    payload = reading_payload(
        recorded_at="2026-10-24T18:30:00+05:30",
        packet_sequence=3,
    )
    store_reading(payload)

    latest = app.test_client().get("/api/readings/latest").get_json()["data"]

    assert latest["recorded_at"] == "2026-10-24T13:00:00Z"
    assert latest["received_at"].endswith("Z")


def test_unknown_fields_are_rejected(app, reading_payload):
    payload = reading_payload(unexpected="value")

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert "fields" in exc_info.value.errors
    assert "unexpected" in exc_info.value.errors["fields"]


@pytest.mark.parametrize(
    "source",
    ["", "   ", 123, "x" * 65, "line\nbreak", None],
)
def test_invalid_sources_are_rejected(app, reading_payload, source):
    payload = reading_payload(source=source)

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert "source" in exc_info.value.errors
    assert stored_count(app) == 0


def test_source_is_required(app, reading_payload):
    payload = reading_payload()
    del payload["source"]

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert "source" in exc_info.value.errors


@pytest.mark.parametrize(
    "packet_sequence",
    [-1, True, 1.0, "1", 2**63],
)
def test_invalid_packet_sequences_are_rejected(
    app, reading_payload, packet_sequence
):
    payload = reading_payload(packet_sequence=packet_sequence)

    with pytest.raises(ReadingValidationError) as exc_info:
        with app.app_context():
            IngestionService().ingest(payload)

    assert "packet_sequence" in exc_info.value.errors
    assert stored_count(app) == 0


def test_duplicate_packet_identifier_is_rejected(app, reading_payload):
    payload = reading_payload(packet_sequence=42)

    with app.app_context():
        IngestionService().ingest(payload)

    with pytest.raises(DuplicateReadingError):
        with app.app_context():
            IngestionService().ingest(payload)

    assert stored_count(app) == 1


def test_duplicate_packet_identifier_is_scoped_to_source(app, reading_payload):
    with app.app_context():
        IngestionService().ingest(
            reading_payload(source="source-a", packet_sequence=5)
        )
        IngestionService().ingest(
            reading_payload(source="source-b", packet_sequence=5)
        )

    assert stored_count(app) == 2


def test_omitted_packet_identifiers_are_not_invented(app, reading_payload):
    with app.app_context():
        first = IngestionService().ingest(reading_payload())
        second = IngestionService().ingest(reading_payload())

        assert first.packet_sequence is None
        assert second.packet_sequence is None

    assert stored_count(app) == 2


def test_validation_failure_does_not_write(app, reading_payload):
    payload = reading_payload(ph=math.nan)

    with pytest.raises(ReadingValidationError):
        with app.app_context():
            IngestionService().ingest(payload)

    assert stored_count(app) == 0


def test_cli_ingests_a_valid_local_file(app, reading_payload, tmp_path):
    payload_path = tmp_path / "reading.json"
    payload_path.write_text(
        json.dumps(reading_payload(packet_sequence=99)),
        encoding="utf-8",
    )

    result = app.test_cli_runner().invoke(
        args=["ingest-reading", "--file", str(payload_path)]
    )

    assert result.exit_code == 0, result.output
    assert "Stored reading" in result.output
    assert stored_count(app) == 1


def test_cli_accepts_windows_utf8_bom(app, reading_payload, tmp_path):
    payload_path = tmp_path / "bom-reading.json"
    payload_path.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps(reading_payload(packet_sequence=100)).encode("utf-8")
    )

    result = app.test_cli_runner().invoke(
        args=["ingest-reading", "--file", str(payload_path)]
    )

    assert result.exit_code == 0, result.output
    assert stored_count(app) == 1


def test_cli_rejects_invalid_payload_without_writing(
    app, reading_payload, tmp_path
):
    payload_path = tmp_path / "invalid.json"
    payload_path.write_text(
        json.dumps(reading_payload(ph=15.0)),
        encoding="utf-8",
    )

    result = app.test_cli_runner().invoke(
        args=["ingest-reading", "--file", str(payload_path)]
    )

    assert result.exit_code != 0
    assert "Invalid reading payload" in result.output
    assert "Traceback" not in result.output
    assert stored_count(app) == 0


def test_cli_rejects_malformed_json(app, tmp_path):
    payload_path = tmp_path / "malformed.json"
    payload_path.write_text("{not json", encoding="utf-8")

    result = app.test_cli_runner().invoke(
        args=["ingest-reading", "--file", str(payload_path)]
    )

    assert result.exit_code != 0
    assert "not valid JSON" in result.output
    assert stored_count(app) == 0


def test_cli_reports_duplicate_packet(app, reading_payload, tmp_path):
    payload_path = tmp_path / "duplicate.json"
    payload_path.write_text(
        json.dumps(reading_payload(packet_sequence=7)),
        encoding="utf-8",
    )

    runner = app.test_cli_runner()
    first = runner.invoke(args=["ingest-reading", "--file", str(payload_path)])
    second = runner.invoke(args=["ingest-reading", "--file", str(payload_path)])

    assert first.exit_code == 0, first.output
    assert second.exit_code != 0
    assert "already exists" in second.output
    assert stored_count(app) == 1


def test_a_fresh_receipt_can_accompany_an_older_recorded_timestamp(
    app, reading_payload
):
    payload = reading_payload(
        recorded_at="2026-10-20T10:00:00Z",
        packet_sequence=12,
    )

    with app.app_context():
        reading = IngestionService().ingest(
            payload,
            received_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
        assert reading.id is not None

    latest = app.test_client().get("/api/readings/latest").get_json()["data"]
    assert latest["state"] == "ok"
    assert latest["receiver"]["status"] == "RECENT_DATA"
