"""
Standalone, hardware-free science-pipeline test runner.

Thin wrapper around the real pipeline test suite. The science pipeline moved
from the old ``SciencePipeline`` in ``omotion/MotionProcessing.py`` (driven by
``tests/test_pipeline_csv.py``, now removed) to the stage-based pipeline under
``omotion/pipeline/``; its tests live under ``tests/test_pipeline/`` (32 files,
fixture/CSV-driven, no device required).

This script just invokes pytest on that suite so the historical entry point
keeps working. Equivalent to::

    pytest tests/test_pipeline/

Usage
-----
From the repo root::

    python scripts/run_pipeline_csv_tests.py [extra pytest args]

Exit codes
----------
Propagates pytest's exit code (0 = all passed).
"""

import os
import subprocess
import sys

# Locate project root relative to this script.
_SCRIPTS_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPTS_DIR)
_PIPELINE_TESTS = os.path.join(_PROJECT_ROOT, "tests", "test_pipeline")


def main() -> int:
    print("=" * 60)
    print("OpenMOTION science pipeline tests (tests/test_pipeline/)")
    print("=" * 60)
    cmd = [sys.executable, "-m", "pytest", _PIPELINE_TESTS, *sys.argv[1:]]
    return subprocess.run(cmd, cwd=_PROJECT_ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
