"""End-to-end test for openmotion-bridge — hardware-free.

Drives a synthetic replay through the HTTP API and asserts the corrected
record is queryable and the live readout is populated. Skips if the optional
``bridge`` extra (fastapi) isn't installed.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openmotion_bridge.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "scan.db"))
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["device"] == "absent"      # no hardware in this process


def test_synthetic_replay_persists_and_serves_bfi(client):
    # 1. Replay a synthetic scan through the real pipeline.
    r = client.post("/replay", json={
        "mode": "synthetic", "scan_id": "s1", "subject_id": "subjA",
        "n_frames": 160, "dark_interval": 40,
    })
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["corrected_rows"] > 0, "replay produced no corrected rows"
    assert summary["session_id"] is not None

    # 2. The scan index lists it.
    scans = client.get("/scans").json()
    assert any(s["id"] == summary["session_id"] for s in scans)

    # 3. The corrected timeseries is queryable with finite BFI/BVI.
    data = client.get(f"/scan/{summary['session_id']}").json()["data"]
    assert len(data) > 0
    bfis = [row["bfi"] for row in data if row.get("bfi") is not None]
    assert bfis and all(math.isfinite(v) for v in bfis)

    # 4. The live readout was populated during the replay.
    live = client.get("/live/subjA").json()
    assert (live["left"] is not None) or (live["right"] is not None)


def test_scan_404(client):
    assert client.get("/scan/99999").status_code == 404


def test_bilateral_replay(client):
    r = client.post("/replay", json={
        "mode": "synthetic", "scan_id": "s2", "subject_id": "subjB",
        "n_frames": 160, "dark_interval": 40,
        "left_camera_mask": 0x01, "right_camera_mask": 0x01,
    })
    assert r.status_code == 200
    sid = r.json()["session_id"]
    sides = {row["side"] for row in client.get(f"/scan/{sid}").json()["data"]}
    assert sides == {0, 1}, f"expected both sides, got {sides}"


def test_ingest_persists_and_serves(client):
    """POST /ingest stores pushed corrected rows; they come back queryable."""
    body = {"scan_id": "ing", "subject_id": "subjC", "rows": [
        {"side": 0, "cam_id": 0, "frame_id": 10, "timestamp_s": 0.25, "bfi": 4.1, "bvi": 6.0},
        {"side": 1, "cam_id": 2, "frame_id": 11, "timestamp_s": 0.275, "bfi": 3.9, "bvi": 5.8},
    ]}
    r = client.post("/ingest", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ingested_rows"] == 2
    data = client.get(f"/scan/{out['session_id']}").json()["data"]
    assert len(data) == 2
    assert {row["side"] for row in data} == {0, 1}
    assert all(row["bfi"] is not None for row in data)


def test_upload_roundtrip(tmp_path):
    """The workstation→Niflheim path: rows_from_session reads a replayed local
    DB, those rows POST to /ingest on a second bridge, and come back queryable."""
    from openmotion_bridge.engine import ReplayEngine
    from openmotion_bridge import upload as up

    # 1. "workstation" bridge: replay a synthetic scan into a local DB.
    src_db = str(tmp_path / "ws.db")
    summary = ReplayEngine(src_db).run_synthetic(
        scan_id="s", subject_id="subjD", n_frames=160, dark_interval=40)
    assert summary["corrected_rows"] > 0
    session, rows = up.rows_from_session(src_db, summary["session_id"])
    assert rows and {r["side"] for r in rows} <= {0, 1}

    # 2. "Niflheim" bridge: ingest those rows over HTTP, then serve them back.
    dst = TestClient(create_app(db_path=str(tmp_path / "niflheim.db")))
    r = dst.post("/ingest", json={
        "scan_id": "s", "subject_id": "subjD", "rows": rows,
        "session_meta": session.get("session_meta"),
    })
    assert r.status_code == 200, r.text
    assert r.json()["ingested_rows"] == len(rows)
    served = dst.get(f"/scan/{r.json()['session_id']}").json()["data"]
    assert len(served) == len(rows)
