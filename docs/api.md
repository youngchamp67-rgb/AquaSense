# AquaSense API — Phase 2

Base URL: `http://127.0.0.1:5000`

All API responses use JSON and disable caching (`Cache-Control: no-store`).
Phase 2 is read-only over HTTP. There is no public ingestion endpoint and no
authentication layer yet; keep the server bound to the local machine.

## Response envelope

Every API response, including errors, uses this shape:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "timestamp": "2026-10-24T12:00:00Z"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `ok` | boolean | `true` for successful requests, `false` for errors |
| `data` | object \| null | Endpoint payload on success, `null` on error |
| `error` | object \| null | `{ "code": string, "message": string }` on error, otherwise `null` |
| `timestamp` | string | Server time in ISO 8601 UTC, ending in `Z` |

`Cache-Control: no-store` is set on API responses so receiver status and data
availability are never served from a stale cache.

---

## `GET /api/health`

Reports whether the Flask application is running and whether a receiver
transport is configured. It does **not** claim that the hardware is online.

**Status:** `200 OK` when the application is healthy.

### Data schema

| Field | Type | Description |
| --- | --- | --- |
| `status` | string | `"ok"` when the application is serving requests |
| `service` | string | Always `"aquasense"` |
| `version` | string | Application version (`0.2.0`) |
| `uptime_seconds` | number | Seconds since this application process started |
| `data_source.configured` | boolean | Whether a receiver transport is configured |
| `data_source.receiver_status` | string | Transport state: `NOT_CONNECTED` or `WAITING_FOR_DATA` |

`data_source.receiver_status` describes transport configuration, not the
freshness of persisted rows. Use `/api/readings/latest` for `RECENT_DATA` or
`STALE_DATA`.

### Example

```json
{
  "ok": true,
  "data": {
    "status": "ok",
    "service": "aquasense",
    "version": "0.2.0",
    "uptime_seconds": 12.345,
    "data_source": {
      "configured": false,
      "receiver_status": "NOT_CONNECTED"
    }
  },
  "error": null,
  "timestamp": "2026-10-24T12:00:00Z"
}
```

---

## `GET /api/readings/latest`

Returns the most recent persisted reading, or an explicit no-data state. The
reading is selected by `recorded_at` descending, then database id descending.

**Status:** `200 OK` for both data and no-data results. A no-data result is not
an error.

### Data schema

| Field | Type | Description |
| --- | --- | --- |
| `available` | boolean | `true` when a persisted reading exists, even if some measurements are null |
| `state` | string | `"no_data"`, `"ok"` (fresh), or `"stale"` |
| `message` | string | Human-readable explanation of the current state |
| `readings.ph` | number \| null | pH value in pH units, or `null` when not supplied |
| `readings.tds_ppm` | number \| null | Total dissolved solids in ppm, or `null` when not supplied |
| `readings.temperature_c` | number \| null | Water temperature in °C, or `null` when not supplied |
| `units.ph` | string | Always `"pH"` |
| `units.tds_ppm` | string | Always `"ppm"` |
| `units.temperature_c` | string | Always `"°C"` |
| `receiver.status` | string | `NOT_CONNECTED`, `WAITING_FOR_DATA`, `RECENT_DATA`, or `STALE_DATA` |
| `receiver.label` | string | Display label, for example `"STALE DATA"` |
| `receiver.transport_configured` | boolean | Whether an ingestion transport has been configured |
| `recorded_at` | string \| null | ISO 8601 UTC sensor timestamp, or `null` |
| `received_at` | string \| null | ISO 8601 UTC server receipt timestamp, or `null` |
| `source` | string \| null | Explicit source metadata for the stored row |
| `packet_sequence` | integer \| null | Source-scoped packet identifier, or `null` when none was supplied |

A stored partial reading is valid. Unavailable measurements remain `null`; the
API never substitutes zero or an estimate.

No numeric sensor example is shown because the application does not generate
measurements.

### Freshness

Freshness is based on the server receipt time (`received_at`), not on the sensor
clock. The threshold is configured with `AQUASENSE_STALE_AFTER_SECONDS`
(default `300`):

- `received_at` within the threshold → `state: "ok"` and
  `receiver.status: "RECENT_DATA"`.
- `received_at` older than the threshold → `state: "stale"` and
  `receiver.status: "STALE_DATA"`. The `message` explicitly says the reading is
  stale.
- No persisted rows → `available: false`, `state: "no_data"`, and a receiver
  status of `NOT_CONNECTED` or `WAITING_FOR_DATA`.

`RECENT_DATA` describes recent receipt, not a verified live connection.
`CONNECTED` is reserved for a future transport with an established connection
and is not emitted in Phase 2.

### Receiver status semantics

| Status | Meaning |
| --- | --- |
| `NOT_CONNECTED` | No transport is configured and no persisted reading exists |
| `WAITING_FOR_DATA` | A transport is configured, but no persisted reading exists |
| `RECENT_DATA` | A persisted reading was received within the freshness threshold |
| `STALE_DATA` | A persisted reading exists but is older than the threshold |
| `CONNECTED` | Reserved for a future verified transport; not emitted in Phase 2 |

### No-data example

```json
{
  "ok": true,
  "data": {
    "available": false,
    "state": "no_data",
    "message": "No readings have been received. No receiver transport is configured and the local database is empty.",
    "readings": {
      "ph": null,
      "tds_ppm": null,
      "temperature_c": null
    },
    "units": {
      "ph": "pH",
      "tds_ppm": "ppm",
      "temperature_c": "°C"
    },
    "receiver": {
      "status": "NOT_CONNECTED",
      "label": "NOT CONNECTED",
      "transport_configured": false
    },
    "recorded_at": null,
    "received_at": null,
    "source": null,
    "packet_sequence": null
  },
  "error": null,
  "timestamp": "2026-10-24T12:00:00Z"
}
```

---

## `GET /api/readings/history`

Returns a bounded page of persisted readings, newest first by `recorded_at`,
then id.

### Query parameters

| Parameter | Type | Default | Rules |
| --- | --- | --- | --- |
| `limit` | integer | `20` | `1`–`100` inclusive |
| `offset` | integer | `0` | `0`–`1,000,000` inclusive |

Invalid, negative, fractional, or non-numeric values return HTTP `400` with
`error.code: "invalid_query_parameter"`.

### Response schema

| Field | Type | Description |
| --- | --- | --- |
| `items` | array | Persisted readings, newest first |
| `items[].id` | integer | Database row identifier |
| `items[].readings` | object | `ph`, `tds_ppm`, and `temperature_c`; each number or `null` |
| `items[].recorded_at` | string | ISO 8601 UTC sensor timestamp |
| `items[].received_at` | string | ISO 8601 UTC server receipt timestamp |
| `items[].source` | string | Explicit source metadata |
| `items[].packet_sequence` | integer \| null | Optional source-scoped packet identifier |
| `units` | object | Units for all three measurement keys |
| `pagination.limit` | integer | Applied page size |
| `pagination.offset` | integer | Applied offset |
| `pagination.count` | integer | Number of items in this page |
| `pagination.has_more` | boolean | Whether at least one additional row exists |
| `pagination.next_offset` | integer \| null | Offset for the next page, or `null` |

`count` is the page count, not the total row count. Use `has_more` and
`next_offset` for paging.

### Empty-history example

```json
{
  "ok": true,
  "data": {
    "items": [],
    "units": {
      "ph": "pH",
      "tds_ppm": "ppm",
      "temperature_c": "°C"
    },
    "pagination": {
      "limit": 20,
      "offset": 0,
      "count": 0,
      "has_more": false,
      "next_offset": null
    }
  },
  "error": null,
  "timestamp": "2026-10-24T12:00:00Z"
}
```

---

## Internal ingestion

Phase 2 deliberately exposes **no HTTP ingestion route**. The validated
ingestion service is an internal Python boundary, and the local Flask CLI is the
documented operator interface:

```powershell
.\.venv\Scripts\python.exe -m flask --app run ingest-reading --file .\path\to\reading.json
```

The file must contain one JSON object:

| Field | Type | Rules |
| --- | --- | --- |
| `ph` | number or `null` | Finite; `0`–`14` inclusive (SEN0169 measurement range) |
| `tds_ppm` | number or `null` | Finite; `>= 0`; no universal upper limit is invented |
| `temperature_c` | number or `null` | Finite; `-55`–`125` inclusive (DS18B20 range) |
| `recorded_at` | string | ISO 8601 with an explicit offset or `Z`; normalized to UTC |
| `source` | string | Required, trimmed, 1–64 characters, no control characters |
| `packet_sequence` | integer or `null` | Optional; `0` to `9,223,372,036,854,775,807` |

Rules:

- At least one sensor measurement must be present.
- Unknown fields are rejected.
- Booleans, numeric strings, lists, objects, NaN, and infinity are rejected.
- Naive timestamps are rejected rather than guessing a timezone.
- Omitted or `null` measurements remain missing. They are never replaced with
  zero.
- Duplicate `(source, packet_sequence)` pairs are rejected.
- Packet identifiers are never invented when omitted.
- The server assigns `received_at`; it is not accepted from the payload.
- CLI errors are printed without tracebacks. Database details remain in the
  server log.

The internal service can be called by a future authenticated transport layer:

```python
from app.services.ingestion import IngestionService

reading = IngestionService().ingest(validated_payload)
```

A future hardware-facing HTTP endpoint must not be added without a defined
authentication and transport design.

---

## Error responses

Example — unknown API route:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "not_found",
    "message": "The requested resource was not found."
  },
  "timestamp": "2026-10-24T12:00:00Z"
}
```

| HTTP status | `error.code` | Meaning |
| --- | --- | --- |
| `400` | `bad_request` | Malformed request |
| `400` | `invalid_query_parameter` | Invalid history `limit` or `offset` |
| `404` | `not_found` | Unknown API route, including any attempted ingestion route |
| `405` | `method_not_allowed` | HTTP method not supported by the read-only route |
| `413` | `payload_too_large` | Request body too large |
| `415` | `unsupported_media_type` | Unsupported content type |
| `500` | `database_error` | Database failure; details are logged server-side only |
| `500` | `internal_error` | Unexpected server failure; details are logged server-side only |

Error messages never include tracebacks, internal file paths, or exception
reprs.

---

## Data integrity contract

- Only validated, persisted rows are returned.
- Partial readings preserve unavailable measurements as `null`.
- No simulated, estimated, interpolated, or hardcoded sensor records are
  exposed.
- `GET` endpoints have no side effects.
- Timestamps are sent in UTC with a `Z` suffix.
- Stale data is labelled stale; it is not presented as an active receiver
  connection.
- No endpoint claims that water is safe or unsafe to drink.
