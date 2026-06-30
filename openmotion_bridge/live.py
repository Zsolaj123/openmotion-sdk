"""LiveRingSink — captures the most recent per-side BFI/BVI for the live UI.

Subscribes to the pipeline's ``"live"`` channel (per-frame, best-effort
corrected). The runner delivers a FrameBatch snapshot per emit; we read its
``bfi_live`` / ``bvi_live`` (shape ``(N, 2, 8)``) and keep, per side, the most
recent finite value plus a short ring of samples for a sparkline. This is the
data ``GET /live/{subject_id}`` returns; the durable per-interval record is the
ScanDatabase written by ScanDBSink.
"""

from __future__ import annotations

import collections
import math
from typing import Any, Optional

import numpy as np

_SIDE_NAMES = ("left", "right")


class LiveRingSink:
    channels = {"live"}

    def __init__(self, subject_id: str, *, maxlen: int = 400) -> None:
        self.subject_id = subject_id
        # side_name -> {"bfi", "bvi", "t", "frame_id"} (latest finite)
        self.latest: dict[str, dict] = {}
        # ring of (t, side, bfi, bvi, frame_id) for a sparkline
        self.samples: collections.deque = collections.deque(maxlen=maxlen)
        self._meta: Optional[Any] = None

    def on_scan_start(self, meta: Any) -> None:
        self._meta = meta

    def consume(self, channel: str, payload: Any) -> None:
        if channel != "live":
            return
        batch = payload
        bfi = getattr(batch, "bfi_live", None)
        bvi = getattr(batch, "bvi_live", None)
        if bfi is None:
            return
        cam_ids = batch.cam_ids
        side_ids = getattr(batch, "side_ids", None)
        ts = batch.timestamp_s
        fids = batch.frame_ids
        n = cam_ids.shape[0]
        for i in range(n):
            sidx = int(side_ids[i]) if side_ids is not None else -1
            if sidx not in (0, 1):
                continue
            cam = int(cam_ids[i])
            v_bfi = float(bfi[i, sidx, cam])
            v_bvi = float(bvi[i, sidx, cam]) if bvi is not None else float("nan")
            if not math.isfinite(v_bfi):
                continue
            side = _SIDE_NAMES[sidx]
            t = float(ts[i]) if ts is not None else 0.0
            frame_id = int(fids[i]) if fids is not None else -1
            self.latest[side] = {
                "bfi": v_bfi,
                "bvi": v_bvi if math.isfinite(v_bvi) else None,
                "t": t,
                "frame_id": frame_id,
            }
            self.samples.append((t, side, v_bfi, v_bvi, frame_id))

    def on_complete(self) -> None:
        pass

    def snapshot(self) -> dict:
        """JSON-serializable view for GET /live."""
        return {
            "subject_id": self.subject_id,
            "left": self.latest.get("left"),
            "right": self.latest.get("right"),
            "n_samples": len(self.samples),
        }
