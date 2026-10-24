"""API route, schema, and empty-state tests."""

from __future__ import annotations

from datetime import datetime

import pytest

ENVELOPE_KEYS = {"ok", "data", "error", "timestamp"}


def assert_success_envelope(response):
    data = response.get_json()
    assert data is not None
    assert set(data) == ENVELOPE_KEYS
    assert data["ok"] is True
    assert data["error"] is None
    assert isinstance(data["timestamp"], str)
    assert data["timestamp"].endswith("Z")
    datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
    return data


def test_health_reports_application_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.mimetype == "application/json"

    body = assert_success_envelope(response)
    data = body["data"]

    assert data["status"] == "ok"
    assert data["service"] == "aquasense"
    assert data["version"] == "0.2.0"
    assert isinstance(data["uptime_seconds"], (int, float))
    assert data["uptime_seconds"] >= 0
    assert data["data_source"] == {
        "configured": False,
        "receiver_status": "NOT_CONNECTED",
    }


def test_latest_reading_reports_explicit_no_data_state(client):
    response = client.get("/api/readings/latest")

    assert response.status_code == 200
    assert response.mimetype == "application/json"

    data = assert_success_envelope(response)["data"]

    assert data["available"] is False
    assert data["state"] == "no_data"
    assert data["readings"] == {
        "ph": None,
        "tds_ppm": None,
        "temperature_c": None,
    }
    assert data["units"] == {
        "ph": "pH",
        "tds_ppm": "ppm",
        "temperature_c": "°C",
    }
    assert data["receiver"] == {
        "status": "NOT_CONNECTED",
        "label": "NOT CONNECTED",
        "transport_configured": False,
    }
    assert data["recorded_at"] is None
    assert data["received_at"] is None
    assert data["source"] is None
    assert data["packet_sequence"] is None
    assert "No readings have been received" in data["message"]


def test_latest_reading_schema_keys_are_stable(client):
    data = client.get("/api/readings/latest").get_json()["data"]

    assert set(data) == {
        "available",
        "state",
        "message",
        "readings",
        "units",
        "receiver",
        "recorded_at",
        "received_at",
        "source",
        "packet_sequence",
    }
    assert set(data["readings"]) == {"ph", "tds_ppm", "temperature_c"}
    assert set(data["receiver"]) == {
        "status",
        "label",
        "transport_configured",
    }


def test_waiting_state_when_transport_is_configured_without_data(app_factory):
    app = app_factory(DATA_SOURCE_CONFIGURED=True)
    client = app.test_client()

    data = client.get("/api/readings/latest").get_json()["data"]

    assert data["available"] is False
    assert data["readings"] == {
        "ph": None,
        "tds_ppm": None,
        "temperature_c": None,
    }
    assert data["receiver"] == {
        "status": "WAITING_FOR_DATA",
        "label": "WAITING FOR DATA",
        "transport_configured": True,
    }

    health = client.get("/api/health").get_json()["data"]
    assert health["data_source"] == {
        "configured": True,
        "receiver_status": "WAITING_FOR_DATA",
    }


def test_api_responses_disable_caching(client):
    for path in ("/api/health", "/api/readings/latest", "/api/readings/history"):
        response = client.get(path)
        assert response.headers["Cache-Control"] == "no-store"


def test_unknown_api_route_returns_json_error(client):
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.mimetype == "application/json"

    body = response.get_json()
    assert set(body) == ENVELOPE_KEYS
    assert body["ok"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "not_found"
    assert "Traceback" not in response.get_data(as_text=True)


def test_disallowed_api_method_returns_json_error(client):
    response = client.post("/api/health")

    assert response.status_code == 405
    assert response.mimetype == "application/json"

    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize(
    "path",
    ["/api/health", "/api/readings/latest", "/api/readings/history"],
)
def test_api_does_not_expose_internal_paths(client, path):
    text = client.get(path).get_data(as_text=True)

    assert "Traceback" not in text
    assert "C:\\" not in text
    assert "site-packages" not in text
