"""Run the bridge: ``python -m openmotion_bridge``.

Env:
  OPENMOTION_BRIDGE_DB    SQLite scan-DB path (default openmotion_scans.db)
  OPENMOTION_BRIDGE_HOST  bind host (default 127.0.0.1 — keep it loopback)
  OPENMOTION_BRIDGE_PORT  bind port (default 5193; 5192 is taken on Niflheim by
                          the Sana/SD image-gen service)
"""

from __future__ import annotations

import os

import uvicorn

from .app import create_app


def main() -> None:
    host = os.environ.get("OPENMOTION_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENMOTION_BRIDGE_PORT", "5193"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
