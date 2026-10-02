"""Paced offered load with explicit saturation and producer scheduling losses.

Offers do not wait for acknowledgments. Completed/rejected/missed work is counted
separately; skipped scheduling slots cannot inflate delivered throughput.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import BusyError, Durable, Request
from axiom.service import Service
from benchmarks.durable import certificate
from benchmarks.service import Histogram, live_digest


class Schedule:
    """Generate scheduled arrivals, counting missed slots instead of catch-up bursts."""

    def __init__(self, started: int, rate: int, seconds: int, stop: threading.Event):
        """Keep constant-size schedule state independent of operation count."""
        self.started, self.rate, self.stop = started, rate, stop
        self.total, self.end = rate * seconds, started + seconds * 1_000_000_000
        self.missed = 0

    def __iter__(self):
        """Yield intended arrival timestamps; never block on operation outcomes."""
        index = 0
        while index < self.total and not self.stop.is_set():
            now = time.perf_counter_ns()
            if now >= self.end:
                break
            due = self.started + index * 1_000_000_000 // self.rate
            if now < due:
                self.stop.wait((due - now) / 1_000_000_000)
                continue
            latest = min(
                self.total - 1,
                ((now - self.started + 1) * self.rate - 1) // 1_000_000_000,
            )
            self.missed += latest - index
            index = latest
            yield self.started + index * 1_000_000_000 // self.rate
            index += 1
        self.missed += self.total - index


def measure(
    path: Path,
    vertices: int,
    rate: int,
    seconds: int,
    *,
    query_rate: int = 1000,
    queue_capacity: int = 512,
) -> dict:
    """Offer hot-edge changes independently of completion, then audit exact recovery."""
    if (
        any(
            type(value) is not int
            for value in (vertices, rate, seconds, query_rate, queue_capacity)
        )
        or not 8 <= vertices <= 1000000
        or vertices % 2
        or not 10 <= rate <= 100000
        or not 1 <= seconds <= 60
        or not 10 <= query_rate <= 10000
        or not 2 <= queue_capacity <= 4096
    ):
        raise ValueError("invalid bounded offered-load envelope")
    if path.exists():
        raise ValueError("benchmark requires a fresh database path")
    service = Service(path, n=vertices, queue_capacity=queue_capacity)
    stop = threading.Event()
    pending, failures = deque(), []
    ack, offered_ack, queue, execution, queries = [Histogram() for _ in range(5)]
    accepted = rejected = query_rejected = query_accepted = peak_pending = 0
    started = time.perf_counter_ns()
    update_schedule = Schedule(started, rate, seconds, stop)
    query_schedule = Schedule(started, query_rate, seconds, stop)

    def reader():
        nonlocal query_rejected, query_accepted
        previous = 1
        try:
            for due in query_schedule:
                try:
                    version, partner = service.partner(0).result(0)
                except BusyError:
                    query_rejected += 1
                    continue
                if version < previous or partner != (1 if version % 2 else None):
                    raise RuntimeError(
                        "hot-edge query disagrees with exact published prefix"
                    )
                previous = version
                query_accepted += 1
                queries.record(time.perf_counter_ns() - due)
        except BaseException as error:
            failures.append(error)
            stop.set()

    def finish(item):
        sequence, receipt, admitted, due = item
        outcome = receipt.result(30)
        observed, timing = time.perf_counter_ns(), receipt.timing()
        if (
            outcome.sequence != sequence
            or not outcome.changed
            or outcome.version != sequence + 1
            or timing is None
        ):
            raise RuntimeError("expected a real durable hot-edge change")
        ack.record(observed - admitted)
        offered_ack.record(observed - due)
        queue.record(timing.started_ns - timing.admitted_ns)
        execution.record(timing.completed_ns - timing.started_ns)

    reader_thread = threading.Thread(target=reader, daemon=True)
    try:
        reader_thread.start()
        for due in update_schedule:
            while pending and pending[0][1].done():
                finish(pending.popleft())
            request = Request(
                accepted + 1, "delete" if accepted % 2 == 0 else "insert", 0, 1
            )
            admitted = time.perf_counter_ns()
            try:
                receipt = service.submit(request)
            except BusyError:
                rejected += 1
            else:
                accepted += 1
                pending.append((accepted, receipt, admitted, due))
                peak_pending = max(peak_pending, len(pending))
                if len(pending) > queue_capacity + 256:
                    raise RuntimeError(
                        "client receipt retention exceeded bounded envelope"
                    )
        stop.set()
        reader_thread.join(10)
        if reader_thread.is_alive():
            raise TimeoutError("query producer did not stop")
        if failures:
            raise failures[0]
        acknowledged_before_drain = ack.count
        for item in pending:
            finish(item)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000_000
        status, metrics = service.status().result(10), service.metrics()
        if (
            status["sequence"] != accepted
            or ack.count != accepted
            or accepted + rejected + update_schedule.missed != update_schedule.total
            or query_accepted + query_rejected + query_schedule.missed
            != query_schedule.total
            or metrics["outstanding"]
        ):
            raise RuntimeError("offered/admitted/rejected/completed counts disagree")
        removed = {(0, 1)} if accepted % 2 else set()
        expected = live_digest(service, vertices, status)
    finally:
        stop.set()
        if reader_thread.ident is not None:
            reader_thread.join(10)
        service.close(30)
    tick = time.perf_counter()
    with Durable(path) as recovered:
        recovery = time.perf_counter() - tick
        if certificate(recovered, set(), removed, vertices) != expected:
            raise RuntimeError("offered-load exact disaster recovery failed")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "paced offered hot-edge load + concurrent committed queries; bounded receipts; producer missed slots explicit; NOT independent network/power-cut qualification",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "vertices": vertices,
        "offered_updates_per_second": rate,
        "offered_queries_per_second": query_rate,
        "offering_seconds": seconds,
        "planned_update_offers": update_schedule.total,
        "producer_missed_update_slots": update_schedule.missed,
        "busy_update_offers": rejected,
        "real_acknowledged_updates": accepted,
        "acknowledged_before_drain": acknowledged_before_drain,
        "offering_and_drain_seconds": elapsed,
        "real_acknowledged_updates_per_second": accepted / elapsed,
        "planned_query_offers": query_schedule.total,
        "producer_missed_query_slots": query_schedule.missed,
        "busy_query_offers": query_rejected,
        "partner_queries": query_accepted,
        "peak_client_receipts": peak_pending,
        "service_metrics": metrics,
        "final_status": status,
        "acknowledged_latency": ack.summary(),
        "offered_to_acknowledged_latency": offered_ack.summary(),
        "update_queue_wait": queue.summary(),
        "update_execution": execution.summary(),
        "offered_query_latency": queries.summary(),
        "recovery_seconds": recovery,
        "independent_exact_audit_and_recovery_passed": True,
        "matching_digest": expected,
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
    }


def main() -> None:
    """Print one bounded offered-load run, leaving its store for inspection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=32000)
    parser.add_argument("--rate", type=int, default=10000)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--query-rate", type=int, default=1000)
    parser.add_argument("--queue-capacity", type=int, default=512)
    args = parser.parse_args()
    print(
        json.dumps(
            measure(
                args.database,
                args.vertices,
                args.rate,
                args.seconds,
                query_rate=args.query_rate,
                queue_capacity=args.queue_capacity,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
