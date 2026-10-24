"""Local development entry point for AquaSense."""

from __future__ import annotations

import os

from app import create_app

app = create_app()


def _port_from_environment() -> int:
    raw = os.environ.get("AQUASENSE_PORT", "5000")
    try:
        port = int(raw)
    except ValueError as exc:
        raise SystemExit(f"AQUASENSE_PORT must be an integer, got {raw!r}.") from exc

    if not 0 < port < 65536:
        raise SystemExit(f"AQUASENSE_PORT must be between 1 and 65535, got {port}.")

    return port


if __name__ == "__main__":
    host = os.environ.get("AQUASENSE_HOST", "127.0.0.1")
    debug = os.environ.get("AQUASENSE_DEBUG", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    # Debug mode is opt-in only; it must not be enabled on an untrusted network.
    app.run(host=host, port=_port_from_environment(), debug=debug)
