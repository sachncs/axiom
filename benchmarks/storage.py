"""Measure native storage only; this is not matcher or durable-service throughput.

Run each size in a fresh process, e.g. ``python benchmarks/storage.py --vertices
1000000``. Construction, timed journaled edits, and the final independent audit
are separate. Native allocation is budgeted; process RSS and audit scratch are
not covered by that container budget. Latency instrumentation remains enabled.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.storage import Packed


def measure(
    vertices: int, width: int, pairs: int, seed: int, budget: int
) -> dict[str, object]:
    """Measure a regular ring and real delete/reinsert transactions on its edges.

    Each call opens and commits a one-edit journal. Every sampled edge exists;
    pairs restore the original graph. Percentiles use nearest-rank samples.
    The returned rate includes Python calls, journal operations, and timing.
    """
    if vertices < 3 or width < 1 or width > (vertices - 1) // 2:
        raise ValueError("require vertices >= 3 and 1 <= width < vertices / 2")
    if not 1 <= pairs <= 1_000_000:
        raise ValueError("pairs must be between 1 and 1000000")
    started = time.perf_counter()
    graph = Packed(vertices, budget=budget)
    graph.ring(width)
    construction = time.perf_counter() - started
    initial = graph.memory()
    rng = random.Random(seed)
    edges = [
        (u, (u + 1) % vertices) for u in (rng.randrange(vertices) for _ in range(pairs))
    ]
    latencies: dict[str, list[int]] = {"insert": [], "delete": []}
    trace_started = time.perf_counter()
    for u, v in edges:
        for name, mutate in (("delete", graph.remove_edge), ("insert", graph.add_edge)):
            started_ns = time.perf_counter_ns()
            token = graph.begin()
            try:
                mutate(u, v)
            except BaseException:
                graph.rollback(token)
                raise
            graph.commit(token)
            latencies[name].append(time.perf_counter_ns() - started_ns)
    trace_seconds = time.perf_counter() - trace_started
    started = time.perf_counter()
    valid = (
        graph.check()
        and graph.num_edges() == vertices * width
        and graph.version == 1 + 2 * pairs
    )
    if valid:
        for u in range(vertices):
            expected = sorted(
                neighbor
                for distance in range(1, width + 1)
                for neighbor in ((u + distance) % vertices, (u - distance) % vertices)
            )
            if list(graph.neighbors(u)) != expected:
                valid = False
                break
    audit = time.perf_counter() - started
    if not valid:
        raise RuntimeError("native storage failed its independent post-run audit")
    rates = {}
    for name, samples in latencies.items():
        ordered = sorted(samples)
        rates[name] = {
            "real_updates": len(samples),
            "updates_per_second": len(samples) * 1e9 / sum(samples),
            "p99_ns": ordered[(99 * len(ordered) + 99) // 100 - 1],
            "max_ns": ordered[-1],
        }
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "native-storage-only; no matching, WAL, recovery, or service queue",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "vertices": vertices,
        "edges": graph.num_edges(),
        "average_degree": 2 * width,
        "seed": seed,
        "construction_seconds": construction,
        "audit_seconds": audit,
        "audit_passed": valid,
        "trace_seconds": trace_seconds,
        "trace_updates_per_second": 2 * pairs / trace_seconds,
        "initial_native_memory": initial,
        "final_native_memory": graph.memory(),
        "process_peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
        "operations": rates,
    }


def main() -> None:
    """Print one fresh-process storage measurement as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertices", type=int, default=1_000_000)
    parser.add_argument("--width", type=int, default=2)
    parser.add_argument("--pairs", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=599)
    parser.add_argument("--budget", type=int, default=1 << 30)
    args = parser.parse_args()
    print(
        json.dumps(
            measure(args.vertices, args.width, args.pairs, args.seed, args.budget),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
