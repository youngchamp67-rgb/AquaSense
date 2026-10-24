# AquaSense — Phase 1 Flask Dashboard

AquaSense is a local water-quality monitoring dashboard for an existing
ESP32 + LoRa sensing project. Phase 1 delivers a working Flask application with
a responsive dark engineering interface, two read-only JSON endpoints, explicit
empty states, and automated tests.

**Phase 1 has no receiver integration.** No sensor measurements are generated,
simulated, hardcoded, or stored. The dashboard shows pH, TDS, and temperature as
unavailable until a real receiver data path is implemented and approved.

## What is included

| Area | Status |
| --- | --- |
| Dashboard at `/` | Responsive UI with sensor cards, system status, recent-readings table, and chart empty state |
| `GET /api/health` | Returns application health, version, uptime, and data-source state |
| `GET /api/readings/latest` | Documented JSON schema with an explicit `available: false` no-data state |
| Sensor values | All three cards show `—` / “No reading received” |
| Receiver status | `NOT CONNECTED` (or `WAITING FOR DATA` when a future transport is configured) |
| Error handling | Friendly HTML errors, JSON API errors, no tracebacks exposed |
| Demo mode | Not implemented and not enabled |
| Database | Not used in Phase 1; deferred to Phase 2 |
| Hardware firmware | Untouched |

The full API contract is in [docs/api.md](docs/api.md).

## Preserved hardware

No firmware, wiring, sensor library, or radio configuration is changed by this
project.

- **Sender ESP32:** SEN0169 pH sensor, Gravity TDS sensor, DS18B20 temperature
  sensor, OLED display, RA-02 LoRa module.
- **Receiver ESP32:** RA-02 LoRa module and OLED display.

The future communication method, packet format, serial settings, and endpoint
design are intentionally undefined in Phase 1.

## Project structure

```text
aqua-sense-monitor/
├── app/
│   ├── __init__.py            # Flask application factory
│   ├── errors.py              # HTML + JSON error handlers
│   ├── responses.py           # Consistent JSON envelope
│   ├── security.py            # CSP, cache, and security headers
│   ├── routes/
│   │   ├── api.py             # /api/health, /api/readings/latest
│   │   └── pages.py           # Dashboard page
│   ├── services/
│   │   └── readings.py        # Explicit no-data state (no simulation)
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

`requirements-dev.txt` includes Flask and pytest. For a runtime-only install,
use `python -m pip install -r requirements.txt`.

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

### Optional environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AQUASENSE_HOST` | `127.0.0.1` | Bind address |
| `AQUASENSE_PORT` | `5000` | HTTP port |
| `AQUASENSE_DEBUG` | unset (off) | Set to `1` for the Flask debugger — local development only |
| `AQUASENSE_SECRET_KEY` | ephemeral random value | Optional stable Flask secret; keep real values out of source control |

Example:

```powershell
$env:AQUASENSE_PORT = "5001"
$env:AQUASENSE_DEBUG = "1"
python run.py
```

Do not enable debug mode on an untrusted network. No secrets belong in the
repository.

## Run the tests

```powershell
python -m pytest -q
```

The suite covers:

- dashboard rendering and the three sensor empty states
- receiver status and chart/table empty states
- `/api/health` schema, health status, and data-source state
- `/api/readings/latest` no-data schema, null readings, and units
- the `WAITING FOR DATA` state when a transport is configured but no sample exists
- consistent success/error envelopes and HTTP status codes
- JSON errors for unknown API routes and disallowed methods
- cache and security headers
- no traceback or internal path leakage in API responses

## API summary

Both endpoints return a consistent envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "timestamp": "2026-10-24T12:00:00Z"
}
```

- `GET /api/health` — application health. HTTP `200`.
- `GET /api/readings/latest` — latest reading or explicit no-data state. HTTP `200`.
- Unknown API route — HTTP `404` with a JSON error envelope.
- Unsupported method — HTTP `405` with a JSON error envelope.
- Unexpected failure — HTTP `500` with a generic JSON error.

`available: false` is a valid, successful no-data response — not an error. In
Phase 1, every sensor field is `null`.

Quick PowerShell check while the server is running:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health | ConvertTo-Json -Depth 5
Invoke-RestMethod http://127.0.0.1:5000/api/readings/latest | ConvertTo-Json -Depth 5
```

## Data integrity and safety

- No pH, TDS, or temperature value is fabricated on the server, in the browser,
  in tests, or in the database.
- No historical readings are inserted or displayed.
- The dashboard never describes water as safe or unsafe to drink. Three sensors
  alone cannot establish potability.
- Receiver status never implies hardware is online when no data has arrived.
- No serial baud rate, HTTP endpoint, LoRa payload layout, or timing protocol is
  assumed.
- Demo mode is disabled and is not part of this phase. Any future demo mode must
  be explicitly enabled and visibly labelled as simulated.

## Current limitations

- No receiver transport, ingestion service, or data validation pipeline exists.
- No database is used; the chart remains empty and recent readings show the
  empty state.
- The latest-reading endpoint always returns the no-data state in Phase 1.
- There is no authentication. Keep the app bound to `127.0.0.1` or a trusted
  local network.
- Automated tests cover server routes and empty-state behavior; browser
  interactions are not tested with a headless browser.

## Phase 2 (after review)

Receiver integration is intentionally deferred. Before implementing it, the
transport (for example serial, Wi-Fi HTTP, or LoRa gateway), packet format,
validation ranges, timestamp source, persistence, and failure/retry behavior
must be agreed. The Flask response contract and receiver-status model can then
be extended without changing the Phase 1 dashboard semantics.

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
