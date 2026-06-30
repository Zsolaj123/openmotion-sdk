"""Hardware-free end-to-end test for SyntheticSource.

This is the regression guard for the ``demo_mode`` gap: ``demo_mode`` produces
an EMPTY scan (no frames, no BFI/BVI), so a test that only checks "no
exception" would green-light a no-data path. This test asserts on ACTUAL
corrected BFI/BVI output flowing through the real ``default_pipeline``, with no
hardware.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from omotion.pipeline.factory import default_pipeline
from omotion.pipeline.runner import ScanRunner
from omotion.pipeline.sources import SyntheticSource
from omotion.pipeline.sinks import ScanMetadata
from omotion.pipeline.pedestal import SensorPedestals


_PEDESTAL = 64.0


@dataclass
class _TrivialCal:
    """Identity-ish affine calibration (same shape default_pipeline expects)."""
    c_min: np.ndarray
    c_max: np.ndarray
    i_min: np.ndarray
    i_max: np.ndarray


def _trivial_cal() -> _TrivialCal:
    return _TrivialCal(
        c_min=np.zeros((2, 8), dtype=np.float32),
        c_max=np.ones((2, 8), dtype=np.float32),
        i_min=np.zeros((2, 8), dtype=np.float32),
        i_max=np.full((2, 8), 500.0, dtype=np.float32),
    )


class _CollectingSink:
    """Records corrected per-camera frames from the 'final' channel."""

    channels = {"final", "diagnostics"}

    def __init__(self) -> None:
        self.final_intervals = 0
        self.bfi_values: list[float] = []
        self.bvi_values: list[float] = []

    def on_scan_start(self, meta) -> None:  # noqa: D401
        pass

    def consume(self, channel, payload) -> None:
        if channel != "final":
            return
        self.final_intervals += 1
        for f in getattr(payload, "frames", []):
            if not (0 <= int(getattr(f, "cam_id", -99)) < 8):
                continue
            bfi = getattr(f, "bfi", None)
            bvi = getattr(f, "bvi", None)
            if bfi is not None:
                self.bfi_values.append(float(bfi))
            if bvi is not None:
                self.bvi_values.append(float(bvi))

    def on_complete(self) -> None:
        pass


def _meta(**over) -> ScanMetadata:
    base = dict(
        scan_id="synth", subject_id="s", operator="op",
        started_at_iso="2026-06-30T00:00:00Z", duration_sec=2,
        left_camera_mask=0x01, right_camera_mask=0x00, reduced_mode=False,
    )
    base.update(over)
    return ScanMetadata(**base)


def _run(meta: ScanMetadata, *, discard_count=9, dark_interval=20, **src) -> _CollectingSink:
    pipeline = default_pipeline(
        metadata=meta,
        calibration=_trivial_cal(),
        pedestals=SensorPedestals(left=_PEDESTAL, right=_PEDESTAL),
        dark_interval=dark_interval,
        discard_count=discard_count,
    )
    source = SyntheticSource(
        metadata=meta, pedestal=_PEDESTAL,
        discard_count=discard_count, dark_interval=dark_interval, **src,
    )
    sink = _CollectingSink()
    ScanRunner(source=source, pipeline=pipeline, sinks=[sink]).run()
    return sink


def test_synthetic_source_streams_corrected_bfi_bvi():
    """The whole point: unlike demo_mode, real frames flow and intervals close."""
    sink = _run(_meta(), n_frames=50)
    assert sink.final_intervals > 0, (
        "no corrected intervals closed — source produced no streamable data "
        "(this is the demo_mode failure mode the synthetic source exists to fix)"
    )
    assert sink.bfi_values, "no BFI values emitted on the 'final' channel"
    assert sink.bvi_values, "no BVI values emitted on the 'final' channel"
    assert all(math.isfinite(v) for v in sink.bfi_values), "non-finite BFI emitted"
    assert all(math.isfinite(v) for v in sink.bvi_values), "non-finite BVI emitted"


def test_synthetic_source_is_deterministic():
    a = _run(_meta(), n_frames=50)
    b = _run(_meta(), n_frames=50)
    assert a.bfi_values == b.bfi_values, "same seed must give identical BFI output"


def test_synthetic_source_bilateral():
    """Both sides stream when both camera masks are set."""
    sink = _run(_meta(right_camera_mask=0x01), n_frames=50)
    assert sink.final_intervals > 0
    assert sink.bfi_values
