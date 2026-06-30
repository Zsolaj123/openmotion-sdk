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
