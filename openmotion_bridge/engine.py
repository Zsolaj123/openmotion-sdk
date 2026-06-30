"""ReplayEngine — runs the real Open-Motion pipeline over synthetic / recorded
data with NO device, persisting the corrected record to a ScanDatabase.

This is the headless heart of the bridge: it lets the entire downstream stack
(dashboard, ML) be built and exercised before any hardware streams. It uses the
identical ``default_pipeline`` + ``ScanRunner`` + ``ScanDBSink`` a live scan
uses; only the Source differs (SyntheticSource / CsvReplaySource instead of
LiveUsbSource).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from omotion.pipeline.factory import default_pipeline
from omotion.pipeline.runner import ScanRunner
from omotion.pipeline.sinks import ScanDBSink, ScanMetadata
from omotion.pipeline.sources import SyntheticSource, CsvReplaySource
from omotion.pipeline.pedestal import SensorPedestals
from omotion.ScanDatabase import ScanDatabase

from .live import LiveRingSink

_DEFAULT_PEDESTAL = 64.0


@dataclass
class _TrivialCalibration:
    """Identity-ish affine calibration used for device-free replay. Real scans
    load calibration from the console EEPROM; for replay the BFI/BVI are
    relative indices (which is what they are clinically anyway)."""
    c_min: np.ndarray
    c_max: np.ndarray
    i_min: np.ndarray
    i_max: np.ndarray

    @classmethod
    def identity(cls) -> "_TrivialCalibration":
        return cls(
            c_min=np.zeros((2, 8), dtype=np.float32),
            c_max=np.ones((2, 8), dtype=np.float32),
            i_min=np.zeros((2, 8), dtype=np.float32),
            i_max=np.full((2, 8), 500.0, dtype=np.float32),
        )


class ReplayEngine:
    """Owns the ScanDatabase path and the latest live state from the most
    recent replay. One engine per bridge process."""

    def __init__(self, db_path: str, *, pedestal: float = _DEFAULT_PEDESTAL) -> None:
        self.db_path = str(db_path)
        self._pedestal = float(pedestal)
        self.live: Optional[LiveRingSink] = None

    # -- replay drivers ---------------------------------------------------

    def run_synthetic(self, *,
                      scan_id: str,
                      subject_id: str,
                      n_frames: int = 200,
                      dark_interval: int = 40,
                      discard_count: int = 9,
                      left_camera_mask: int = 0x01,
                      right_camera_mask: int = 0x00,
                      reduced_mode: bool = False,
                      seed: int = 42) -> dict:
        meta = self._meta(scan_id, subject_id, left_camera_mask,
                          right_camera_mask, reduced_mode)
        source = SyntheticSource(
            metadata=meta, n_frames=n_frames, dark_interval=dark_interval,
            discard_count=discard_count, pedestal=self._pedestal, seed=seed,
        )
        return self._run(meta, source, dark_interval=dark_interval,
                         discard_count=discard_count)

    def run_csv(self, *,
                scan_id: str,
                subject_id: str,
                raw_csv_left: Optional[str],
                raw_csv_right: Optional[str],
                dark_interval: int = 600,
                discard_count: int = 9,
                left_camera_mask: int = 0xFF,
                right_camera_mask: int = 0xFF,
                reduced_mode: bool = False) -> dict:
        meta = self._meta(scan_id, subject_id, left_camera_mask,
                          right_camera_mask, reduced_mode)
        source = CsvReplaySource(
            raw_csv_left=Path(raw_csv_left) if raw_csv_left else None,
            raw_csv_right=Path(raw_csv_right) if raw_csv_right else None,
            batch_size_frames=100, metadata=meta,
        )
        return self._run(meta, source, dark_interval=dark_interval,
                         discard_count=discard_count)

    # -- internals --------------------------------------------------------

    def _meta(self, scan_id, subject_id, left_mask, right_mask, reduced) -> ScanMetadata:
        return ScanMetadata(
            scan_id=scan_id, subject_id=subject_id, operator="bridge",
            started_at_iso="1970-01-01T00:00:00Z", duration_sec=0,
            left_camera_mask=left_mask, right_camera_mask=right_mask,
            reduced_mode=reduced,
        )

    def _run(self, meta: ScanMetadata, source: Any, *,
             dark_interval: int, discard_count: int) -> dict:
        pipeline = default_pipeline(
            metadata=meta,
            calibration=_TrivialCalibration.identity(),
            pedestals=SensorPedestals(left=self._pedestal, right=self._pedestal),
            dark_interval=dark_interval,
            discard_count=discard_count,
        )
        live = LiveRingSink(meta.subject_id)
        db_sink = ScanDBSink(db_path=self.db_path)
        ScanRunner(source=source, pipeline=pipeline, sinks=[db_sink, live]).run()
        self.live = live

        # Count what landed (the session may have been dropped if empty).
        label = f"{meta.scan_id}_{meta.subject_id}"
        corrected_rows = 0
        session_id: Optional[int] = None
        db = ScanDatabase(db_path=self.db_path)
        try:
            sess = db.get_session_by_label(label)
            if sess is not None:
                session_id = int(sess["id"])
                corrected_rows = sum(1 for _ in db.iter_session_data(session_id))
        finally:
            db.close()
        return {
            "scan_id": meta.scan_id,
            "subject_id": meta.subject_id,
            "session_label": label,
            "session_id": session_id,
            "corrected_rows": corrected_rows,
            "live": live.snapshot(),
        }

    # -- read helpers (used by the HTTP layer) ----------------------------

    def list_scans(self) -> list[dict]:
        db = ScanDatabase(db_path=self.db_path)
        try:
            return list(db.iter_sessions())
        finally:
            db.close()

    def get_scan(self, session_id: int, *, side: Optional[int] = None,
                 cam_id: Optional[int] = None, limit: Optional[int] = None) -> dict:
        db = ScanDatabase(db_path=self.db_path)
        try:
            session = db.get_session(session_id)
            rows = []
            if limit is None or limit > 0:   # limit<=0 → metadata only, no rows
                for row in db.iter_session_data(session_id, side=side, cam_id=cam_id):
                    rows.append(row)
                    if limit is not None and len(rows) >= limit:
                        break
            return {"session": session, "data": rows}
        finally:
            db.close()

    # -- ingest (a remote bridge → this instance) -------------------------

    def ingest_rows(self, *, scan_id: str, subject_id: str, rows: list[dict],
                    session_meta: Optional[dict] = None,
                    session_start: Optional[float] = None) -> dict:
        """Persist corrected rows pushed from another bridge — e.g. the bench
        workstation's bridge POSTing a finished scan to this Niflheim instance.

        Each row needs at least ``side`` (0/1); cam_id/frame_id/timestamp_s and
        the bfi/bvi/contrast/mean/quality metrics are optional. Creates one
        session (label ``{scan_id}_{subject_id}``) and returns its id + count.
        """
        if not rows:
            # nothing to persist — don't create an orphan empty session
            return {"session_id": None, "session_label": f"{scan_id}_{subject_id}",
                    "ingested_rows": 0, "note": "no rows to ingest"}
        db = ScanDatabase(db_path=self.db_path)
        try:
            label = f"{scan_id}_{subject_id}"
            meta = session_meta or {
                "scan_id": scan_id, "subject_id": subject_id,
                "data_semantics": "final",
            }
            start = float(session_start) if session_start is not None else time.time()
            session_id = db.create_session(
                session_label=label, session_start=start,
                session_notes=None, session_meta=meta,
            )
            payload = [{
                "session_id": session_id,
                "cam_id": int(r.get("cam_id", -1)),
                "side": int(r["side"]),
                "frame_id": int(r.get("frame_id", -1)),
                "timestamp_s": float(r.get("timestamp_s", 0.0)),
                "bfi": r.get("bfi"), "bvi": r.get("bvi"),
                "contrast": r.get("contrast"), "mean": r.get("mean"),
                "quality": str(r.get("quality", "ok") or "ok"),
            } for r in rows]
            try:
                n = db.insert_session_data_rows(payload) if payload else 0
            except Exception:
                db.delete_session(session_id)   # no orphan empty session on a rejected batch
                raise
            db.close_session(session_id, start)
            return {"session_id": session_id, "session_label": label,
                    "ingested_rows": n}
        finally:
            db.close()
