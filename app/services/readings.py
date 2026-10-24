"""Read-side services for persisted AquaSense readings.

The dashboard and API only expose rows that were validated and persisted by
:mod:`app.services.ingestion`. This module never synthesizes, interpolates, or
estimates a measurement.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select

from ..extensions import db
from ..models import Reading
from ..time_utils import ensure_utc, to_utc_iso, utc_now

NOT_CONNECTED = "NOT_CONNECTED"
WAITING_FOR_DATA = "WAITING_FOR_DATA"
RECENT_DATA = "RECENT_DATA"
STALE_DATA = "STALE_DATA"

_STATUS_LABELS = {
    NOT_CONNECTED: "NOT CONNECTED",
    WAITING_FOR_DATA: "WAITING FOR DATA",
    RECENT_DATA: "RECENT DATA",
    STALE_DATA: "STALE DATA",
}

_UNITS = {
    "ph": "pH",
    "tds_ppm": "ppm",
    "temperature_c": "°C",
}

DEFAULT_STALE_AFTER_SECONDS = 300
MAX_HISTORY_LIMIT = 100


class ReadingDataError(RuntimeError):
    """Raised when a persisted row cannot be represented safely."""


class ReadingService:
    """Expose persisted readings and their freshness.

    ``source_configured`` describes transport configuration only. It does not
    claim that hardware is online. Once rows exist, the receiver status is
    derived from the age of the most recent row's server receipt time.
    """

    def __init__(
        self,
        source_configured: bool = False,
        stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        self._source_configured = bool(source_configured)
        self._stale_after_seconds = int(stale_after_seconds)

    @property
    def source_configured(self) -> bool:
        return self._source_configured

    @property
    def stale_after_seconds(self) -> int:
        return self._stale_after_seconds

    @property
    def receiver_status(self) -> str:
        """Return the no-data transport state used by the health endpoint."""
        return WAITING_FOR_DATA if self._source_configured else NOT_CONNECTED

    @property
    def receiver_label(self) -> str:
        return _STATUS_LABELS[self.receiver_status]

    def latest_payload(self) -> dict[str, object]:
        """Return the latest persisted reading or an explicit no-data state."""
        latest = db.session.scalar(
            select(Reading)
            .order_by(Reading.recorded_at.desc(), Reading.id.desc())
            .limit(1)
        )
        if latest is None:
            return self._no_data_payload()

        readings = {
            "ph": _safe_measurement(latest.ph, "ph"),
            "tds_ppm": _safe_measurement(latest.tds_ppm, "tds_ppm"),
            "temperature_c": _safe_measurement(
                latest.temperature_c, "temperature_c"
            ),
        }
        if all(value is None for value in readings.values()):
            raise ReadingDataError("The latest persisted reading has no measurements.")

        received_at = ensure_utc(latest.received_at)
        age_seconds = max(0, int((utc_now() - received_at).total_seconds()))
        is_stale = age_seconds > self._stale_after_seconds
        status = STALE_DATA if is_stale else RECENT_DATA
        state = "stale" if is_stale else "ok"

        if is_stale:
            message = (
                "Latest reading is stale: no new reading has been received within "
                f"the {self._stale_after_seconds}-second freshness threshold."
            )
        else:
            message = "Latest reading was received within the freshness threshold."

        return {
            "available": True,
            "state": state,
            "message": message,
            "readings": readings,
            "units": dict(_UNITS),
            "receiver": {
                "status": status,
                "label": _STATUS_LABELS[status],
                "transport_configured": self._source_configured,
            },
            "recorded_at": to_utc_iso(latest.recorded_at),
            "received_at": to_utc_iso(received_at),
            "source": latest.source,
            "packet_sequence": latest.packet_sequence,
        }

    def history_payload(self, *, limit: int, offset: int) -> dict[str, object]:
        """Return one bounded page of persisted readings, newest first."""
        rows = list(
            db.session.scalars(
                select(Reading)
                .order_by(Reading.recorded_at.desc(), Reading.id.desc())
                .offset(offset)
                .limit(limit + 1)
            ).all()
        )
        has_more = len(rows) > limit
        page = rows[:limit]

        return {
            "items": [self._history_item(reading) for reading in page],
            "units": dict(_UNITS),
            "pagination": {
                "limit": limit,
                "offset": offset,
                "count": len(page),
                "has_more": has_more,
                "next_offset": offset + limit if has_more else None,
            },
        }

    def _no_data_payload(self) -> dict[str, object]:
        if self._source_configured:
            message = (
                "No readings have been received yet. The receiver transport is "
                "configured but no valid sample has been stored."
            )
        else:
            message = (
                "No readings have been received. No receiver transport is "
                "configured and the local database is empty."
            )

        status = self.receiver_status
        return {
            "available": False,
            "state": "no_data",
            "message": message,
            "readings": {
                "ph": None,
                "tds_ppm": None,
                "temperature_c": None,
            },
            "units": dict(_UNITS),
            "receiver": {
                "status": status,
                "label": _STATUS_LABELS[status],
                "transport_configured": self._source_configured,
            },
            "recorded_at": None,
            "received_at": None,
            "source": None,
            "packet_sequence": None,
        }

    def _history_item(self, reading: Reading) -> dict[str, Any]:
        return {
            "id": reading.id,
            "readings": {
                "ph": _safe_measurement(reading.ph, "ph"),
                "tds_ppm": _safe_measurement(reading.tds_ppm, "tds_ppm"),
                "temperature_c": _safe_measurement(
                    reading.temperature_c, "temperature_c"
                ),
            },
            "recorded_at": to_utc_iso(reading.recorded_at),
            "received_at": to_utc_iso(reading.received_at),
            "source": reading.source,
            "packet_sequence": reading.packet_sequence,
        }


def _safe_measurement(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReadingDataError(f"Persisted {name} is not numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise ReadingDataError(f"Persisted {name} is not finite.")
    return number
