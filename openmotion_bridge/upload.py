"""Push a finished local scan to a remote openmotion-bridge ``/ingest``.

The workstation acquires a scan (writing a local ScanDatabase), then this
uploads that session's corrected rows to the Niflheim bridge over the network
(Tailscale / SSH-forwarded localhost). File-sync (rsync of the .db) is the
other, simpler hand-off; this is the network-push path.

    python -m openmotion_bridge.upload  ./scans.db  http://localhost:5193  --session-id 1

``requests`` is already an omotion dependency, so no extra install is needed on
the acquisition side.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

import requests

from omotion.ScanDatabase import ScanDatabase

_ROW_KEYS = ("side", "cam_id", "frame_id", "timestamp_s",
             "bfi", "bvi", "contrast", "mean", "quality")


def rows_from_session(db_path: str, session_id: int):
    """Return ``(session_dict, rows)`` for one session in a local scan DB."""
    db = ScanDatabase(db_path=db_path)
    try:
        session = db.get_session(session_id)
        rows = [{k: r.get(k) for k in _ROW_KEYS}
                for r in db.iter_session_data(session_id)]
        return session, rows
    finally:
        db.close()


def latest_session_id(db_path: str) -> Optional[int]:
    db = ScanDatabase(db_path=db_path)
    try:
        sid = None
        for s in db.iter_sessions():
            sid = int(s["id"])   # iter_sessions is ordered by start/id
        return sid
    finally:
        db.close()


def upload(db_path: str, base_url: str, *, session_id: Optional[int] = None,
           scan_id: Optional[str] = None, subject_id: Optional[str] = None,
           timeout: float = 30.0) -> dict:
    if session_id is None:
        session_id = latest_session_id(db_path)
        if session_id is None:
            raise SystemExit(f"no sessions in {db_path}")
    session, rows = rows_from_session(db_path, session_id)
    if session is None:
        raise SystemExit(f"session {session_id} not found in {db_path}")
    if not rows:
        raise SystemExit(f"session {session_id} in {db_path} has no corrected rows to upload")
    meta = session.get("session_meta") if session else None
    label = (session or {}).get("session_label", "") or ""
    if isinstance(meta, dict):
        scan_id = scan_id or meta.get("scan_id")
        subject_id = subject_id or meta.get("subject_id")
    if (scan_id is None or subject_id is None) and "_" in label:
        a, _, b = label.partition("_")
        scan_id = scan_id or a
        subject_id = subject_id or b
    body = {
        "scan_id": scan_id or "scan",
        "subject_id": subject_id or "subj",
        "rows": rows,
        "session_meta": meta if isinstance(meta, dict) else None,
    }
    resp = requests.post(base_url.rstrip("/") + "/ingest", json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Upload a local scan to a remote openmotion-bridge /ingest")
    p.add_argument("db_path", help="local ScanDatabase path")
    p.add_argument("base_url", help="remote bridge base URL, e.g. http://localhost:5193")
    p.add_argument("--session-id", type=int, default=None,
                   help="session id to upload (default: the latest in the DB)")
    p.add_argument("--scan-id", default=None)
    p.add_argument("--subject-id", default=None)
    args = p.parse_args(argv)
    result = upload(args.db_path, args.base_url, session_id=args.session_id,
                    scan_id=args.scan_id, subject_id=args.subject_id)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
