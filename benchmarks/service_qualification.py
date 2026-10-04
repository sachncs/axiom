"""Repeatable, per-run durable Service smoke benchmark for paper modes.

This measures local SQLite-backed Service acknowledgments while partner reads
run concurrently. It is a per-run smoke, not a 10k updates/s qualification:
that claim requires a sustained, no-loss target run on the declared workload.

Example: ``python benchmarks/service_qualification.py --mode basic --vertices
10000 --updates 2000 --rate max --read-rate 100 --seed 599``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import threading
import time
from array import array
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

try:
    import resource
except ImportError:  # pragma: no cover - platform-specific availability
    resource = None  # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import BusyError, CapacityError, Durable, Request
from axiom.service import Service

MAX_UPDATES = 1_000_000
MAX_VERTICES = 1_000_000


def positive_integer(value: str) -> int:
    """Parse an explicitly positive CLI integer."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if str(parsed) != value or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def rate_value(value: str) -> float | None:
    """Parse a positive operations/second rate or ``max`` for unpaced load."""
    if value == "max":
        return None
    try:
        rate = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive rate or 'max'") from error
    if not math.isfinite(rate) or rate <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive rate or 'max'")
    return rate


class Latency:
    """Fixed-memory latency histogram with 100-microsecond upper-bound buckets."""

    def __init__(self) -> None:
        """Allocate fixed counters so memory does not scale with sample count."""
        self.bins = array("Q", [0]) * 10001
        self.count = 0
        self.maximum = 0

    def record(self, nanoseconds: int) -> None:
        """Record one duration in the corresponding conservative bucket."""
        index = min(nanoseconds // 100_000, 10_000)
        self.bins[index] += 1
        self.count += 1
        self.maximum = max(self.maximum, nanoseconds)

    def summary(self) -> dict[str, int | None]:
        """Report conservative percentile upper bounds, None for overflow ranks."""
        result: dict[str, int | None] = {"count": self.count, "max_ns": None}
        for name, fraction in (("p50_ns", 0.50), ("p95_ns", 0.95), ("p99_ns", 0.99)):
            rank = math.ceil(fraction * self.count)
            running = 0
            value = None
            for index, amount in enumerate(self.bins):
                running += amount
                if rank and running >= rank:
                    value = (index + 1) * 100_000 if index < 10_000 else None
                    break
            result[name] = value
        result["max_ns"] = self.maximum if self.count else None
        result["resolution_ns"] = 100_000
        result["overflow_at_1s"] = self.bins[-1]
        return result


def matching_digest(
    page: Any, version: int, vertices: int, *, asynchronous: bool
) -> str:
    """Check coherent paged matching properness and digest its full partner map."""
    partners = array("i", [-1]) * vertices
    start = 0
    while True:
        result = page(start, min(4096, vertices), version)
        current, edges, following = result.result(30) if asynchronous else result
        if current != version:
            raise RuntimeError("matching audit crossed graph versions")
        for left, right in edges:
            if not 0 <= left < right < vertices:
                raise RuntimeError("matching audit found an invalid edge")
            if partners[left] != -1 or partners[right] != -1:
                raise RuntimeError("matching audit found a non-proper matching")
            partners[left], partners[right] = right, left
        if following is None:
            break
        if type(following) is not int or not start < following <= vertices:
            raise RuntimeError("matching audit page did not advance")
        start = following
    if sys.byteorder != "little":
        partners.byteswap()
    return hashlib.sha256(memoryview(partners).cast("B")).hexdigest()


def audit_topology(
    restored: Durable,
    vertices: int,
    acknowledged: int,
) -> int:
    """Audit ring plus the possible unmatched insert in an acknowledged prefix."""
    expected_count = 2 * vertices + acknowledged % 2
    status = restored.status()
    if status["edges"] != expected_count:
        raise RuntimeError(
            "reopened graph edge count differs from expected topology: "
            f"actual={status['edges']}, expected={expected_count}"
        )

    def expected_edges() -> Iterator[tuple[int, int]]:
        for left in range(vertices):
            for offset in (1, 2):
                right = (left + offset) % vertices
                yield min(left, right), max(left, right)
        if acknowledged % 2:
            pair = acknowledged // 2
            yield pair, pair + vertices // 2

    chunk: list[tuple[int, int]] = []
    for edge in expected_edges():
        chunk.append(edge)
        if len(chunk) == 4096:
            if not all(restored.read_snapshot([], chunk).has_edges):
                raise RuntimeError("reopened graph is missing an expected edge")
            chunk.clear()
    if chunk and not all(restored.read_snapshot([], chunk).has_edges):
        raise RuntimeError("reopened graph is missing an expected edge")
    return expected_count


def resource_snapshot(service: Service) -> dict[str, int] | None:
    """Return process peak RSS and Service counters when the platform exposes them."""
    if resource is None:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        peak_rss = int(usage.ru_maxrss)
        if sys.platform == "darwin":
            peak_rss //= 1024
        metrics = service.metrics()
        return {
            "peak_rss_kib": peak_rss,
            "peak_outstanding": int(metrics["peak_outstanding"]),
            "largest_group": int(metrics["largest_group"]),
        }
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return None


def validate(
    *,
    mode: str,
    vertices: int,
    updates: int,
    rate: float | None,
    read_rate: float | None,
    seed: int,
    window: int = 64,
) -> None:
    """Reject unsupported workload parameters before creating a database."""
    if mode not in {"basic", "multilevel"}:
        raise ValueError("mode must be basic or multilevel")
    if type(vertices) is not int or not 8 <= vertices <= MAX_VERTICES:
        raise ValueError(f"vertices must be an integer in [8, {MAX_VERTICES}]")
    if type(updates) is not int or not 1 <= updates <= MAX_UPDATES:
        raise ValueError(f"updates must be an integer in [1, {MAX_UPDATES}]")
    if updates > 2 * (vertices // 2):
        raise ValueError("updates exceed the distinct antipodal-pair workload")
    if type(window) is not int or not 1 <= window <= 512:
        raise ValueError("window must be an integer in [1, 512]")
    if rate is not None and (
        type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0
    ):
        raise ValueError("rate must be max/None or a finite positive number")
    if read_rate is not None and (
        type(read_rate) not in (int, float)
        or not math.isfinite(read_rate)
        or read_rate <= 0
    ):
        raise ValueError("read rate must be max/None or a finite positive number")
    if type(seed) is not int or not 0 <= seed <= (1 << 32) - 1:
        raise ValueError("seed must be an integer in [0, 4294967295]")


def run(
    path: Path,
    *,
    mode: str,
    vertices: int,
    updates: int,
    rate: float | None,
    read_rate: float | None,
    seed: int,
    window: int = 64,
) -> dict[str, Any]:
    """Run one deterministic trace, count actual outcomes, and verify recovery."""
    validate(
        mode=mode,
        vertices=vertices,
        updates=updates,
        rate=rate,
        read_rate=read_rate,
        seed=seed,
        window=window,
    )
    if path.exists():
        raise ValueError("benchmark requires a fresh database path")
    overall_start = time.perf_counter()
    receipt_latencies = Latency()
    query_latencies = Latency()
    query_failures = 0
    query_stop = threading.Event()
    query_started = threading.Event()
    initialization_start = time.perf_counter()
    service = Service(
        path,
        n=vertices,
        width=2,
        mode=mode,
        queue_capacity=window + 8,
    )
    initialization_seconds = time.perf_counter() - initialization_start
    workload_start = time.perf_counter()
    query_rng = random.Random(seed ^ 0xA51)

    def query_worker() -> None:
        nonlocal query_failures
        query_started.set()
        next_offer = time.perf_counter()
        try:
            while not query_stop.is_set():
                before = time.perf_counter_ns()
                receipt = service.partner(query_rng.randrange(vertices))
                try:
                    receipt.result(30)
                    query_latencies.record(time.perf_counter_ns() - before)
                except BaseException:
                    query_failures += 1
                    return
                if read_rate is not None:
                    next_offer = time.perf_counter() + 1 / read_rate
                    query_stop.wait(max(0, next_offer - time.perf_counter()))
        except BaseException:
            query_failures += 1
            query_stop.set()

    reader = threading.Thread(target=query_worker, name="paper-service-reader")
    reader.start()
    if not query_started.wait(5):
        query_stop.set()
        reader.join(5)
        service.close(30)
        raise TimeoutError("query worker did not start")
    acknowledged = accepted = failed = rejected = 0
    offered = 0
    next_offer = time.perf_counter()
    pending: deque[tuple[Any, int, int]] = deque()

    def complete_oldest(timeout: float = 120) -> bool | None:
        """Resolve oldest receipt, preserving FIFO and receipt-completion latency."""
        nonlocal acknowledged, failed
        receipt, sequence, admitted_ns = pending[0]
        try:
            outcome = receipt.result(timeout)
        except TimeoutError:
            if not receipt.done():
                if timeout < 120:
                    return None
                pending.popleft()
                failed += 1
                receipt_latencies.record(time.perf_counter_ns() - admitted_ns)
                return False
            pending.popleft()
            failed += 1
            timing = getattr(receipt, "timing", lambda: None)()
            elapsed = (
                timing.completed_ns - timing.admitted_ns
                if timing is not None
                else time.perf_counter_ns() - admitted_ns
            )
            receipt_latencies.record(elapsed)
            return False
        except BaseException:
            pending.popleft()
            failed += 1
            timing = getattr(receipt, "timing", lambda: None)()
            elapsed = (
                timing.completed_ns - timing.admitted_ns
                if timing is not None
                else time.perf_counter_ns() - admitted_ns
            )
            receipt_latencies.record(elapsed)
            return False
        pending.popleft()
        timing = getattr(receipt, "timing", lambda: None)()
        elapsed = (
            timing.completed_ns - timing.admitted_ns
            if timing is not None
            else time.perf_counter_ns() - admitted_ns
        )
        receipt_latencies.record(elapsed)
        if outcome.sequence != acknowledged + 1 or sequence != outcome.sequence:
            failed += 1
            return False
        if not outcome.changed:
            failed += 1
            return False
        acknowledged += 1
        return True

    try:
        for sequence in range(1, updates + 1):
            if query_stop.is_set():
                break
            blocked = False
            while len(pending) >= window:
                if complete_oldest() is not True:
                    blocked = True
                    break
            if failed or blocked:
                break
            if rate is not None:
                delay = next_offer - time.perf_counter()
                if delay > 0:
                    if pending:
                        complete_oldest(delay)
                        if failed:
                            break
                    remaining = next_offer - time.perf_counter()
                    if remaining > 0:
                        time.sleep(remaining)
            pair_index = (sequence - 1) // 2
            left, right = pair_index, pair_index + vertices // 2
            operation: Literal["insert", "delete"] = (
                "insert" if sequence % 2 else "delete"
            )
            offered += 1
            offered_ns = time.perf_counter_ns()
            try:
                receipt = service.submit(Request(sequence, operation, left, right))
            except (BusyError, CapacityError):
                rejected += 1
                break
            except BaseException:
                failed += 1
                break
            accepted += 1
            pending.append((receipt, sequence, offered_ns))
            if rate is not None:
                # Resume pacing from now, preventing catch-up bursts after stalls.
                next_offer = time.perf_counter() + 1 / rate
        while pending:
            complete_oldest()
        resources = resource_snapshot(service) if failed == 0 else None
    finally:
        query_stop.set()
        reader.join(30)
        if reader.is_alive():
            service.close(30)
            raise TimeoutError("query worker did not stop")
        workload_seconds = time.perf_counter() - workload_start
        service.close(120)
    with Durable(path, mode=mode) as restored:
        recovered_status = restored.status()
        if recovered_status["sequence"] != acknowledged:
            raise RuntimeError(
                "reopened durable status differs from acknowledged trace"
            )
        if not restored.check():
            raise RuntimeError("reopened graph/matching exact check failed")
        expected_edge_count = audit_topology(restored, vertices, acknowledged)
        if recovered_status["edges"] != expected_edge_count:
            raise RuntimeError("reopened edge count differs from audited topology")
        recovered_digest = matching_digest(
            restored.page,
            int(recovered_status["version"]),
            vertices,
            asynchronous=False,
        )
    end_to_end_seconds = time.perf_counter() - overall_start
    return {
        "scope": "PER-RUN SMOKE ONLY; not 10k qualification without a sustained, no-loss target run",
        "mode": mode,
        "load_model": "bounded receipt pipeline; pacing has no catch-up bursts; not open-loop",
        "vertices": vertices,
        "window": window,
        "service_initialization_seconds": initialization_seconds,
        "seed": seed,
        "update_pattern": "insert-delete on distinct antipodal pairs",
        "requested_updates": updates,
        "update_rate_offer_per_second": rate if rate is not None else "max",
        "update_pacing": "unpaced"
        if rate is None
        else "rate-capped without catch-up bursts",
        "read_rate_offer_per_second": read_rate if read_rate is not None else "max",
        "read_pacing": "unpaced"
        if read_rate is None
        else "rate-capped without catch-up bursts",
        "offered": offered,
        "accepted": accepted,
        "acknowledged_durable": acknowledged,
        "failed": failed,
        "rejected": rejected,
        "offered_updates_per_second": offered / workload_seconds,
        "accepted_updates_per_second": accepted / workload_seconds,
        "achieved_durable_updates_per_second": acknowledged / workload_seconds,
        "workload_seconds": workload_seconds,
        "end_to_end_seconds": end_to_end_seconds,
        "receipt_latency_ns": receipt_latencies.summary(),
        "query_offers": query_latencies.count + query_failures,
        "query_succeeded": query_latencies.count,
        "query_failed": query_failures,
        "query_achieved_per_second": query_latencies.count / workload_seconds,
        "query_latency_ns": query_latencies.summary(),
        "recovered_status": recovered_status,
        "matching_digest": recovered_digest,
        "independent_reopen_verified": True,
        "resource_snapshot": resources,
    }


def main(arguments: list[str] | None = None) -> int:
    """Parse explicit workload arguments and print one JSON result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--mode", choices=("basic", "multilevel"), required=True)
    parser.add_argument("--vertices", type=positive_integer, required=True)
    parser.add_argument("--updates", type=positive_integer, required=True)
    parser.add_argument(
        "--rate", type=rate_value, required=True, help="updates/s or max"
    )
    parser.add_argument(
        "--read-rate", type=rate_value, required=True, help="queries/s or max"
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--window",
        type=positive_integer,
        default=64,
        help="accepted update window (1-512)",
    )
    options = parser.parse_args(arguments)
    try:
        result = run(
            options.database,
            mode=options.mode,
            vertices=options.vertices,
            updates=options.updates,
            rate=options.rate,
            read_rate=options.read_rate,
            seed=options.seed,
            window=options.window,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return (
        0
        if result["failed"] == 0
        and result["rejected"] == 0
        and result["accepted"] == result["requested_updates"]
        and result["acknowledged_durable"] == result["requested_updates"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
