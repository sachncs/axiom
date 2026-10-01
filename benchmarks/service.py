"""Measure bounded concurrent clients, FULL-WAL acknowledgments and partner reads.

Streaming histograms include queue wait and native checkpoint maintenance. The
fixed-pool closed-loop workload is not an open-loop overload or power-cut test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import resource
import sys
import threading
import time
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import Durable, Request
from axiom.service import Service
from benchmarks.durable import canonical, certificate


class Histogram:
    """Bound latency storage; report conservative 100us p99 buckets and exact max."""

    def __init__(self) -> None:
        """Allocate fixed counters, not one Python object per observed latency."""
        self.bins = array("Q", [0]) * 10001
        self.count = self.maximum = 0

    def record(self, nanoseconds: int) -> None:
        """Count one sample; last bucket is explicit overflow at >=1 second."""
        self.bins[min(nanoseconds // 100000, 10000)] += 1
        self.count += 1
        self.maximum = max(self.maximum, nanoseconds)

    def merge(self, other: Histogram) -> None:
        """Combine independently owned thread histograms after joining."""
        for index, count in enumerate(other.bins):
            self.bins[index] += count
        self.count += other.count
        self.maximum = max(self.maximum, other.maximum)

    def summary(self) -> dict:
        """Return upper-bound p99, or None if empty or percentile overflowed."""
        total, bound = 0, None
        rank = (99 * self.count + 99) // 100
        for index, count in enumerate(self.bins):
            total += count
            if rank and total >= rank:
                bound = (index + 1) * 100000 if index < 10000 else None
                break
        return {
            "count": self.count,
            "p99_upper_ns": bound,
            "max_ns": self.maximum,
            "overflow_at_1s": self.bins[-1],
            "resolution_ns": 100000,
        }


def live_digest(service: Service, vertices: int, status: dict) -> str:
    """Capture exact live partners through bounded coherent matching pages."""
    if not service.check().result(10):
        raise RuntimeError("live native audit failed")
    partners = array("I", [0xFFFFFFFF]) * vertices
    start, count, version = 0, 0, status["version"]
    while True:
        current, edges, following = service.page(start, 4096, version).result(10)
        if current != version:
            raise RuntimeError("live matching page version mismatch")
        for u, v in edges:
            if (
                not 0 <= u < v < vertices
                or partners[u] != 0xFFFFFFFF
                or partners[v] != 0xFFFFFFFF
            ):
                raise RuntimeError("live proper matching page certificate failed")
            partners[u], partners[v] = v, u
            count += 1
        if following is None:
            break
        if not start < following <= vertices:
            raise RuntimeError("matching page failed to advance")
        start = following
    if count != status["matching"]:
        raise RuntimeError("live matching count mismatch")
    if sys.byteorder != "little":
        partners.byteswap()
    return hashlib.sha256(partners.tobytes()).hexdigest()


def measure(
    path: Path,
    vertices: int,
    pairs: int,
    seed: int,
    *,
    clients: int = 4,
    window: int = 64,
    query_window: int = 128,
    queue_capacity: int = 512,
    checkpoint_interval: int = 32768,
    timeout_seconds: int = 120,
    duration_seconds: int | None = None,
    hub_degree: int = 0,
) -> dict:
    """Stream bounded client windows; preserve exact topology and recovered partners."""
    if (
        vertices < 8
        or type(hub_degree) is not int
        or (hub_degree != 0 and not 6 <= hub_degree <= min(vertices - 3, 262144))
        or not 1 <= pairs <= 100000000
        or not 1 <= clients <= 16
        or not 2 <= window <= 256
        or window % 2
        or not 1 <= query_window <= 256
        or queue_capacity < clients * window + query_window
        or not 1 <= timeout_seconds <= 3600
        or (
            duration_seconds is not None
            and (
                not 1 <= duration_seconds <= 3590
                or timeout_seconds < duration_seconds + 10
            )
        )
    ):
        raise ValueError("invalid bounded client/query/workload envelope")
    if path.exists():
        raise ValueError("benchmark requires a fresh database path")
    rng, query_rng = random.Random(seed), random.Random(seed + 1)
    width = min(vertices, 8192)
    originals = [
        canonical(u, (u + 1) % vertices) for u in rng.sample(range(vertices), width)
    ]
    extras, unique = [], set()
    while len(extras) < width:
        u, v = sorted(rng.sample(range(vertices), 2))
        if 2 < v - u < vertices - 2 and (u, v) not in unique:
            unique.add((u, v))
            extras.append((u, v))
    if hub_degree:
        # Ring neighbors are 1,2,n-2,n-1. Add exactly degree-4 non-ring
        # neighbors; the churn chord sits just outside that hub neighborhood.
        width, originals, extras = 1, [(0, 1)], [(0, hub_degree - 1)]
    toggled, trace = [False] * width, hashlib.sha256()
    admission, writers_done, failed = (
        threading.Condition(),
        threading.Event(),
        threading.Event(),
    )
    barrier = threading.Barrier(clients + 2)
    completed_pairs, retry_checks, disk_peak = 0, 0, 0
    failures: list[BaseException] = []
    writer_histograms = [[Histogram() for _ in range(3)] for _ in range(clients)]
    read_histograms = [Histogram() for _ in range(3)]
    query_while_writers_active = 0
    tick = time.perf_counter()
    service = Service(
        path,
        n=vertices,
        queue_capacity=queue_capacity,
        checkpoint_interval=checkpoint_interval,
    )
    construction = time.perf_counter() - tick
    hub_edges = {(0, v) for v in range(3, hub_degree - 1)} if hub_degree else set()
    tick = time.perf_counter()
    bootstrap = 0
    try:
        chunk = min(256, queue_capacity)
        for start in range(3, hub_degree - 1, chunk):
            requests = [
                Request(bootstrap + offset + 1, "insert", 0, v)
                for offset, v in enumerate(
                    range(start, min(start + chunk, hub_degree - 1))
                )
            ]
            receipts = [service.submit(request) for request in requests]
            if any(not receipt.result(30).changed for receipt in receipts):
                raise RuntimeError("hub bootstrap contains non-real transitions")
            bootstrap += len(requests)
        hub_setup = time.perf_counter() - tick
        initial = service.status().result(10)
    except BaseException:
        service.close(10)
        raise
    deadline = time.monotonic() + timeout_seconds
    run_until: float | None = None

    def wait_seconds() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("concurrent trace exceeded its watchdog")
        return min(remaining, 30)

    def record(receipt: object, admitted: int, histograms: list[Histogram]) -> object:
        outcome = receipt.result(wait_seconds())
        observed, timing = time.perf_counter_ns(), receipt.timing()
        if timing is None:
            raise RuntimeError("completed receipt lacks timing")
        histograms[0].record(observed - admitted)
        histograms[1].record(timing.started_ns - timing.admitted_ns)
        histograms[2].record(timing.completed_ns - timing.started_ns)
        return outcome

    def writer(client: int) -> None:
        nonlocal completed_pairs, retry_checks, disk_peak
        try:
            barrier.wait(timeout=10)
            while not failed.is_set():
                pending = []
                with admission:
                    first = completed_pairs
                    count = min(window // 2, pairs - completed_pairs)
                    if run_until is not None and time.monotonic() >= run_until:
                        count = 0  # Stop new admission, not accepted work.
                    for offset in range(count):
                        cell = rng.randrange(width)
                        old, new = (
                            (extras[cell], originals[cell])
                            if toggled[cell]
                            else (originals[cell], extras[cell])
                        )
                        for index, (operation, (u, v)) in enumerate(
                            (("delete", old), ("insert", new))
                        ):
                            seq = bootstrap + 2 * (completed_pairs + offset) + index + 1
                            request = Request(seq, operation, u, v)
                            admitted = time.perf_counter_ns()
                            receipt = service.submit(request)
                            pending.append((request, receipt, admitted))
                            trace.update(f"{seq}:{operation}:{u}:{v};".encode())
                        toggled[cell] = not toggled[cell]
                    completed_pairs += count
                    admission.notify_all()
                if not count:
                    break
                outcomes = []
                for request, receipt, admitted in pending:
                    outcome = record(receipt, admitted, writer_histograms[client])
                    if not outcome.changed or outcome.version != request.sequence + 1:
                        raise RuntimeError(
                            "expected a real durably acknowledged update"
                        )
                    outcomes.append(outcome)
                if first % 4096 == 0:
                    retries = [service.submit(request) for request, _, _ in pending]
                    if [
                        receipt.result(wait_seconds()) for receipt in retries
                    ] != outcomes:
                        raise RuntimeError("concurrent retry changed original outcomes")
                    with admission:
                        retry_checks += len(retries)
                if client == 0:
                    disk_peak = max(
                        disk_peak,
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
        except BaseException as error:
            failures.append(error)
            failed.set()

    def reader() -> None:
        nonlocal query_while_writers_active
        previous = bootstrap + 1
        try:
            barrier.wait(timeout=10)
            while not failed.is_set():
                # Fixed 1:1 query/update mix, independent of query execution speed.
                # Unrestricted fast reads would silently change offered work and
                # CPU contention compared with the earlier queued-read benchmark.
                with admission:
                    while (
                        read_histograms[0].count == 2 * completed_pairs
                        and not writers_done.is_set()
                        and not failed.is_set()
                    ):
                        admission.wait(0.1)
                    count = min(
                        query_window, 2 * completed_pairs - read_histograms[0].count
                    )
                if not count:
                    break
                pending = []
                for _ in range(count):
                    vertex = query_rng.randrange(vertices)
                    admitted = time.perf_counter_ns()
                    pending.append((vertex, service.partner(vertex), admitted))
                for vertex, receipt, admitted in pending:
                    version, partner = record(receipt, admitted, read_histograms)
                    if not previous <= version <= bootstrap + 2 * pairs + 1 or (
                        partner is not None
                        and (not 0 <= partner < vertices or partner == vertex)
                    ):
                        raise RuntimeError("incoherent concurrent partner query")
                    previous = version
                    query_while_writers_active += not writers_done.is_set()
        except BaseException as error:
            failures.append(error)
            failed.set()

    workers = [
        threading.Thread(target=writer, args=(client,), daemon=True)
        for client in range(clients)
    ]
    query_worker = threading.Thread(target=reader, daemon=True)
    try:
        for worker in workers + [query_worker]:
            worker.start()
        started = time.perf_counter()
        deadline = time.monotonic() + timeout_seconds
        if duration_seconds is not None:
            run_until = time.monotonic() + duration_seconds
        barrier.wait(timeout=10)
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))
        with admission:
            writers_done.set()
            admission.notify_all()
        query_worker.join(max(0, deadline - time.monotonic()))
        if any(worker.is_alive() for worker in workers + [query_worker]):
            raise TimeoutError("bounded concurrent clients did not finish")
        if failures:
            raise failures[0]
        elapsed = time.perf_counter() - started
        final, metrics = service.status().result(10), service.metrics()
        if (
            final["sequence"] != bootstrap + 2 * completed_pairs
            or metrics["outstanding"]
        ):
            raise RuntimeError("not all admitted updates completed")
        tick = time.perf_counter()
        matching_digest = live_digest(service, vertices, final)
        live_audit = time.perf_counter() - tick
    finally:
        failed.set()
        with admission:
            writers_done.set()
            admission.notify_all()
        service.close(10)
    removed = {originals[i] for i in range(width) if toggled[i]}
    extra = hub_edges | {extras[i] for i in range(width) if toggled[i]}
    tick = time.perf_counter()
    with Durable(path) as recovered:
        recovery = time.perf_counter() - tick
        tick = time.perf_counter()
        if (
            recovered.status()["sequence"] != bootstrap + 2 * completed_pairs
            or certificate(recovered, extra, removed, vertices) != matching_digest
        ):
            raise RuntimeError(
                "independent recovery topology/matching certificate failed"
            )
        recovery_audit = time.perf_counter() - tick
    acknowledgments, queues, executions = Histogram(), Histogram(), Histogram()
    for group in writer_histograms:
        for combined, item in zip(
            (acknowledgments, queues, executions), group, strict=True
        ):
            combined.merge(item)
    if acknowledgments.count != 2 * completed_pairs:
        raise RuntimeError("acknowledged update count differs from trace")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "bounded closed-loop clients + committed partner reads (1:1 query/update mix) + FULL-WAL + native checkpoint retirement; NOT open-loop overload/power-cut qualification",
        "query_policy": "one partner query per admitted real update; drain all credits",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": final["sqlite"],
        "vertices": vertices,
        "edges": initial["edges"],
        "average_degree": 2 * initial["edges"] / vertices,
        "hub_initial_degree": hub_degree,
        "hub_bootstrap_real_updates": bootstrap,
        "hub_setup_seconds": hub_setup,
        "seed": seed,
        "churn_pool_pairs": width,
        "clients": clients,
        "client_update_window": window,
        "query_window": query_window,
        "queue_capacity": queue_capacity,
        "real_acknowledged_updates": acknowledgments.count,
        "partner_queries": read_histograms[0].count,
        "queries_completed_while_writers_active": query_while_writers_active,
        "retry_outcomes_verified": retry_checks,
        "construction_seconds": construction,
        "requested_pair_ceiling": pairs,
        "requested_duration_seconds": duration_seconds,
        "requested_duration_completed": duration_seconds is not None
        and elapsed >= duration_seconds,
        "trace_seconds": elapsed,
        "real_acknowledged_updates_per_second": acknowledgments.count / elapsed,
        "live_audit_seconds": live_audit,
        "recovery_seconds": recovery,
        "recovery_audit_seconds": recovery_audit,
        "independent_audit_passed": True,
        "exact_recovery_passed": True,
        "trace_digest": trace.hexdigest(),
        "matching_digest": matching_digest,
        "initial_native_bytes": initial["native_bytes"],
        "final_native_bytes": final["native_bytes"],
        "sampled_database_wal_shm_peak_bytes": disk_peak,
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "final_status": final,
        "service_metrics": metrics,
        "acknowledged_latency": acknowledgments.summary(),
        "update_queue_wait": queues.summary(),
        "update_execution": executions.summary(),
        "partner_query_latency": read_histograms[0].summary(),
        "query_queue_wait": read_histograms[1].summary(),
        "query_execution": read_histograms[2].summary(),
    }


def main() -> None:
    """Print one streaming measurement; leave its database available for inspection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=32000)
    parser.add_argument("--pairs", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=599)
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--window", type=int, default=64)
    parser.add_argument("--query-window", type=int, default=128)
    parser.add_argument("--queue-capacity", type=int, default=512)
    parser.add_argument("--checkpoint-interval", type=int, default=32768)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--duration", type=int)
    parser.add_argument("--hub-degree", type=int, default=0)
    args = parser.parse_args()
    print(
        json.dumps(
            measure(
                args.database,
                args.vertices,
                args.pairs,
                args.seed,
                clients=args.clients,
                window=args.window,
                query_window=args.query_window,
                queue_capacity=args.queue_capacity,
                checkpoint_interval=args.checkpoint_interval,
                timeout_seconds=args.timeout,
                duration_seconds=args.duration,
                hub_degree=args.hub_degree,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
