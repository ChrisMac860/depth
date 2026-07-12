"""DEPTH launcher.

Usage:
    python run.py

Serves the app on http://127.0.0.1:8000 (localhost only — this is a local
product, see SPEC.md "Notes for builders").
"""

from __future__ import annotations

from server.app import app

HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    print(f"DEPTH running at {url}")
    print('"See what the mean is hiding."')
    app.run(host=HOST, port=PORT)


if __name__ == "__main__":
    main()
