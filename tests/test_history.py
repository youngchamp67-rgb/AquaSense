"""History pagination, freshness, and database-error tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.extensions import db
from app.services.ingestion import IngestionService


ENVELOPE_KEYS = {"ok", "data", "error", "timestamp"}
UNITS = {
    "ph": "pH",
    "tds_ppm": "ppm",
    "temperature_c": "°C",
}


def test_empty_history_is_a_successful_empty_page(client):
    response = client.get("/api/readings/history")

    assert response.status_code == 200
    assert response.mimetype == "application/json"

    body = response.get_json()
    assert set(body) == ENVELOPE_KEYS
    assert body["ok"] is True
    assert body["error"] is None
    assert body["data"]["items"] == []
    assert body["data"]["units"] == UNITS
    assert body["data"]["pagination"] == {
        "limit": 20,
        "offset": 0,
        "count": 0,
        "has_more": False,
        "next_offset": None,
    }


def test_history_returns_persisted_metadata_and_nulls(
    client, app, reading_payload, store_reading
):
    store_reading(
        reading_payload(
            source="source-a",
            packet_sequence=11,
            recorded_at="2026-10-24T12:00:00Z",
        )
    )

    partial = reading_payload(
        source="source-b",
        packet_sequence=12,
        recorded_at="2026-10-24T12:01:00Z",
        ph=None,
        tds_ppm=250.0,
        temperature_c=None,
    )
    store_reading(partial)

    data = client.get("/api/readings/history").get_json()["data"]
    items = data["items"]

    assert data["units"] == UNITS
    assert [item["source"] for item in items] == ["source-b", "source-a"]
    assert items[0]["packet_sequence"] == 12
    assert items[0]["readings"] == {
        "ph": None,
        "tds_ppm": 250.0,
        "temperature_c": None,
    }
    assert items[1]["readings"] == {
        "ph": 7.25,
        "tds_ppm": 321.0,
        "temperature_c": 21.5,
    }
    assert items[0]["recorded_at"] == "2026-10-24T12:01:00Z"
    assert items[0]["received_at"].endswith("Z")
    assert isinstance(items[0]["id"], int)


def test_history_pagination_is_bounded_and_ordered(
    app, client, reading_payload, store_reading
):
    for index in range(5):
        store_reading(
            reading_payload(
                ph=7.0 + index / 10,
                packet_sequence=index + 1,
                recorded_at=f"2026-10-24T12:0{index}:00Z",
            )
        )

    first_page = client.get(
        "/api/readings/history",
        query_string={"limit": 2, "offset": 0},
    ).get_json()["data"]
    assert len(first_page["items"]) == 2
    assert [item["recorded_at"] for item in first_page["items"]] == [
        "2026-10-24T12:04:00Z",
        "2026-10-24T12:03:00Z",
    ]
    assert first_page["pagination"] == {
        "limit": 2,
        "offset": 0,
        "count": 2,
        "has_more": True,
        "next_offset": 2,
    }

    middle_page = client.get(
        "/api/readings/history",
        query_string={"limit": 2, "offset": 2},
    ).get_json()["data"]
    assert [item["recorded_at"] for item in middle_page["items"]] == [
        "2026-10-24T12:02:00Z",
        "2026-10-24T12:01:00Z",
    ]

    last_page = client.get(
        "/api/readings/history",
        query_string={"limit": 2, "offset": 4},
    ).get_json()["data"]
    assert len(last_page["items"]) == 1
    assert last_page["pagination"]["has_more"] is False
    assert last_page["pagination"]["next_offset"] is None


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("limit", "0"),
        ("limit", "101"),
        ("limit", "-1"),
        ("limit", "abc"),
        ("limit", "1.5"),
        ("offset", "-1"),
        ("offset", "abc"),
        ("offset", "1000001"),
    ],
)
def test_history_rejects_invalid_pagination(client, parameter, value):
    response = client.get(
        "/api/readings/history",
        query_string={parameter: value},
    )

    assert response.status_code == 400
    assert response.mimetype == "application/json"

    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_query_parameter"
    assert parameter in body["error"]["message"]


def test_latest_reports_recent_persisted_data(
    app, client, reading_payload, store_reading
):
    store_reading(
        reading_payload(source="receiver-test", packet_sequence=21)
    )
    data = client.get("/api/readings/latest").get_json()["data"]

    assert data["available"] is True
    assert data["state"] == "ok"
    assert data["readings"] == {
        "ph": 7.25,
        "tds_ppm": 321.0,
        "temperature_c": 21.5,
    }
    assert data["source"] == "receiver-test"
    assert data["packet_sequence"] == 21
    assert data["receiver"] == {
        "status": "RECENT_DATA",
        "label": "RECENT DATA",
        "transport_configured": False,
    }
    assert "freshness threshold" in data["message"]
    assert data["recorded_at"] == "2026-10-24T12:00:00Z"


def test_latest_explicitly_reports_stale_data(
    app, client, reading_payload, store_reading
):
    old_receipt = datetime.now(timezone.utc) - timedelta(seconds=600)
    store_reading(
        reading_payload(source="receiver-test", packet_sequence=22),
        received_at=old_receipt,
    )

    data = client.get("/api/readings/latest").get_json()["data"]

    assert data["available"] is True
    assert data["state"] == "stale"
    assert data["receiver"]["status"] == "STALE_DATA"
    assert data["receiver"]["label"] == "STALE DATA"
    assert "stale" in data["message"].lower()
    assert "receiver-test" == data["source"]


def test_staleness_threshold_is_configurable(
    app_factory, reading_payload
):
    app = app_factory(STALE_AFTER_SECONDS=60)
    old_receipt = datetime.now(timezone.utc) - timedelta(seconds=120)

    with app.app_context():
        IngestionService().ingest(
            reading_payload(packet_sequence=31),
            received_at=old_receipt,
        )

    data = app.test_client().get("/api/readings/latest").get_json()["data"]
    assert data["state"] == "stale"
    assert data["receiver"]["status"] == "STALE_DATA"


def test_no_public_ingestion_endpoint_exists(client, reading_payload):
    response = client.post(
        "/api/readings/ingest",
        json=reading_payload(),
    )

    assert response.status_code == 404
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"


def test_read_only_endpoints_reject_write_methods(client):
    response = client.post("/api/readings/latest")

    assert response.status_code == 405
    assert response.get_json()["error"]["code"] == "method_not_allowed"


def test_database_errors_return_generic_json(app, client):
    with app.app_context():
        db.session.execute(text("DROP TABLE readings"))
        db.session.commit()

    for path in ("/api/readings/latest", "/api/readings/history"):
        response = client.get(path)

        assert response.status_code == 500
        assert response.mimetype == "application/json"

        body = response.get_json()
        assert set(body) == ENVELOPE_KEYS
        assert body["ok"] is False
        assert body["data"] is None
        assert body["error"]["code"] == "database_error"
        assert "Traceback" not in response.get_data(as_text=True)
        assert "C:\\" not in response.get_data(as_text=True)
        assert "site-packages" not in response.get_data(as_text=True)
