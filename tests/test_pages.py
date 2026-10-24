"""Dashboard page and error-page tests."""

from __future__ import annotations

import re


def test_dashboard_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.mimetype == "text/html"

    html = response.get_data(as_text=True)
    assert "AquaSense" in html
    assert "Water quality overview" in html
    assert "NOT CONNECTED" in html
    assert "Awaiting receiver integration" in html
    assert "No trend data yet" in html
    assert "No readings received yet" in html
    assert "It does not certify water as safe to drink." in html


def test_dashboard_sensor_cards_render_empty_values(client):
    html = client.get("/").get_data(as_text=True)

    placeholders = re.findall(
        r'data-sensor-value="([^"]+)">—</output>',
        html,
    )

    assert placeholders == ["ph", "tds_ppm", "temperature_c"]
    assert html.count('class="status-chip"') == 3


def test_dashboard_does_not_render_numeric_sensor_values(client):
    html = client.get("/").get_data(as_text=True)

    # The only sensor values the page may render in Phase 1 are empty markers.
    for key in ("ph", "tds_ppm", "temperature_c"):
        assert re.search(
            rf'data-sensor-value="{key}">\s*—\s*</output>',
            html,
        )

    assert "Demo mode" not in html


def test_dashboard_disables_caching(client):
    response = client.get("/")

    assert response.headers["Cache-Control"] == "no-store"


def test_security_headers_are_present(client):
    response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_static_assets_have_browser_safe_mime_types(client):
    javascript = client.get("/static/js/dashboard.js")
    stylesheet = client.get("/static/css/dashboard.css")

    assert javascript.status_code == 200
    assert javascript.mimetype in {"text/javascript", "application/javascript"}

    assert stylesheet.status_code == 200
    assert stylesheet.mimetype == "text/css"


def test_unknown_page_returns_html_error(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.mimetype == "text/html"

    html = response.get_data(as_text=True)
    assert "Page not found" in html
    assert "Back to dashboard" in html
    assert "Traceback" not in html
