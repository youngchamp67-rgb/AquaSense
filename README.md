# AquaSense — Phase 2 Flask Dashboard and SQLite Foundation

AquaSense is a local water-quality monitoring dashboard for an existing
ESP32 + LoRa sensing project. Phase 2 adds validated SQLite persistence, a
bounded history API, freshness reporting, and a local ingestion command ready
for a future receiver transport.

**There is still no receiver transport.** No ESP32 firmware, serial port, HTTP
receiver, or LoRa packet format is assumed. Measurements are only stored when a
validated payload is submitted through the application's internal service or
local CLI. The dashboard never generates, simulates, or estimates readings.

## What is included

| Area | Status |
| --- | --- |
| Dashboard at `/` | Responsive dark UI with latest readings, partial-value handling, stale-data warning, real history chart lanes, and recent-readings table |
| `GET /api/health` | Application health, version, uptime, and transport configuration state |
| `GET /api/readings/latest` | Latest persisted reading, partial values, source metadata, and explicit fresh/stale/no-data states |
| `GET /api/readings/history` | Bounded newest-first history with `limit` and `offset` |
| Ingestion | Validated internal service plus a local `flask ingest-reading` CLI command |
| Public write endpoint | Deliberately not implemented |
| Database | Local SQLite via Flask-SQLAlchemy; database file ignored by git |
| Demo mode | Not implemented and not enabled |
| Hardware firmware | Untouched |

The full API contract is in [docs/api.md](docs/api.md).

## Data integrity and safety

- Only validated, persisted rows are displayed.
- Missing measurements remain `NULL` / `—`; they are never replaced with zero.
- NaN, infinity, booleans, strings, and malformed payloads are rejected.
- Timestamps must include a timezone and are normalized to UTC.
- pH and temperature are validated against documented sensor ranges.
- TDS has no invented universal upper limit. It must be finite and non-negative.
- Duplicate `(source, packet_sequence)` pairs are rejected. Packet identifiers
  are never generated for payloads that omit them.
- A reading older than the freshness threshold is labelled **STALE DATA**; it is
  not presented as proof that the receiver is currently connected.
- The dashboard does not describe water as safe or unsafe to drink. These three
  sensors cannot establish potability.

## Preserved hardware

No firmware, wiring, sensor library, or radio configuration is changed by this
project.

- **Sender ESP32:** SEN0169 pH sensor, Gravity TDS sensor, DS18B20 temperature
  sensor, OLED display, RA-02 LoRa module.
- **Receiver ESP32:** RA-02 LoRa module and OLED display.

The transport, packet format, serial settings, and authentication design remain
undefined until receiver integration is approved.

## Project structure

```text
aqua-sense-monitor/
├── app/
│   ├── __init__.py            # Flask factory, configuration, schema startup
│   ├── cli.py                 # Local validated ingestion command
│   ├── errors.py              # HTML, JSON, and database error handlers
│   ├── extensions.py          # SQLAlchemy extension
│   ├── models/
│   │   └── reading.py         # Persisted reading model
│   ├── responses.py           # Consistent JSON envelope
│   ├── security.py            # CSP, cache, and security headers
│   ├── time_utils.py          # UTC parsing and formatting
│   ├── routes/
│   │   ├── api.py             # /api/health, latest, history
│   │   └── pages.py           # Dashboard page
│   ├── services/
│   │   ├── ingestion.py       # Validation and persistence
│   │   └── readings.py        # Read models, freshness, serialization
│   ├── static/
│   │   ├── css/dashboard.css
│   │   ├── img/favicon.svg
│   │   └── js/dashboard.js
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       └── error.html
├── docs/api.md
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_history.py
│   ├── test_ingestion.py
│   └── test_pages.py
├── .gitignore
├── pytest.ini
├── requirements.txt
├── requirements-dev.txt
├── run.py
└── README.md
```

## Requirements

- Windows 10 or 11 with PowerShell
- Python 3.10 or newer (tested with Python 3.12.7)
- A modern browser

Node.js is **not** required. The frontend is plain HTML, CSS, and vanilla
JavaScript.

## Windows PowerShell setup

From the project directory:

```powershell
cd "C:\Users\TARUN\Documents\PROJECTS_ONGOING\aqua-sense-monitor"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

If PowerShell blocks virtual-environment activation, allow it for the current
terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

`requirements-dev.txt` includes Flask, Flask-SQLAlchemy, and pytest. For a
runtime-only install, use `python -m pip install -r requirements.txt`.

## Run the application

```powershell
python run.py
```

Then open:

```text
http://127.0.0.1:5000
```

Stop the server with `Ctrl+C`.

The server binds to `127.0.0.1` by default, so it is not exposed to the local
network. Debug mode is off unless explicitly enabled.

The SQLite tables are created automatically on startup. No separate database
initialization command is required for a fresh checkout.

## Database configuration

The default database is:

```text
instance/aquasense.sqlite3
```

The `instance/` directory and SQLite files are ignored by git. Override the path
when needed:

```powershell
$env:AQUASENSE_DATABASE_URL = "sqlite:///C:/Users/TARUN/AppData/Local/aquasense/aquasense.sqlite3"
python run.py
```

Use an absolute SQLite URL with forward slashes on Windows. Database files must
not be committed and the database must not contain secrets.

Phase 2 creates missing tables but does not run schema migrations. Back up or
remove a development database before changing the model during a future phase.

### Optional environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AQUASENSE_HOST` | `127.0.0.1` | Bind address |
| `AQUASENSE_PORT` | `5000` | HTTP port |
| `AQUASENSE_DEBUG` | unset (off) | Set to `1` for the Flask debugger — local development only |
| `AQUASENSE_SECRET_KEY` | ephemeral random value | Optional stable Flask secret; keep real values out of source control |
| `AQUASENSE_DATABASE_URL` | `instance/aquasense.sqlite3` | SQLAlchemy database URL |
| `AQUASENSE_STALE_AFTER_SECONDS` | `300` | Age in seconds after which the latest reading is reported as stale |

Example:

```powershell
$env:AQUASENSE_PORT = "5001"
$env:AQUASENSE_STALE_AFTER_SECONDS = "600"
python run.py
```

Do not enable debug mode on an untrusted network. No secrets belong in the
repository.

## Internal reading ingestion

There is intentionally **no public HTTP ingestion endpoint**. A future receiver
transport must first define authentication, transport, and packet handling.

For local validation and persistence, write a JSON payload to a local file and
run:

```powershell
.\.venv\Scripts\python.exe -m flask --app run ingest-reading --file .\path\to\reading.json
```

The payload must be a JSON object containing:

| Field | Type | Rules |
| --- | --- | --- |
| `ph` | number or `null` | Finite; 0–14 (SEN0169 range) |
| `tds_ppm` | number or `null` | Finite; zero or greater; no upper limit is assumed |
| `temperature_c` | number or `null` | Finite; −55–125 °C (DS18B20 range) |
| `recorded_at` | string | ISO 8601 with an explicit offset or `Z`; stored in UTC |
| `source` | string | Required, 1–64 characters, no control characters |
| `packet_sequence` | integer or `null` | Optional non-negative signed 64-bit integer |

At least one of the three sensor fields must contain a number. Unknown fields
are rejected. Omitting a sensor field or setting it to `null` preserves it as
missing. A repeated `source` + `packet_sequence` pair is rejected.

The command reports success or a validation/duplicate/database error without
exposing a traceback. It writes only to the configured local database.

## API summary

All API responses use a consistent envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "timestamp": "2026-10-24T12:00:00Z"
}
```

- `GET /api/health` — application health. HTTP `200`.
- `GET /api/readings/latest` — latest persisted reading or explicit no-data state. HTTP `200`.
- `GET /api/readings/history?limit=20&offset=0` — bounded persisted history. HTTP `200`.
- Invalid history pagination — HTTP `400` with `invalid_query_parameter`.
- Unknown API route — HTTP `404` with a JSON error envelope.
- Unsupported method — HTTP `405` with a JSON error envelope.
- Database failure — HTTP `500` with a generic `database_error` envelope.
- Unexpected failure — HTTP `500` with a generic JSON error.

`available: false` is a valid, successful no-data response — not an error. A
partial stored reading returns `available: true` with `null` for measurements
that were not supplied.

The latest-reading receiver status is one of:

| Status | Meaning |
| --- | --- |
| `NOT_CONNECTED` | No transport is configured and no reading exists |
| `WAITING_FOR_DATA` | A transport is configured but no reading exists |
| `RECENT_DATA` | A persisted reading arrived within the freshness threshold |
| `STALE_DATA` | A persisted reading exists but is older than the threshold |
| `CONNECTED` | Reserved for a future verified transport; not emitted in Phase 2 |

Freshness is based on the server receipt timestamp (`received_at`), not on the
sensor clock. The receiver status does not prove that hardware is online.

Quick PowerShell checks while the server is running:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health | ConvertTo-Json -Depth 5
Invoke-RestMethod http://127.0.0.1:5000/api/readings/latest | ConvertTo-Json -Depth 5
Invoke-RestMethod "http://127.0.0.1:5000/api/readings/history?limit=10&offset=0" | ConvertTo-Json -Depth 5
```

## Run the tests

```powershell
python -m pytest -q
```

Every test app uses a separate temporary SQLite file. Tests never insert
records into `instance/aquasense.sqlite3` or another development database.

The suite covers:

- dashboard rendering, empty states, MIME types, cache, and security headers
- valid and partial persistence
- missing and malformed values, booleans, NaN, and infinity
- pH, TDS, and temperature validation boundaries
- invalid and naive timestamps, plus UTC normalization
- source validation and optional packet sequences
- duplicate packet identifiers and source-scoped uniqueness
- empty history, bounded pagination, ordering, and invalid query parameters
- recent and stale latest-reading states
- database failures returning generic JSON errors
- local CLI ingestion success, validation failure, malformed JSON, and duplicates
- absence of a public ingestion endpoint
- no traceback or internal-path leakage

## Current limitations

- No receiver transport, serial bridge, authenticated HTTP endpoint, or LoRa
  packet parser exists.
- No authentication is implemented. Keep the app bound to `127.0.0.1` or a
  trusted local network.
- No migration framework is configured yet.
- The trend lanes use independent vertical scales so pH, TDS, and temperature
  are not visually compared on a shared axis.
- Automated tests cover server routes and persistence behavior; browser
  interactions are verified manually rather than with headless CI.
- The app is a monitoring tool, not a potability certification system.

## Next phase

Receiver integration remains intentionally deferred. Before implementing it,
the transport (serial, Wi-Fi, or LoRa gateway), packet format, authentication,
validation ranges, timestamp source, retry behavior, and failure handling must
be agreed. The validated ingestion service and persistence model can then be
connected without weakening the no-fabrication guarantees.

## Troubleshooting

**`python` is not recognized**

Use the Windows launcher:

```powershell
py run.py
```

**Port 5000 is already in use**

Choose another port:

```powershell
$env:AQUASENSE_PORT = "5001"
python run.py
```

**Virtual-environment activation is blocked**

Run the process-scoped execution-policy command shown in the setup section, or
invoke the environment directly:

```powershell
.\.venv\Scripts\python.exe run.py
```

**The dashboard shows an error banner**

Confirm the Flask process is still running, then press **Retry**. The banner is
the intended error state when the API cannot be reached; no stale values are
presented as live data.

**The database cannot be created**

Confirm the configured parent directory is writable and that
`AQUASENSE_DATABASE_URL` is a valid SQLAlchemy URL. The default location is
`instance/aquasense.sqlite3` inside the project.
