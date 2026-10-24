"""Local command-line tools for AquaSense."""

from __future__ import annotations

import json
from pathlib import Path

import click
from flask import Flask, current_app
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db
from .services.ingestion import (
    DuplicateReadingError,
    IngestionService,
    ReadingValidationError,
)
from .time_utils import to_utc_iso


def register_cli(app: Flask) -> None:
    """Register internal, local-only ingestion commands."""

    @app.cli.command("ingest-reading")
    @click.option(
        "--file",
        "file_path",
        required=True,
        type=click.Path(
            exists=True,
            dir_okay=False,
            readable=True,
            path_type=Path,
        ),
        help="Path to a local JSON reading payload.",
    )
    def ingest_reading(file_path: Path) -> None:
        """Validate and persist one reading from a local JSON file.

        This is an internal operator interface, not a network endpoint. The
        future receiver integration must supply authentication and transport
        design before any HTTP ingestion route is exposed.
        """
        try:
            raw_payload = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise click.ClickException(f"Could not read the payload file: {exc}") from None

        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise click.ClickException(
                f"The payload file is not valid JSON: {exc.msg} "
                f"(line {exc.lineno}, column {exc.colno})."
            ) from None

        try:
            reading = IngestionService().ingest(payload)
        except ReadingValidationError as exc:
            details = "; ".join(
                f"{field}: {message}" for field, message in exc.errors.items()
            )
            raise click.ClickException(f"Invalid reading payload. {details}") from None
        except DuplicateReadingError as exc:
            raise click.ClickException(str(exc)) from None
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception(
                "Database error while ingesting a reading from the CLI"
            )
            raise click.ClickException(
                "The reading could not be saved because of a database error."
            ) from None

        click.echo(
            f"Stored reading {reading.id} from source {reading.source!r}, "
            f"recorded at {to_utc_iso(reading.recorded_at)}."
        )
