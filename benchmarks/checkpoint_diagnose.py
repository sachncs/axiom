"""Profile checkpoint maintenance separately from update-throughput qualification.

Profiling overhead is deliberate: these timings are diagnostic, never a service
throughput or latency SLA. All certificates and FULL-WAL commits remain enabled.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import platform
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import Durable, Request
from benchmarks.durable import certificate


def measure(path: Path, vertices: int = 1000000, updates: int = 32768) -> dict:
    """Profile one checkpoint with bounded history, then verify exact recovery."""
    if (
        type(vertices) is not int
        or not 8 <= vertices <= 1000000
        or vertices % 2
        or type(updates) is not int
        or not 256 <= updates <= 48896
        or updates % 256
    ):
        raise ValueError("require even vertices and 256-aligned bounded history")
    if path.exists():
        raise ValueError("diagnostic requires a fresh database")
    with Durable(
        path,
        n=vertices,
        max_batch=256,
        checkpoint_interval=48896,
        retain_operations=16384,
        max_operations=65536,
    ) as owner:
        for first in range(1, updates + 1, 256):
            outcomes = owner.apply(
                [
                    Request(seq, "delete" if seq % 2 else "insert", 0, 1)
                    for seq in range(first, first + 256)
                ]
            )
            if any(not outcome.changed for outcome in outcomes):
                raise RuntimeError("diagnostic requires real changes")
        before = owner.status()
        profile = cProfile.Profile()
        started = time.perf_counter_ns()
        result = profile.runcall(owner.checkpoint)
        elapsed = time.perf_counter_ns() - started
        after = owner.status()
        if (
            before["checkpoint_generation"] != 0
            or after["checkpoint_generation"] != 1
            or after["sequence"] != updates
            or after["version"] != before["version"]
            or after["retained_operations"] != min(updates, 16384)
        ):
            raise RuntimeError("checkpoint changed graph/version or history policy")
        expected = certificate(owner, set(), set(), vertices)
    with Durable(path) as recovered:
        # Restore can compact retained native capacity without changing state.
        restored = recovered.status()
        if {key: value for key, value in restored.items() if key != "native_bytes"} != {
            key: value for key, value in after.items() if key != "native_bytes"
        } or certificate(recovered, set(), set(), vertices) != expected:
            raise RuntimeError("diagnostic exact recovery failed")
    stats = pstats.Stats(profile)
    functions = [
        {
            "file": Path(filename).name,
            "line": line,
            "function": name,
            "primitive_calls": primitive,
            "calls": calls,
            "self_seconds": own,
            "cumulative_seconds": cumulative,
        }
        for (filename, line, name), (primitive, calls, own, cumulative, _) in sorted(
            stats.stats.items(), key=lambda item: item[1][3], reverse=True
        )
    ]
    return {
        "scope": "profiled checkpoint diagnostic; NOT unprofiled latency/throughput qualification",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "vertices": vertices,
        "real_updates_before_checkpoint": updates,
        "history_rows_validated": updates,
        "profiled_checkpoint_ns": elapsed,
        "checkpoint": result,
        "status": after,
        "matching_digest": expected,
        "independent_exact_audit_and_recovery_passed": True,
        "functions": functions,
    }


def main() -> None:
    """Print one maintenance profile and leave the database for inspection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=1000000)
    parser.add_argument("--updates", type=int, default=32768)
    args = parser.parse_args()
    print(json.dumps(measure(args.database, args.vertices, args.updates), indent=2))


if __name__ == "__main__":
    main()
