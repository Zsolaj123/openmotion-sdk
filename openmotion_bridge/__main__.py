"""Run the bridge: ``python -m openmotion_bridge``.

Env:
  OPENMOTION_BRIDGE_DB    SQLite scan-DB path (default openmotion_scans.db)
  OPENMOTION_BRIDGE_HOST  bind host (default 127.0.0.1 — keep it loopback)
  OPENMOTION_BRIDGE_PORT  bind port (default 5197; on Niflheim 5192 is the
                          Sana/SD image-gen service and 5193 is the Quarkdown
                          coordinator — 5197 is free)
"""

from __future__ import annotations

import os

import uvicorn

from .app import create_app


def main() -> None:
    host = os.environ.get("OPENMOTION_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENMOTION_BRIDGE_PORT", "5197"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
