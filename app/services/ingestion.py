"""Validation and persistence for structured AquaSense readings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..extensions import db
from ..models import Reading
from ..time_utils import ensure_utc, parse_utc_timestamp, utc_now

SENSOR_KEYS = ("ph", "tds_ppm", "temperature_c")
_ALLOWED_FIELDS = set(SENSOR_KEYS) | {"recorded_at", "source", "packet_sequence"}

# pH is constrained to the measurement range of the SEN0169 sensor. The
# temperature range matches the DS18B20 sensor's supported range. TDS has no
# invented upper limit; it only has to be finite and non-negative.
PH_MIN = 0.0
PH_MAX = 14.0
TEMPERATURE_MIN_C = -55.0
TEMPERATURE_MAX_C = 125.0
MAX_SOURCE_LENGTH = 64
MAX_PACKET_SEQUENCE = 9_223_372_036_854_775_807


class ReadingValidationError(ValueError):
    """Raised when a candidate reading fails validation."""

    def __init__(self, errors: Mapping[str, str]) -> None:
        self.errors = dict(errors)
        details = "; ".join(
            f"{field}: {message}" for field, message in self.errors.items()
        )
        super().__init__(f"Reading payload is invalid: {details}")


class DuplicateReadingError(Exception):
    """Raised when a source supplies a packet sequence already stored."""

    def __init__(self, source: str, packet_sequence: int) -> None:
        self.source = source
        self.packet_sequence = packet_sequence
        super().__init__(
            f"A reading from source {source!r} with packet_sequence "
            f"{packet_sequence} already exists."
        )


@dataclass(frozen=True)
class ValidatedReading:
    """Normalized values ready for persistence."""

    ph: float | None
    tds_ppm: float | None
    temperature_c: float | None
    recorded_at: datetime
    source: str
    packet_sequence: int | None


def validate_reading_payload(payload: object) -> ValidatedReading:
    """Validate one structured reading without inventing missing values."""
    if not isinstance(payload, Mapping):
        raise ReadingValidationError({"payload": "must be a JSON object"})

    errors: dict[str, str] = {}
    unknown_fields = sorted(set(payload) - _ALLOWED_FIELDS)
    if unknown_fields:
        errors["fields"] = (
            "unsupported field(s): " + ", ".join(str(field) for field in unknown_fields)
        )

    measurements: dict[str, float | None] = {}
    for key in SENSOR_KEYS:
        raw_value = payload.get(key)
        if raw_value is None:
            measurements[key] = None
            continue

        try:
            value = _finite_number(raw_value)
        except ValueError as exc:
            errors[key] = str(exc)
            measurements[key] = None
            continue

        range_error = _measurement_range_error(key, value)
        if range_error:
            errors[key] = range_error
        measurements[key] = value

    if all(value is None for value in measurements.values()):
        errors["readings"] = "at least one sensor measurement is required"

    source = ""
    raw_source = payload.get("source")
    if "source" not in payload or raw_source is None:
        errors["source"] = "is required"
    elif not isinstance(raw_source, str):
        errors["source"] = "must be a string"
    else:
        source = raw_source.strip()
        if not source:
            errors["source"] = "must not be empty"
        elif len(source) > MAX_SOURCE_LENGTH:
            errors["source"] = f"must be at most {MAX_SOURCE_LENGTH} characters"
        elif any(ord(character) < 32 or ord(character) == 127 for character in source):
            errors["source"] = "must not contain control characters"

    recorded_at: datetime | None = None
    if "recorded_at" not in payload or payload.get("recorded_at") is None:
        errors["recorded_at"] = "is required"
    else:
        try:
            recorded_at = parse_utc_timestamp(payload.get("recorded_at"))
        except (TypeError, ValueError) as exc:
            errors["recorded_at"] = str(exc)

    packet_sequence: int | None = None
    raw_sequence = payload.get("packet_sequence")
    if raw_sequence is not None:
        if isinstance(raw_sequence, bool) or not isinstance(raw_sequence, int):
            errors["packet_sequence"] = "must be a non-negative integer or null"
        elif raw_sequence < 0:
            errors["packet_sequence"] = "must be zero or greater"
        elif raw_sequence > MAX_PACKET_SEQUENCE:
            errors["packet_sequence"] = "is too large for a signed 64-bit integer"
        else:
            packet_sequence = raw_sequence

    if errors:
        raise ReadingValidationError(errors)

    # These assertions are defensive: every failure path above records an error.
    assert recorded_at is not None
    return ValidatedReading(
        ph=measurements["ph"],
        tds_ppm=measurements["tds_ppm"],
        temperature_c=measurements["temperature_c"],
        recorded_at=recorded_at,
        source=source,
        packet_sequence=packet_sequence,
    )


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a finite number or null")

    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("must be a finite number or null") from exc

    if not math.isfinite(number):
        raise ValueError("must be a finite number; NaN and infinity are rejected")

    return number


def _measurement_range_error(key: str, value: float) -> str | None:
    if key == "ph" and not PH_MIN <= value <= PH_MAX:
        return f"must be between {PH_MIN:g} and {PH_MAX:g} pH units"
    if key == "temperature_c" and not TEMPERATURE_MIN_C <= value <= TEMPERATURE_MAX_C:
        return (
            f"must be between {TEMPERATURE_MIN_C:g} and "
            f"{TEMPERATURE_MAX_C:g} °C"
        )
    if key == "tds_ppm" and value < 0:
        return "must be zero or greater; no upper limit is assumed"
    return None


class IngestionService:
    """Validate and persist readings supplied by an internal caller.

    This service is intentionally not connected to a public HTTP route. A
    future receiver transport can call it after authentication and transport
    details are agreed.
    """

    def ingest(
        self,
        payload: object,
        *,
        received_at: datetime | None = None,
    ) -> Reading:
        """Validate, persist, and return a reading.

        ``received_at`` is server receipt metadata. It is not accepted from the
        payload. Tests may pass it to create deterministic freshness scenarios.
        """
        validated = validate_reading_payload(payload)
        receipt_time = utc_now() if received_at is None else ensure_utc(received_at)

        if validated.packet_sequence is not None:
            duplicate_exists = db.session.scalar(
                select(Reading.id)
                .where(
                    Reading.source == validated.source,
                    Reading.packet_sequence == validated.packet_sequence,
                )
                .limit(1)
            )
            if duplicate_exists is not None:
                raise DuplicateReadingError(
                    validated.source, validated.packet_sequence
                )

        reading = Reading(
            ph=validated.ph,
            tds_ppm=validated.tds_ppm,
            temperature_c=validated.temperature_c,
            recorded_at=validated.recorded_at,
            received_at=receipt_time,
            source=validated.source,
            packet_sequence=validated.packet_sequence,
        )
        db.session.add(reading)

        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            if validated.packet_sequence is not None:
                duplicate_exists = db.session.scalar(
                    select(Reading.id)
                    .where(
                        Reading.source == validated.source,
                        Reading.packet_sequence == validated.packet_sequence,
                    )
                    .limit(1)
                )
                if duplicate_exists is not None:
                    raise DuplicateReadingError(
                        validated.source, validated.packet_sequence
                    ) from exc
            raise
        except SQLAlchemyError:
            db.session.rollback()
            raise

        db.session.refresh(reading)
        return reading
