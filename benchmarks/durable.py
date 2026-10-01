"""Measure acknowledged FULL-WAL native updates with committed partner queries.

The default short v1 trace includes SQLite WAL checkpoints. Explicit v2 traces
also include native checkpoint/history retirement. Neither is a production soak
or concurrent-client qualification. Use a fresh process and dedicated local path.
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

from axiom.durable import Durable, ExpiredError, Request


def canonical(u: int, v: int) -> tuple[int, int]:
    """Return one canonical undirected edge."""
    return min(u, v), max(u, v)


def certificate(store: Durable, extra: set, removed: set, vertices: int) -> str:
    """Independently verify exact topology, proper maximal matching, and its digest."""
    if not store.check() or store.status()["edges"] != 2 * vertices + len(extra) - len(
        removed
    ):
        raise RuntimeError("native audit/edge count failed")
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
        for distance in (1, 2):
            a, b = canonical(u, (u + distance) % vertices)
            if (a, b) not in removed:
                if (
                    store.has_edge(a, b) != (version, True)
                    or partners[a] == partners[b] == 0xFFFFFFFF
                ):
                    raise RuntimeError("independent ring topology/maximality failed")
                count += 1
    for a, b in extra:
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
    checkpoint_interval: int | None = None,
) -> dict:
    """Churn a stable edge pool, acknowledge every real edit, and verify recovery."""
    limit = 250000 if checkpoint_interval is not None else 32768
    if vertices < 8 or not 1 <= pairs <= limit or not 2 <= batch <= 256 or batch % 2:
        raise ValueError(
            f"require n>=8, 1<=pairs<={limit} and an even batch in [2,256]"
        )
    if path.exists():
        raise ValueError("benchmark requires a fresh database path")
    rng = random.Random(seed)
    width = min(vertices, 8192)
    originals = [
        canonical(u, (u + 1) % vertices) for u in rng.sample(range(vertices), width)
    ]
    extras: list[tuple[int, int]] = []
    unique: set[tuple[int, int]] = set()
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
    store = Durable(path, n=vertices, checkpoint_interval=checkpoint_interval)
    construction = time.perf_counter() - tick
    initial = store.status()
    try:
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
                    sequence = 2 * (completed + index) + offset + 1
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
        extra = {extras[i] for i in range(width) if toggled[i]}
        tick = time.perf_counter()
        matching_digest = certificate(store, extra, removed, vertices)
        audit = time.perf_counter() - tick
    finally:
        store.close()
    tick = time.perf_counter()
    with Durable(path) as recovered:
        recovery = time.perf_counter() - tick
        tick = time.perf_counter()
        if (
            recovered.status()["sequence"] != 2 * pairs
            or recovered.status()["version"] != 2 * pairs + 1
        ):
            raise RuntimeError(
                "recovery sequence/version disagrees with acknowledgments"
            )
        if certificate(recovered, extra, removed, vertices) != matching_digest:
            raise RuntimeError("recovery changed exact deterministic matching")
        if recovered.apply(requests) != outcomes:
            raise RuntimeError("recovery changed retained retry outcomes")
        if final["retired_floor"]:
            try:
                recovered.apply([Request(1, "delete", *originals[0])])
            except ExpiredError:
                pass
            else:
                raise RuntimeError("recovered retired ID did not expire")
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
        "scope": (
            "FULL-WAL durable group commits + committed partner queries + "
            "SQLite WAL checkpoints + native checkpoint/retirement; "
            "NOT soak/concurrent-client qualification"
            if checkpoint_interval is not None
            else "FULL-WAL durable group commits + committed partner queries + "
            "SQLite WAL checkpoints; NOT native checkpoint/soak qualification"
        ),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": final["sqlite"],
        "vertices": vertices,
        "edges": 2 * vertices,
        "average_degree": 4,
        "churn_pool_pairs": width,
        "seed": seed,
        "pairs": pairs,
        "batch_limit": batch,
        "checkpoint_interval": final["checkpoint_interval"],
        "checkpoint_generation": final["checkpoint_generation"],
        "checkpoint_sequence": final["checkpoint_sequence"],
        "retired_floor": final["retired_floor"],
        "retained_operations": final["retained_operations"],
        "retained_retry_recovery_passed": True,
        "expired_retry_recovery_verified": bool(final["retired_floor"]),
        "synchronous": "FULL",
        "fullfsync": True,
        "checkpoint_fullfsync": True,
        "wal_autocheckpoint_pages": 256,
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
        "initial_native_bytes": initial["native_bytes"],
        "final_native_bytes": final["native_bytes"],
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
    parser.add_argument("--checkpoint-interval", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            measure(
                args.database,
                args.vertices,
                args.pairs,
                args.batch,
                args.seed,
                checkpoint_interval=args.checkpoint_interval,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
