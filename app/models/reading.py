"""Persisted sensor reading model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db


class Reading(db.Model):
    """One validated reading from an explicitly identified source.

    Sensor columns are nullable because the ingestion contract permits partial
    readings. The validation service requires at least one measurement, but the
    database must not turn an unavailable measurement into zero.
    """

    __tablename__ = "readings"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "packet_sequence",
            name="uq_readings_source_packet_sequence",
        ),
        Index("ix_readings_recorded_at_id", "recorded_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    tds_ppm: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    packet_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:
        return f"<Reading id={self.id} source={self.source!r}>"
