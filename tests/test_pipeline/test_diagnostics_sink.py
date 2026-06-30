"""Diagnostics consumers — DiagnosticsLogSink + ScanDBSink session_meta summary.

Integrity events (DarkIntegrityWarning, TerminalDarkResult(found=False),
StencilFallback, PipelineError) must not evaporate: the log sink WARNs on
each, and ScanDBSink folds a per-type summary into the session's
session_meta at scan end. Routine events (TriggerStateEvent, successful
TerminalDarkResult) are excluded from the integrity record.
"""

import json
import logging
import sqlite3

from omotion.pipeline.batch import (
    DarkIntegrityWarning,
    PipelineError,
    TerminalDarkResult,
    TriggerStateEvent,
)
from omotion.pipeline.sinks import DiagnosticsLogSink, ScanDBSink, ScanMetadata
from omotion.pipeline.stages.dark import (
    EnrichedCorrectedFrame,
    EnrichedCorrectedInterval,
)


def _meta():
    return ScanMetadata(
        scan_id="diag", subject_id="subj", operator="op",
        started_at_iso="2026-06-10T00:00:00Z", duration_sec=60,
        left_camera_mask=0x01, right_camera_mask=0, reduced_mode=False,
    )


def _dark_warning(abs_id=42):
    return DarkIntegrityWarning(
        side="left", cam_id=0, abs_frame_id=abs_id,
        u1=90.0, pedestal=64.0, threshold=5.0,
    )


def _corrected_interval():
    """One per-camera corrected frame so the session has >=1 row and is not
    deleted as empty (ScanDBSink drops sessions with zero corrected rows).
    Normal-mode meta → cam_id 0 is persisted."""
    return EnrichedCorrectedInterval(left_abs=10, right_abs=610, frames=[
        EnrichedCorrectedFrame(
            abs_frame_id=10, t=0.25, side="left", cam_id=0,
            mean=100.0, std=2.0, contrast=0.02, bfi=4.0, bvi=6.0, quality="ok",
        ),
    ])


def test_log_sink_warns_on_integrity_events(caplog):
    sink = DiagnosticsLogSink()
    sink.on_scan_start(_meta())
    with caplog.at_level(logging.WARNING, logger="openmotion.sdk.pipeline.sinks"):
        sink.consume("diagnostics", _dark_warning())
        sink.consume("diagnostics", PipelineError(
            error="RuntimeError('x')", n_frames=10, first_timestamp_s=1.0))
        sink.on_complete()
    assert "integrity event" in caplog.text
    assert "DarkIntegrityWarning" in caplog.text
    assert "PipelineError" in caplog.text


def test_log_sink_ignores_routine_events(caplog):
    from omotion.pipeline.batch import TerminalFsyncCount
    sink = DiagnosticsLogSink()
    sink.on_scan_start(_meta())
    with caplog.at_level(logging.WARNING, logger="openmotion.sdk.pipeline.sinks"):
        sink.consume("diagnostics", TriggerStateEvent(state="ON", timestamp_s=0.1))
        sink.consume("diagnostics", TerminalDarkResult(
            side="left", cam_id=0, abs_frame_id=100, u1=64.0,
            threshold=69.0, found=True))
        sink.consume("diagnostics", TerminalFsyncCount(count=842, timestamp_s=60.0))
        sink.on_complete()
    assert caplog.text == ""


def test_scan_db_sink_writes_diagnostics_summary_to_session_meta(tmp_path):
    db_path = str(tmp_path / "scan.db")
    sink = ScanDBSink(db_path=db_path)
    sink.on_scan_start(_meta())
    sink.consume("diagnostics", _dark_warning(abs_id=10))
    sink.consume("diagnostics", _dark_warning(abs_id=610))
    sink.consume("diagnostics", TerminalDarkResult(
        side="left", cam_id=0, abs_frame_id=2400, u1=120.0,
        threshold=69.0, found=False))
    # Routine events must not pollute the summary.
    sink.consume("diagnostics", TriggerStateEvent(state="OFF", timestamp_s=60.0))
    # A corrected row so the session survives on_complete (empty sessions are
    # deleted); the diagnostics summary is only written for a non-empty session.
    sink.consume("final", _corrected_interval())
    sink.on_complete()

    conn = sqlite3.connect(db_path)
    meta = json.loads(conn.execute(
        "SELECT session_meta FROM sessions").fetchone()[0])
    conn.close()
    diag = meta["diagnostics"]
    assert diag["DarkIntegrityWarning"] == {"count": 2, "first": 10, "last": 610}
    assert diag["TerminalDarkResult"]["count"] == 1
    assert "TriggerStateEvent" not in diag
    # The rest of the stamped meta survives the update.
    assert meta["data_semantics"] == "final"
    assert meta["sdk_flags"]["reduced_mode"] is False


def test_scan_db_sink_meta_has_no_diagnostics_key_when_clean(tmp_path):
    db_path = str(tmp_path / "scan.db")
    sink = ScanDBSink(db_path=db_path)
    sink.on_scan_start(_meta())
    # A corrected row (no diagnostics events) so the session survives; we are
    # asserting the absence of a diagnostics key, not an empty session.
    sink.consume("final", _corrected_interval())
    sink.on_complete()

    conn = sqlite3.connect(db_path)
    meta = json.loads(conn.execute(
        "SELECT session_meta FROM sessions").fetchone()[0])
    conn.close()
    assert "diagnostics" not in meta
