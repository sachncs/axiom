"""Measure paper-matcher updates committed by SQLite FULL-WAL.

The trace measures durable grouped acknowledgments, committed partner reads,
and replay recovery. It is not a production soak or concurrent-client test.
Use a fresh process and a dedicated local database path.
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
from collections.abc import Iterable, Sized
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import Durable, Request


def canonical(u: int, v: int) -> tuple[int, int]:
    """Return one canonical undirected edge."""
    return min(u, v), max(u, v)


def certificate(
    store: Durable,
    extra: Iterable[tuple[int, int]],
    removed: set,
    vertices: int,
    width: int = 2,
    *,
    size: int | None = None,
) -> str:
    """Certify topology/matching; counted streams must be strictly sorted chords."""
    if type(width) is not int or not 1 <= width < vertices // 2:
        raise ValueError("require an unambiguous ring width")
    streamed = size is not None or not isinstance(extra, (set, frozenset))
    if size is None:
        if not isinstance(extra, Sized):
            raise ValueError("streamed extras require an explicit size")
        size = len(extra)
    if type(size) is not int or size < 0:
        raise ValueError("require a nonnegative extra edge count")
    if not store.check() or store.status()["edges"] != (
        width * vertices + size - len(removed)
    ):
        raise RuntimeError("paper audit/edge count failed")
    version = store.status()["version"]
    partners = array("I")
    digest = hashlib.sha256()
    for u in range(vertices):
        current, partner = store.partner(u)
        if current != version:
            raise RuntimeError("query version disagreement")
        value = partner if partner is not None else 0xFFFFFFFF
        partners.append(value)
        digest.update(value.to_bytes(4, "little"))
    matched = 0
    for u, v in enumerate(partners):
        if v != 0xFFFFFFFF:
            if (
                v >= vertices
                or v == u
                or partners[v] != u
                or store.has_edge(u, v) != (version, True)
            ):
                raise RuntimeError("independent proper-matching certificate failed")
            matched += u < v
    if matched != store.status()["matching"]:
        raise RuntimeError("independent matching count failed")
    count = 0
    for u in range(vertices):
        for distance in range(1, width + 1):
            a, b = canonical(u, (u + distance) % vertices)
            if (a, b) not in removed:
                if (
                    store.has_edge(a, b) != (version, True)
                    or partners[a] == partners[b] == 0xFFFFFFFF
                ):
                    raise RuntimeError("independent ring topology/maximality failed")
                count += 1
    previous = None
    for a, b in extra:
        if (
            not 0 <= a < b < vertices
            or min(b - a, vertices - (b - a)) <= width
            or (streamed and previous is not None and (a, b) <= previous)
        ):
            raise RuntimeError("invalid or repeated extra topology reference")
        previous = a, b
        if (
            store.has_edge(a, b) != (version, True)
            or partners[a] == partners[b] == 0xFFFFFFFF
        ):
            raise RuntimeError("independent extra topology/maximality failed")
        count += 1
    if count != store.status()["edges"]:
        raise RuntimeError("independent exact graph certificate failed")
    return digest.hexdigest()


def measure(
    path: Path,
    vertices: int,
    pairs: int,
    batch: int,
    seed: int,
    *,
    mode: str = "basic",
    workload: str = "uniform",
    hub_degree: int = 0,
) -> dict:
    """Churn a stable edge pool, acknowledge every real edit, and verify recovery."""
    limit = 32768
    if vertices < 8 or not 1 <= pairs <= limit or not 2 <= batch <= 4096 or batch % 2:
        raise ValueError(
            f"require n>=8, 1<=pairs<={limit} and an even batch in [2,4096]"
        )
    if workload not in ("uniform", "hub-churn"):
        raise ValueError("workload must be 'uniform' or 'hub-churn'")
    if type(hub_degree) is not int or hub_degree < 0:
        raise ValueError("hub_degree must be a nonnegative integer")
    if workload == "uniform" and hub_degree:
        raise ValueError("hub_degree is only valid for hub-churn")
    if workload == "hub-churn" and hub_degree < 1:
        raise ValueError("hub-churn requires at least one preloaded hub edge")
    if path.exists():
        raise ValueError("benchmark requires a fresh database path")
    rng = random.Random(seed)
    width = min(vertices, 8192)
    if workload == "hub-churn":
        width = min(width, vertices - 5 - hub_degree)
        if width < 1:
            raise ValueError("hub_degree leaves no distinct non-ring churn spokes")
        hubedges = [(0, vertex) for vertex in range(3, hub_degree + 3)]
        hotextras = [
            (0, vertex) for vertex in range(hub_degree + 3, hub_degree + width + 3)
        ]
    else:
        hubedges = []
        hotextras = []
    originals = [
        canonical(u, (u + 1) % vertices) for u in rng.sample(range(vertices), width)
    ]
    extras: list[tuple[int, int]] = []
    unique: set[tuple[int, int]] = set()
    if workload == "hub-churn":
        extras = hotextras
        unique.update(extras)
    else:
        while len(extras) < width:
            u, v = sorted(rng.sample(range(vertices), 2))
            if 2 < v - u < vertices - 2 and (u, v) not in unique:
                unique.add((u, v))
                extras.append((u, v))
    toggled = [False] * width
    digest = hashlib.sha256()
    latencies: list[int] = []
    batch_latencies: list[int] = []
    query_latencies: list[int] = []
    sampled_disk_peak = 0
    retry_checks = 0
    tick = time.perf_counter()
    store = Durable(path, n=vertices, mode=mode, max_batch=batch, width=2)
    construction = time.perf_counter() - tick
    setup_seconds = 0.0
    setup_count = 0
    try:
        if hubedges:
            tick = time.perf_counter()
            for offset in range(0, len(hubedges), batch):
                group = hubedges[offset : offset + batch]
                requests = [
                    Request(
                        setup_count + index + 1,
                        "insert",
                        left,
                        right,
                    )
                    for index, (left, right) in enumerate(group)
                ]
                outcomes = store.apply(requests)
                if any(
                    not outcome.changed
                    or outcome.sequence != setup_count + index + 1
                    or outcome.version != setup_count + index + 2
                    for index, outcome in enumerate(outcomes)
                ):
                    raise RuntimeError("hub preload acknowledgment is invalid")
                for request in requests:
                    digest.update(
                        f"{request.sequence}:insert:{request.u}:{request.v};".encode()
                    )
                setup_count += len(group)
            setup_seconds = time.perf_counter() - tick
        initial = store.status()
        started = time.perf_counter()
        completed = 0
        while completed < pairs:
            requests, admitted = [], []
            current_pairs = min(batch // 2, pairs - completed)
            for index in range(current_pairs):
                cell = rng.randrange(width)
                old, new = (
                    (extras[cell], originals[cell])
                    if toggled[cell]
                    else (originals[cell], extras[cell])
                )
                for offset, (operation, (u, v)) in enumerate(
                    (("delete", old), ("insert", new))
                ):
                    sequence = setup_count + 2 * (completed + index) + offset + 1
                    requests.append(Request(sequence, operation, u, v))
                    admitted.append(time.perf_counter_ns())
                    digest.update(f"{sequence}:{operation}:{u}:{v};".encode())
                toggled[cell] = not toggled[cell]
            tick_ns = time.perf_counter_ns()
            outcomes = store.apply(requests)
            acknowledged = time.perf_counter_ns()
            batch_latencies.append(acknowledged - tick_ns)
            latencies.extend(acknowledged - entry for entry in admitted)
            for outcome in outcomes:
                if not outcome.changed or outcome.version != outcome.sequence + 1:
                    raise RuntimeError(
                        "expected a durably acknowledged real transition"
                    )
            for _ in range(current_pairs):
                vertex = rng.randrange(vertices)
                tick_ns = time.perf_counter_ns()
                version, _ = store.partner(vertex)
                query_latencies.append(time.perf_counter_ns() - tick_ns)
                if version != outcomes[-1].version:
                    raise RuntimeError("matching query returned incoherent version")
            if completed % 4096 == 0:
                if store.apply(requests) != outcomes:
                    raise RuntimeError("retry changed the acknowledged result")
                retry_checks += len(requests)
            completed += current_pairs
            sampled_disk_peak = max(
                sampled_disk_peak,
                sum(
                    candidate.stat().st_size
                    for candidate in (
                        path,
                        Path(str(path) + "-wal"),
                        Path(str(path) + "-shm"),
                    )
                    if candidate.exists()
                ),
            )
        elapsed = time.perf_counter() - started
        final = store.status()
        removed = {originals[i] for i in range(width) if toggled[i]}
        extra = set(hubedges)
        extra.update(extras[i] for i in range(width) if toggled[i])
        tick = time.perf_counter()
        matching_digest = certificate(store, extra, removed, vertices)
        audit = time.perf_counter() - tick
    finally:
        store.close()
    tick = time.perf_counter()
    with Durable(path, mode=mode) as recovered:
        recovery = time.perf_counter() - tick
        tick = time.perf_counter()
        if (
            recovered.status()["sequence"] != setup_count + 2 * pairs
            or recovered.status()["version"] != setup_count + 2 * pairs + 1
        ):
            raise RuntimeError(
                "recovery sequence/version disagrees with acknowledgments"
            )
        if certificate(recovered, extra, removed, vertices) != matching_digest:
            raise RuntimeError("recovery changed exact deterministic matching")
        if recovered.apply(requests) != outcomes:
            raise RuntimeError("recovery changed retained retry outcomes")
        recovery_audit = time.perf_counter() - tick
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    def summary(values: list[int]) -> dict[str, int]:
        ordered = sorted(values)
        return {
            "count": len(values),
            "p99_ns": ordered[(99 * len(values) + 99) // 100 - 1],
            "max_ns": ordered[-1],
        }

    return {
        "scope": "paper matcher + SQLite FULL-WAL group commits, partner queries, and operation-log replay; NOT soak/concurrent-client qualification",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": final["sqlite"],
        "paper_mode": mode,
        "vertices": vertices,
        "base_edges": 2 * vertices,
        "edges": initial["edges"],
        "final_edges": final["edges"],
        "average_degree": 2 * initial["edges"] / vertices,
        "workload": workload,
        "hub_vertex": 0 if workload == "hub-churn" else None,
        "preloaded_hub_degree": hub_degree,
        "churn_hub_pool_size": width if workload == "hub-churn" else 0,
        "initial_hub_degree": 4 + hub_degree if workload == "hub-churn" else None,
        "churn_pool_pairs": width,
        "seed": seed,
        "pairs": pairs,
        "batch_limit": batch,
        "operation_history_entries": final["history_operations"],
        "operation_history_limit": final["max_operations"],
        "retry_recovery_passed": True,
        "synchronous": "FULL",
        "fullfsync": True,
        "preload_updates": setup_count,
        "preload_seconds": setup_seconds,
        "real_acknowledged_updates": 2 * pairs,
        "partner_queries": pairs,
        "retry_outcomes_verified": retry_checks,
        "trace_digest": digest.hexdigest(),
        "matching_digest": matching_digest,
        "construction_seconds": construction,
        "trace_seconds": elapsed,
        "real_acknowledged_updates_per_second": 2 * pairs / elapsed,
        "audit_seconds": audit,
        "recovery_seconds": recovery,
        "recovery_audit_seconds": recovery_audit,
        "independent_audit_passed": True,
        "exact_recovery_passed": True,
        "initial_paper_graph_bytes": initial["graph_bytes"],
        "final_paper_graph_bytes": final["graph_bytes"],
        "sampled_database_wal_shm_peak_bytes": sampled_disk_peak,
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "acknowledged_latency": summary(latencies),
        "batch_commit_publication_latency": summary(batch_latencies),
        "partner_query_latency": summary(query_latencies),
    }


def main() -> None:
    """Print one bounded durable measurement; leave its database for inspection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=32000)
    parser.add_argument("--pairs", type=int, default=20000)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--seed", type=int, default=599)
    parser.add_argument("--mode", choices=("basic", "multilevel"), default="basic")
    parser.add_argument(
        "--workload", choices=("uniform", "hub-churn"), default="uniform"
    )
    parser.add_argument("--hub-degree", type=int, default=0)
    args = parser.parse_args()
    print(
        json.dumps(
            measure(
                args.database,
                args.vertices,
                args.pairs,
                args.batch,
                args.seed,
                mode=args.mode,
                workload=args.workload,
                hub_degree=args.hub_degree,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
