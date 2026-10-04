"""Opt-in process and Python-allocation measurements for paper hot paths.

Set ``AXIOM_PROFILE_STAGES=1`` in a diagnostic process to emit one JSON record
per measured stage to stderr, including tracemalloc peaks. Set
``AXIOM_PROFILE_RSS_ONLY=1`` to retain stage timing/RSS without allocation
tracing when diagnosing a constrained run.
"""

from __future__ import annotations

import json
import os
import sys
import time
import tracemalloc
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_ENABLED = (
    os.environ.get("AXIOM_PROFILE_STAGES") == "1"
    or os.environ.get("AXIOM_PROFILE_RSS_ONLY") == "1"
)
_TRACE_ALLOCATIONS = os.environ.get("AXIOM_PROFILE_STAGES") == "1"
_RSS_KIND = "resident" if os.path.exists("/proc/self/statm") else "process_peak"
if _TRACE_ALLOCATIONS and not tracemalloc.is_tracing():
    tracemalloc.start()


def _rss_bytes() -> int | None:
    """Return current resident bytes on Linux/macOS when the OS exposes it."""
    try:
        with open("/proc/self/statm", encoding="ascii") as source:
            resident_pages = int(source.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):
        pass
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except (ImportError, OSError, ValueError):
        return None


@contextmanager
def profile_stage(name: str, **sizes: int) -> Iterator[None]:
    """Measure one stage when profiling is enabled; otherwise add no work."""
    if not _ENABLED:
        yield
        return
    started = time.perf_counter_ns()
    rss_before = _rss_bytes()
    if tracemalloc.is_tracing():
        tracemalloc.reset_peak()
    try:
        yield
    finally:
        current, peak = (
            tracemalloc.get_traced_memory()
            if tracemalloc.is_tracing()
            else (None, None)
        )
        record: dict[str, Any] = {
            "stage": name,
            "elapsed_ns": time.perf_counter_ns() - started,
            "rss_before_bytes": rss_before,
            "rss_after_bytes": _rss_bytes(),
            "rss_measurement": _RSS_KIND,
            "python_current_bytes": current,
            "python_peak_bytes": peak,
            "sizes": sizes,
        }
        print(json.dumps(record, sort_keys=True), file=sys.stderr, flush=True)
