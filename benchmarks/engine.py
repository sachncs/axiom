"""Measure full native matching plus coherent queries, without persistence.

This is a stepping stone, not the accepted durable 10k/s qualification. Run sizes
sequentially in fresh processes. Final exact graph and independent matching audits
are outside the update trace and included in reported process RSS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import resource
import sys
import time
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.engine import Engine


def canonical(u: int, v: int) -> tuple[int, int]:
    """Return one ordered undirected edge key."""
    return min(u, v), max(u, v)


def measure(vertices: int, pairs: int, seed: int, budget: int) -> dict:
    """Maintain average-degree-four churn and perform one partner query per pair.

    Deletes target live original-ring edges. Inserts are distinct absent non-ring
    edges. This short trace exercises real topology changes and matched deletes;
    inserted edges persist, so it is not a long-duration stationary workload.
    All query/selection overhead is included in the whole-trace rate.
    """
    if vertices < 8 or not 1 <= pairs <= min(100_000, vertices):
        raise ValueError(
            "require vertices >= 8 and 1 <= pairs <= min(100000, vertices)"
        )
    started = time.perf_counter()
    engine = Engine(vertices, budget=budget)
    engine.ring(2)
    construction = time.perf_counter() - started
    initial_memory = engine.memory()
    rng = random.Random(seed)
    removed: set[tuple[int, int]] = set()
    extra: set[tuple[int, int]] = set()
    digest = hashlib.sha256()
    durations: dict[str, list[int]] = {"delete": [], "insert": [], "partner": []}
    matched_deletes = 0
    started = time.perf_counter()
    for _ in range(pairs):
        while True:
            u = rng.randrange(vertices)
            edge = canonical(u, (u + rng.randrange(1, 3)) % vertices)
            if edge not in removed:
                break
        u, v = edge
        matched_deletes += engine.partner(u) == v
        tick = time.perf_counter_ns()
        if not engine.delete(u, v):
            raise RuntimeError("native benchmark expected a real deletion")
        durations["delete"].append(time.perf_counter_ns() - tick)
        removed.add(edge)
        digest.update(f"delete:{u}:{v};".encode())
        while True:
            u, v = sorted(rng.sample(range(vertices), 2))
            if 2 < v - u < vertices - 2 and (u, v) not in extra:
                break
        tick = time.perf_counter_ns()
        if not engine.insert(u, v):
            raise RuntimeError("native benchmark expected a real insertion")
        durations["insert"].append(time.perf_counter_ns() - tick)
        extra.add((u, v))
        digest.update(f"insert:{u}:{v};".encode())
        vertex = rng.randrange(vertices)
        tick = time.perf_counter_ns()
        engine.partner(vertex)
        durations["partner"].append(time.perf_counter_ns() - tick)
    elapsed = time.perf_counter() - started
    final_memory = engine.memory()
    started = time.perf_counter()
    if (
        not engine.check()
        or engine.version != 1 + 2 * pairs
        or engine.num_edges() != 2 * vertices
    ):
        raise RuntimeError("native full audit/count/version failed")
    # Independent public-query certificate: compact partner array, exact expected
    # edges/count, symmetry/live matching edges, and coverage of every expected edge.
    partners = array(
        "I",
        (
            p if (p := engine.partner(u)) is not None else 0xFFFFFFFF
            for u in range(vertices)
        ),
    )
    count = 0
    for u, v in enumerate(partners):
        if v != 0xFFFFFFFF:
            if v >= vertices or v == u or partners[v] != u or not engine.has_edge(u, v):
                raise RuntimeError(
                    "independent partner/proper-matching certificate failed"
                )
            count += u < v
    if count != engine.size():
        raise RuntimeError("independent matching count failed")
    expected_count = 0
    for u in range(vertices):
        for distance in (1, 2):
            a, b = canonical(u, (u + distance) % vertices)
            if (a, b) not in removed:
                if not engine.has_edge(a, b) or (
                    partners[a] == partners[b] == 0xFFFFFFFF
                ):
                    raise RuntimeError(
                        "independent exact ring-edge/maximality audit failed"
                    )
                expected_count += 1
    for u, v in extra:
        if not engine.has_edge(u, v) or (partners[u] == partners[v] == 0xFFFFFFFF):
            raise RuntimeError(
                "independent exact inserted-edge/maximality audit failed"
            )
        expected_count += 1
    if expected_count != engine.num_edges():
        raise RuntimeError("independent exact graph count failed")
    audit = time.perf_counter() - started
    samples = {}
    for name, values in durations.items():
        ordered = sorted(values)
        samples[name] = {
            "calls": len(values),
            "p99_ns": ordered[(99 * len(values) + 99) // 100 - 1],
            "max_ns": ordered[-1],
        }
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "native graph + maximal matching + queries; NO durable acknowledgments",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "vertices": vertices,
        "edges": engine.num_edges(),
        "average_degree": 4,
        "pairs": pairs,
        "seed": seed,
        "digest": digest.hexdigest(),
        "real_updates": 2 * pairs,
        "partner_queries": pairs,
        "matched_deletes": matched_deletes,
        "construction_seconds": construction,
        "trace_seconds": elapsed,
        "real_updates_per_second": 2 * pairs / elapsed,
        "audit_seconds": audit,
        "independent_audit_passed": True,
        "initial_native_memory": initial_memory,
        "final_native_memory": final_memory,
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "latency": samples,
    }


def main() -> None:
    """Print one native in-memory measurement with explicit scope and certificates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertices", type=int, default=1_000_000)
    parser.add_argument("--pairs", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=599)
    parser.add_argument("--budget", type=int, default=1 << 30)
    args = parser.parse_args()
    print(
        json.dumps(measure(args.vertices, args.pairs, args.seed, args.budget), indent=2)
    )


if __name__ == "__main__":
    main()
