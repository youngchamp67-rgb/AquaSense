# AquaSense API — Phase 1

Base URL: `http://127.0.0.1:5000`

All API responses use JSON and disable caching (`Cache-Control: no-store`).
No authentication is implemented in Phase 1; keep the server bound to the local
machine.

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

Reports whether the Flask application is running and whether a receiver data
source is configured. It does **not** claim that the hardware is online.

**Status:** `200 OK` when the application is healthy.

### Data schema

| Field | Type | Description |
| --- | --- | --- |
| `status` | string | `"ok"` when the application is serving requests |
| `service` | string | Always `"aquasense"` |
| `version` | string | Application version |
| `uptime_seconds` | number | Seconds since this application process started |
| `data_source.configured` | boolean | Whether a receiver transport is configured |
| `data_source.receiver_status` | string | `NOT_CONNECTED` or `WAITING_FOR_DATA` in Phase 1 |

### Example

```json
{
  "ok": true,
  "data": {
    "status": "ok",
    "service": "aquasense",
    "version": "0.1.0",
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

Returns the most recent receiver reading, or an explicit no-data state.

**Status:** `200 OK` in both cases. A no-data result is not an error.

### Data schema

| Field | Type | Description |
| --- | --- | --- |
| `available` | boolean | `true` only when a complete, receiver-provided reading exists |
| `state` | string | `"no_data"` in Phase 1; `"ok"` when a reading is available in a future phase |
| `message` | string | Human-readable explanation of the current state |
| `readings.ph` | number \| null | pH value in pH units, `null` when unavailable |
| `readings.tds_ppm` | number \| null | Total dissolved solids in ppm, `null` when unavailable |
| `readings.temperature_c` | number \| null | Water temperature in °C, `null` when unavailable |
| `units.ph` | string | Always `"pH"` |
| `units.tds_ppm` | string | Always `"ppm"` |
| `units.temperature_c` | string | Always `"°C"` |
| `receiver.status` | string | `NOT_CONNECTED`, `WAITING_FOR_DATA`, or (in a future phase) `CONNECTED` |
| `receiver.label` | string | Display label, for example `"NOT CONNECTED"` |
| `receiver.transport_configured` | boolean | Whether an ingestion transport has been set up |
| `recorded_at` | string \| null | ISO 8601 UTC sensor timestamp, or `null` |
| `received_at` | string \| null | ISO 8601 UTC server receipt timestamp, or `null` |

### Phase 1 no-data example

```json
{
  "ok": true,
  "data": {
    "available": false,
    "state": "no_data",
    "message": "No readings have been received. Receiver integration is not configured in Phase 1.",
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
    "received_at": null
  },
  "error": null,
  "timestamp": "2026-10-24T12:00:00Z"
}
```

### Future available state

When real receiver integration exists, a complete reading sets `available` to
`true`, `state` to `"ok"`, provides all three numeric readings, and supplies
`recorded_at` and `received_at` timestamps. No numeric sensor example is shown
here because Phase 1 does not generate measurements.

Partial or invalid readings must be rejected by the future ingestion layer;
missing values must never be filled with estimates.

### Receiver status semantics

| Status | Meaning |
| --- | --- |
| `NOT_CONNECTED` | No receiver transport is configured |
| `WAITING_FOR_DATA` | A transport is configured, but no valid reading has arrived |
| `CONNECTED` | Reserved for a future phase with an established transport |

Neither `NOT_CONNECTED` nor `WAITING_FOR_DATA` implies the ESP32 hardware is
online.

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
| `404` | `not_found` | Unknown API route |
| `405` | `method_not_allowed` | HTTP method not supported by the route |
| `413` | `payload_too_large` | Request body too large |
| `415` | `unsupported_media_type` | Unsupported content type |
| `500` | `internal_error` | Unexpected server failure; details are logged server-side only |

Error messages never include tracebacks, internal file paths, or exception
reprs.

---

## Data integrity contract

- Phase 1 always returns `available: false` and null readings.
- No simulated, estimated, or historical sensor records are exposed.
- `GET /api/readings/latest` has no side effects.
- Timestamps are sent in UTC with a `Z` suffix.
