"""openmotion-bridge — the single process that imports ``omotion``.

A standalone AGPL service that runs the Open-Motion science pipeline over
fixture / synthetic / recorded-CSV replay (and, on a bench machine with the
device attached, live scans), persists the corrected record to a
``ScanDatabase``, and exposes it over plain HTTP/JSON. Proprietary Neuratos
services (the SvelteKit dashboard, ML jobs) talk to this bridge ONLY over the
network — so ``omotion`` (AGPL-3.0) is never linked into closed code.

This package is the AGPL boundary by construction: keep it the only thing that
``import omotion``s.
"""

from .engine import ReplayEngine
from .live import LiveRingSink

__all__ = ["ReplayEngine", "LiveRingSink"]
