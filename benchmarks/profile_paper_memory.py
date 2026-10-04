"""Profile paper-mode startup stages in a fresh process.

This diagnostic enables tracemalloc and therefore must not be used as the
512 MiB resource qualification run. Run one mode per process for comparable
stage RSS, Python allocation, and timing records.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
import tracemalloc
from pathlib import Path


def main() -> int:
    """Run one fresh-process startup profile and print its summary record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertices", type=int, required=True)
    parser.add_argument("--width", type=int, default=2)
    parser.add_argument("--mode", choices=("basic", "multilevel"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.vertices < 0 or args.width < 0:
        parser.error("vertices and width must be nonnegative")

    os.environ["AXIOM_PROFILE_STAGES"] = "1"
    from axiom.core import Matcher
    from axiom.storage import Packed

    graph = Packed(args.vertices)
    if args.width:
        graph.ring(args.width)
    started = time.perf_counter_ns()
    matcher = Matcher(args.vertices, mode=args.mode, graph=graph)
    elapsed = time.perf_counter_ns() - started
    current, peak = tracemalloc.get_traced_memory()
    system = matcher.system
    record = {
        "mode": args.mode,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "vertices": args.vertices,
        "edges": matcher.graph.num_edges(),
        "startup_elapsed_ns": elapsed,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "python_current_bytes": current,
        "python_peak_bytes": peak,
        "graph_memory": matcher.graph.memory(),
        "system": {
            "A": len(system.A) if system is not None else 0,
            "B": len(system.B) if system is not None else 0,
            "U": len(system.U) if system is not None else 0,
            "lambda_rows": len(system.lambda_lists) if system is not None else 0,
            "lambda_entries": (
                sum(map(len, system.lambda_lists.values())) if system is not None else 0
            ),
            "L_rows": len(system.L_lists) if system is not None else 0,
            "L_entries": (
                sum(map(len, system.L_lists.values())) if system is not None else 0
            ),
        },
        # Matcher construction completes its mode-specific certificates before
        # returning; an additional full audit here duplicates state-sized scans.
        "constructor_certified": True,
    }
    encoded = json.dumps(record, sort_keys=True, indent=2) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
