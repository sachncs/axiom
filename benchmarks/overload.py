"""Paced offered load with explicit saturation and producer scheduling losses.

Offers do not wait for acknowledgments. Completed/rejected/missed work is counted
separately; skipped scheduling slots cannot inflate delivered throughput.
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
from collections import deque
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import BusyError, Durable, Request
from axiom.service import Service
from benchmarks.durable import certificate
from benchmarks.service import Histogram, live_digest


class PowerLaw:
    """Bounded deterministic skewed topology and Zipf-weighted real-update pool."""

    def __init__(self, vertices: int, edges: int, seed: int):
        """Build disjoint permanent and toggleable spoke sets using a fixed seed."""
        if type(vertices) is not int or vertices < 64:
            raise ValueError("power-law workload requires at least 64 vertices")
        if type(edges) is not int or not 1 <= edges <= 8192:
            raise ValueError("power-law edge budget must be in [1, 8192]")
        self.vertices, self.seed = vertices, seed
        self.hubs = min(16, vertices // 8)
        rng = random.Random(seed)
        weights = [1 / rank**1.2 for rank in range(1, self.hubs + 1)]
        owners = []
        counts = [0] * self.hubs
        capacity = vertices - self.hubs - 4
        for _ in range(2 * edges):
            eligible = [rank for rank in range(self.hubs) if counts[rank] < capacity]
            if not eligible:
                raise ValueError("power-law edge budget exceeds graph capacity")
            owner = min(eligible, key=lambda rank: (counts[rank] + 1) / weights[rank])
            owners.append(owner)
            counts[owner] += 1
        rng.shuffle(owners)
        used: list[set[int]] = [set() for _ in range(self.hubs)]
        self.permanent: list[tuple[int, int]] = []
        self.churn: list[tuple[int, int]] = []
        cursors = [
            self.hubs + 3 + rng.randrange(max(1, vertices - self.hubs - 3))
            for _ in range(self.hubs)
        ]

        for index, owner in enumerate(owners):
            cursor = cursors[owner]
            while True:
                target = cursor % vertices
                cursor += 1
                distance = min((target - owner) % vertices, (owner - target) % vertices)
                if target >= self.hubs and distance > 2 and target not in used[owner]:
                    used[owner].add(target)
                    cursors[owner] = cursor
                    edge = (owner, target)
                    (self.permanent if index < edges else self.churn).append(edge)
                    break

        self.churn.sort()
        self.permanent.sort()
        # A bounded shuffled wheel provides deterministic Zipf-weighted selection
        # without a per-offer O(pool-size) weighted draw.
        hotweights = [1 / (edge[0] + 1) ** 1.2 for edge in self.churn]
        wheel_size = min(4096, max(256, len(self.churn) * 4))
        self.wheel = rng.choices(
            range(len(self.churn)), weights=hotweights, k=wheel_size
        )
        self.active = [True] * len(self.churn)
        self.digest = hashlib.sha256()
        self.insertions = self.deletions = 0

    def bootstrap(self) -> list[tuple[int, int]]:
        """Return exact preloaded edges; their setup sequence is reported separately."""
        return [*self.permanent, *self.churn]

    def request(self, accepted: int, sequence: int) -> tuple[Request, int]:
        """Prepare a deterministic toggle without advancing state on rejection."""
        cell = self.wheel[accepted % len(self.wheel)]
        operation: Literal["insert", "delete"] = (
            "delete" if self.active[cell] else "insert"
        )
        u, v = self.churn[cell]
        return Request(sequence, operation, u, v), cell

    def commit(self, request: Request, cell: int) -> None:
        """Advance workload and trace state only after Service admission succeeds."""
        self.active[cell] = not self.active[cell]
        self.digest.update(
            f"{request.sequence}:{request.operation}:{request.u}:{request.v};".encode()
        )
        if request.operation == "insert":
            self.insertions += 1
        else:
            self.deletions += 1

    def extras(self) -> list[tuple[int, int]]:
        """Return the sorted exact non-ring edge set for independent certification."""
        return sorted(
            [
                *self.permanent,
                *(
                    edge
                    for edge, active in zip(self.churn, self.active, strict=True)
                    if active
                ),
            ]
        )


def graph_digest(
    vertices: int,
    extras: list[tuple[int, int]],
    removed: set[tuple[int, int]],
    matching: str,
) -> str:
    """Hash an exact ring-plus-chords graph description and its full matching."""
    digest = hashlib.sha256(f"ring2:{vertices};".encode())
    for edge in sorted(removed):
        digest.update(f"-{edge[0]}:{edge[1]};".encode())
    for u, v in extras:
        digest.update(f"+{u}:{v};".encode())
    digest.update(bytes.fromhex(matching))
    return digest.hexdigest()


def maximum_degree(extras: list[tuple[int, int]], removed: set[tuple[int, int]]) -> int:
    """Return exact maximum degree from the degree-four base and sparse deltas."""
    deltas: dict[int, int] = {}
    for u, v in extras:
        deltas[u] = deltas.get(u, 0) + 1
        deltas[v] = deltas.get(v, 0) + 1
    for u, v in removed:
        deltas[u] = deltas.get(u, 0) - 1
        deltas[v] = deltas.get(v, 0) - 1
    return max((4 + degree for degree in deltas.values()), default=4)


class Schedule:
    """Generate scheduled arrivals, counting missed slots instead of catch-up bursts."""

    def __init__(self, started: int, rate: int, seconds: int, stop: threading.Event):
        """Keep constant-size schedule state independent of operation count."""
        self.started, self.rate, self.stop = started, rate, stop
        self.total, self.end = rate * seconds, started + seconds * 1_000_000_000
        self.missed = 0

    def deadline(self, index: int) -> int:
        """Map an offer slot to its independently measured intended timestamp."""
        return self.started + index * 1_000_000_000 // self.rate

    def position(self, now: int) -> int:
        """Select the last rounded slot that has arrived, without moving backward."""
        return min(
            self.total - 1,
            ((now - self.started + 1) * self.rate - 1) // 1_000_000_000,
        )

    def __iter__(self):
        """Yield intended arrival timestamps; never block on operation outcomes."""
        index = 0
        while index < self.total and not self.stop.is_set():
            now = time.perf_counter_ns()
            if now >= self.end:
                break
            due = self.deadline(index)
            if now < due:
                self.stop.wait((due - now) / 1_000_000_000)
                continue
            latest = self.position(now)
            self.missed += latest - index
            index = latest
            yield self.deadline(index)
            index += 1
        self.missed += self.total - index


class Burst(Schedule):
    """Offer each second's updates in its first quarter, then leave a drain gap."""

    def deadline(self, index: int) -> int:
        """Keep the same average offer count with a fourfold active-window rate."""
        second, slot = divmod(index, self.rate)
        return (
            self.started
            + second * 1_000_000_000
            + slot * 1_000_000_000 // (4 * self.rate)
        )

    def position(self, now: int) -> int:
        """Clamp quiet-window time to the last slot, never replaying a late burst."""
        second, elapsed = divmod(now - self.started, 1_000_000_000)
        slot = min(self.rate - 1, ((elapsed + 1) * 4 * self.rate - 1) // 1_000_000_000)
        return min(self.total - 1, second * self.rate + slot)


def measure(
    path: Path,
    vertices: int,
    rate: int,
    seconds: int,
    *,
    query_rate: int = 1000,
    queue_capacity: int = 512,
    workload: str = "hot",
    seed: int = 599,
    skew_edges: int = 1024,
) -> dict:
    """Offer bounded real updates independently of completion, then audit recovery."""
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
        or workload not in ("hot", "power-law")
        or type(seed) is not int
        or type(skew_edges) is not int
        or (workload == "power-law" and not 1 <= skew_edges <= 8192)
    ):
        raise ValueError("invalid bounded offered-load envelope")
    if path.exists():
        raise ValueError("benchmark requires a fresh database path")
    traffic = PowerLaw(vertices, skew_edges, seed) if workload == "power-law" else None
    service = Service(path, n=vertices, queue_capacity=queue_capacity)
    bootstrap = 0
    bootstrap_seconds = 0.0
    try:
        if traffic is not None:
            tick = time.perf_counter()
            rows = traffic.bootstrap()
            limit = min(256, int(service.metrics()["update_admission_limit"]))
            while bootstrap < len(rows):
                group = rows[bootstrap : bootstrap + limit]
                receipts = [
                    service.submit(Request(bootstrap + offset + 1, "insert", u, v))
                    for offset, (u, v) in enumerate(group)
                ]
                if any(not receipt.result(30).changed for receipt in receipts):
                    raise RuntimeError("power-law bootstrap contains a non-real edge")
                bootstrap += len(group)
            bootstrap_seconds = time.perf_counter() - tick
    except BaseException:
        service.close(10)
        raise
    stop = threading.Event()
    pending, failures = deque(), []
    ack, offered_ack, queue, execution, queries = [Histogram() for _ in range(5)]
    accepted = rejected = query_rejected = query_accepted = peak_pending = 0
    trace = hashlib.sha256()
    query_rng = random.Random(seed + 1)
    started = time.perf_counter_ns()
    update_schedule = Schedule(started, rate, seconds, stop)
    query_schedule = Schedule(started, query_rate, seconds, stop)

    def reader():
        nonlocal query_rejected, query_accepted
        previous = bootstrap + 1
        try:
            for due in query_schedule:
                try:
                    vertex = (
                        query_rng.choices(
                            range(traffic.hubs),
                            weights=[
                                1 / rank**1.2 for rank in range(1, traffic.hubs + 1)
                            ],
                            k=1,
                        )[0]
                        if traffic is not None
                        else 0
                    )
                    version, partner = service.partner(vertex).result(0)
                except BusyError:
                    query_rejected += 1
                    continue
                if (
                    version < previous
                    or version < bootstrap + 1
                    or version > bootstrap + accepted + 1
                    or (traffic is None and partner != (1 if version % 2 else None))
                    or (
                        traffic is not None
                        and partner is not None
                        and (not 0 <= partner < vertices or partner == vertex)
                    )
                ):
                    raise RuntimeError(
                        "partner query disagrees with a published mutation prefix"
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
            cell = None
            if traffic is None:
                request = Request(
                    accepted + 1, "delete" if accepted % 2 == 0 else "insert", 0, 1
                )
            else:
                request, cell = traffic.request(accepted, bootstrap + accepted + 1)
            admitted = time.perf_counter_ns()
            # Publish the candidate prefix before submission: Service can commit
            # before submit() returns, and the query thread must not observe a
            # valid committed version beyond its stale high-water mark.
            accepted += 1
            try:
                receipt = service.submit(request)
            except BusyError:
                accepted -= 1
                rejected += 1
            else:
                if traffic is None:
                    trace.update(
                        f"{accepted}:{request.operation}:{request.u}:{request.v};".encode()
                    )
                else:
                    if cell is None:
                        raise RuntimeError("power-law toggle lost its edge identity")
                    traffic.commit(request, cell)
                pending.append((request.sequence, receipt, admitted, due))
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
            status["sequence"] != bootstrap + accepted
            or ack.count != accepted
            or accepted + rejected + update_schedule.missed != update_schedule.total
            or query_accepted + query_rejected + query_schedule.missed
            != query_schedule.total
            or metrics["outstanding"]
        ):
            raise RuntimeError("offered/admitted/rejected/completed counts disagree")
        removed = {(0, 1)} if traffic is None and accepted % 2 else set()
        expected = live_digest(service, vertices, status)
    finally:
        stop.set()
        if reader_thread.ident is not None:
            reader_thread.join(10)
        service.close(30)
    tick = time.perf_counter()
    extras = [] if traffic is None else traffic.extras()
    with Durable(path) as recovered:
        recovery = time.perf_counter() - tick
        if (
            recovered.status()["sequence"] != bootstrap + accepted
            or certificate(recovered, extras, removed, vertices) != expected
        ):
            raise RuntimeError("offered-load exact disaster recovery failed")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "paced offered real-edge load + concurrent committed queries; bounded receipts; producer missed slots explicit; NOT independent network/power-cut qualification",
        "workload": workload,
        "seed": seed,
        "power_law_exponent": 1.2 if traffic is not None else None,
        "power_law_hubs": traffic.hubs if traffic is not None else None,
        "power_law_edge_budget_per_pool": skew_edges if traffic is not None else None,
        "bootstrap_updates": bootstrap,
        "bootstrap_seconds": bootstrap_seconds,
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
        "real_insertions": traffic.insertions
        if traffic is not None
        else (accepted + 1) // 2,
        "real_deletions": traffic.deletions if traffic is not None else accepted // 2,
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
        "graph_state_digest": graph_digest(vertices, extras, removed, expected),
        "maximum_degree": maximum_degree(extras, removed),
        "update_trace_digest": traffic.digest.hexdigest()
        if traffic is not None
        else trace.hexdigest(),
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
    parser.add_argument("--workload", choices=("hot", "power-law"), default="hot")
    parser.add_argument("--seed", type=int, default=599)
    parser.add_argument("--skew-edges", type=int, default=1024)
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
                workload=args.workload,
                seed=args.seed,
                skew_edges=args.skew_edges,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
