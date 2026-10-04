"""Measure real paper-mode edge updates and verify their durable replay.

This local benchmark reports accepted updates, partner-query latency, and
recovery cost. It is a repeatable workload, not network or power-loss
qualification. Use a fresh database for each run.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import Durable, Request
from axiom.service import Service


def measure(
    path: Path,
    vertices: int = 10000,
    updates: int = 1000,
    *,
    mode: str = "basic",
    batch: int = 32,
) -> dict:
    """Run alternating real deletes/inserts through Service and audit replay."""
    if (
        type(vertices) is not int
        or vertices < 8
        or vertices % 2
        or type(updates) is not int
        or not 1 <= updates <= 1_000_000
        or type(batch) is not int
        or not 1 <= batch <= 256
        or mode not in ("basic", "multilevel")
    ):
        raise ValueError("invalid paper-mode load envelope")
    if path.exists():
        raise ValueError("benchmark requires a fresh database")
    latencies: list[int] = []
    query_latencies: list[int] = []
    service = Service(path, n=vertices, mode=mode, max_batch=batch)
    started = time.perf_counter_ns()
    try:
        completed = 0
        while completed < updates:
            count = min(batch, updates - completed)
            requests, admitted = [], []
            for offset in range(count):
                sequence = completed + offset + 1
                action, edge = (
                    ("delete", (0, 1)),
                    ("insert", (0, 3)),
                    ("delete", (0, 3)),
                    ("insert", (0, 1)),
                )[(sequence - 1) % 4]
                requests.append(Request(sequence, action, *edge))
                admitted.append(time.perf_counter_ns())
            outcomes = service.submit_batch(requests).result(60)
            acknowledged = time.perf_counter_ns()
            if any(
                not result.changed or result.version != result.sequence + 1
                for result in outcomes
            ):
                raise RuntimeError("workload did not produce real committed edits")
            latencies.extend(acknowledged - item for item in admitted)
            completed += count
            query_started = time.perf_counter_ns()
            version, partner = service.partner(0).result(30)
            query_latencies.append(time.perf_counter_ns() - query_started)
            if version != completed + 1:
                raise RuntimeError("partner query disagrees with acknowledged prefix")
            last_partner = partner
        status = service.status().result(30)
        if status["sequence"] != updates or status["mode"] != mode:
            raise RuntimeError("service status disagrees with completed workload")
    finally:
        service.close(60)
    elapsed = time.perf_counter_ns() - started
    recovery_started = time.perf_counter_ns()
    with Durable(path, mode=mode) as recovered:
        recovery_ns = time.perf_counter_ns() - recovery_started
        if not recovered.check() or recovered.status()["sequence"] != updates:
            raise RuntimeError("paper-mode replay recovery failed audit")
        if recovered.partner(0) != (updates + 1, last_partner):
            raise RuntimeError("recovered matching differs from committed state")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "local Service workload and Durable replay; not network or power-loss qualification",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mode": mode,
        "vertices": vertices,
        "updates": updates,
        "batch": batch,
        "elapsed_seconds": elapsed / 1e9,
        "acknowledged_updates_per_second": updates / (elapsed / 1e9),
        "ack_latency_ns": {
            "p50": sorted(latencies)[len(latencies) // 2],
            "max": max(latencies),
        },
        "partner_query_latency_ns": {
            "p50": sorted(query_latencies)[len(query_latencies) // 2],
            "max": max(query_latencies),
        },
        "recovery_seconds": recovery_ns / 1e9,
        "recovery_audit_passed": True,
        "final_status": status,
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
    }


def main() -> None:
    """Print one bounded paper-mode workload report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=10000)
    parser.add_argument("--updates", type=int, default=1000)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--mode", choices=("basic", "multilevel"), default="basic")
    args = parser.parse_args()
    print(
        json.dumps(
            measure(
                args.database,
                args.vertices,
                args.updates,
                mode=args.mode,
                batch=args.batch,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
