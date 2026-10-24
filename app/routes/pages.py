"""Server-rendered page routes."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def dashboard():
    service = current_app.extensions["readings"]
    return render_template(
        "dashboard.html",
        snapshot=service.latest_payload(),
        poll_interval_seconds=30,
    )
