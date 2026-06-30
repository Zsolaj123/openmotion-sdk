"""FastAPI app for the openmotion-bridge.

Plain HTTP/JSON over the ScanDatabase + the ReplayEngine. No auth here — bind to
127.0.0.1 on Niflheim and let the dashboard proxy/auth in front of it; when the
bench workstation posts to Niflheim over Tailscale, terminate that with a token
at the dashboard ingest route, not here.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .engine import ReplayEngine


class ReplayRequest(BaseModel):
    mode: str = "synthetic"            # "synthetic" | "csv"
    scan_id: str
    subject_id: str
    # synthetic params
    n_frames: int = 200
    dark_interval: int = 40
    discard_count: int = 9
    left_camera_mask: int = 0x01
    right_camera_mask: int = 0x00
    reduced_mode: bool = False
    seed: int = 42
    # csv params
    raw_csv_left: Optional[str] = None
    raw_csv_right: Optional[str] = None


class IngestRow(BaseModel):
    side: int                       # 0 = left, 1 = right (required)
    cam_id: int = -1
    frame_id: int = -1
    timestamp_s: float = 0.0
    bfi: Optional[float] = None
    bvi: Optional[float] = None
    contrast: Optional[float] = None
    mean: Optional[float] = None
    quality: str = "ok"


class IngestRequest(BaseModel):
    scan_id: str
    subject_id: str
    rows: list[IngestRow]
    session_meta: Optional[dict] = None
    session_start: Optional[float] = None


def create_app(db_path: Optional[str] = None,
               engine: Optional[ReplayEngine] = None) -> FastAPI:
    db_path = db_path or os.environ.get("OPENMOTION_BRIDGE_DB", "openmotion_scans.db")
    engine = engine or ReplayEngine(db_path)
    app = FastAPI(title="openmotion-bridge", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {
            "ok": True,
            "service": "openmotion-bridge",
            "db_path": engine.db_path,
            "fixture_mode": True,   # no live device attached in this process
            "device": "absent",
        }

    @app.get("/scans")
    def scans() -> list:
        return engine.list_scans()

    @app.get("/scan/{session_id}")
    def scan(session_id: int, side: Optional[int] = None,
             cam_id: Optional[int] = None, limit: Optional[int] = None) -> dict:
        result = engine.get_scan(session_id, side=side, cam_id=cam_id, limit=limit)
        if result["session"] is None:
            raise HTTPException(status_code=404, detail=f"session {session_id} not found")
        return result

    @app.post("/replay")
    def replay(req: ReplayRequest) -> dict:
        if req.mode == "synthetic":
            return engine.run_synthetic(
                scan_id=req.scan_id, subject_id=req.subject_id,
                n_frames=req.n_frames, dark_interval=req.dark_interval,
                discard_count=req.discard_count,
                left_camera_mask=req.left_camera_mask,
                right_camera_mask=req.right_camera_mask,
                reduced_mode=req.reduced_mode, seed=req.seed,
            )
        if req.mode == "csv":
            if not (req.raw_csv_left or req.raw_csv_right):
                raise HTTPException(status_code=400,
                                    detail="csv mode needs raw_csv_left and/or raw_csv_right")
            return engine.run_csv(
                scan_id=req.scan_id, subject_id=req.subject_id,
                raw_csv_left=req.raw_csv_left, raw_csv_right=req.raw_csv_right,
                dark_interval=req.dark_interval, discard_count=req.discard_count,
                left_camera_mask=req.left_camera_mask,
                right_camera_mask=req.right_camera_mask,
                reduced_mode=req.reduced_mode,
            )
        raise HTTPException(status_code=400, detail=f"unknown mode {req.mode!r}")

    @app.post("/ingest")
    def ingest(req: IngestRequest) -> dict:
        # Receive corrected rows pushed from another bridge (the bench
        # workstation → this Niflheim instance). The cross-Tailscale hop should
        # carry an auth token at the dashboard proxy in front of this; the
        # bridge itself stays loopback + unauthenticated by design.
        return engine.ingest_rows(
            scan_id=req.scan_id, subject_id=req.subject_id,
            rows=[r.model_dump() for r in req.rows],
            session_meta=req.session_meta, session_start=req.session_start,
        )

    @app.get("/live/{subject_id}")
    def live(subject_id: str) -> dict:
        if engine.live is None or engine.live.subject_id != subject_id:
            return {"subject_id": subject_id, "left": None, "right": None, "n_samples": 0}
        return engine.live.snapshot()

    return app
