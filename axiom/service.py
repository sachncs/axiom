"""Bounded asynchronous admission to one certified FULL-WAL mutation owner.

This local threaded service explicitly selects the native production backend.
It does not provide network transport, caller authentication or a latency SLA.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Generic, TypeVar, cast

from axiom.durable import (
    BusyError,
    Durable,
    Outcome,
    Request,
    UnavailableError,
)

_T = TypeVar("_T")
_MAX = (1 << 63) - 1


def _integer(value: int, low: int, high: int, name: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")


def _timeout(value: float | None) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not 0 <= value <= threading.TIMEOUT_MAX:
        raise ValueError("timeout must be finite, nonnegative and supported by threads")
    return float(value)


@dataclass(frozen=True)
class Timing:
    """Measure admission, execution start and completion using a monotonic clock."""

    admitted_ns: int
    started_ns: int
    completed_ns: int


class Receipt(Generic[_T]):
    """Wait for accepted work without cancellation or owner-thread callbacks.

    A timeout does not cancel work or prove noncommit. Keep this receipt, or retry
    the same request ID/payload; never assign a fresh ID to an uncertain mutation.
    """

    def __init__(self) -> None:
        """Initialize a receipt; service admission supplies completion authority."""
        self._condition = threading.Condition()
        self._admitted_ns = time.perf_counter_ns()
        self._finished = False
        self._value: object = None
        self._error: BaseException | None = None
        self._timing: Timing | None = None

    def _finish(self, value: object, error: BaseException | None, started: int) -> None:
        with self._condition:
            if self._finished:
                # A delivered acknowledgment remains immutable during fail-stop.
                return
            timing = Timing(
                self._admitted_ns,
                max(started, self._admitted_ns),
                time.perf_counter_ns(),
            )
            self._value, self._error = value, error
            self._timing = timing
            self._finished = True
            self._condition.notify_all()

    def done(self) -> bool:
        """Report completion, including failure, without waiting."""
        with self._condition:
            return self._finished

    def timing(self) -> Timing | None:
        """Return completion timing, or None while the operation is pending."""
        with self._condition:
            return self._timing

    def result(self, timeout: float | None = None) -> _T:
        """Return the original result or raise failure; timeout leaves work accepted."""
        seconds = _timeout(timeout)
        deadline = None if seconds is None else time.monotonic() + seconds
        with self._condition:
            while not self._finished:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("accepted work may still commit; retain its ID")
                self._condition.wait(remaining)
            if self._error is not None:
                raise self._error
            return cast(_T, self._value)


@dataclass
class _Work:
    receipts: list[Receipt[object]]
    request: Request | None = None
    action: Callable[[Durable], object] | None = None
    started_ns: int = 0
    finished: bool = False


class Service:
    """Aggregate updates with bounded outstanding work and coherent query results.

    One global request stream must be sequenced by callers. Pending identical IDs
    share the original mutation/outcome. Reads are scheduled between update groups,
    not as FIFO barriers: wait for an update acknowledgment before read-your-write.
    Close explicitly to drain accepted work and release the persistent owner lock.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        n: int | None = None,
        width: int = 2,
        budget: int = 1 << 30,
        queue_capacity: int = 1024,
        max_batch: int | None = None,
        batch_wait_ms: float = 1.0,
        checkpoint_interval: int | None = None,
        retain_operations: int | None = None,
        max_operations: int | None = None,
        max_database_bytes: int = 64 << 20,
        max_snapshot_bytes: int = 64 << 20,
    ) -> None:
        """Open native checkpoint v2 and start its single local mutation worker."""
        _integer(queue_capacity, 1, 16384, "queue_capacity")
        if type(batch_wait_ms) not in (int, float) or not 0 <= batch_wait_ms <= 100:
            raise ValueError("batch_wait_ms must be finite in [0,100]")
        if not Path(path).exists() and checkpoint_interval is None:
            checkpoint_interval = 32768
        self._condition = threading.Condition()
        self._close_lock = threading.Lock()
        self._updates: deque[_Work] = deque()
        self._reads: deque[_Work] = deque()
        self._pending: dict[int, _Work] = {}
        self._capacity = queue_capacity
        self._wait_ns = int(batch_wait_ms * 1_000_000)
        self._outstanding = self._accepted = self._completed = 0
        self._peak_outstanding = self._groups = self._largest_group = 0
        self._prefer_reads = False
        self._closing = self._closed = False
        self._failure: BaseException | None = None
        self._close_error: BaseException | None = None
        self._unavailable = UnavailableError(
            "owner failed; close/recover and retry original request IDs"
        )
        self._owner = Durable(
            path,
            n=n,
            width=width,
            budget=budget,
            max_batch=max_batch,
            checkpoint_interval=checkpoint_interval,
            retain_operations=retain_operations,
            max_operations=max_operations,
            max_database_bytes=max_database_bytes,
            max_snapshot_bytes=max_snapshot_bytes,
        )
        try:
            status = self._owner.status()
            if not status["checkpoint_interval"]:
                raise ValueError(
                    "Service requires checkpoint v2; no implicit v1 migration"
                )
            if queue_capacity > int(status["retain_operations"]):
                raise ValueError(
                    "queue capacity must not exceed persisted retry retention"
                )
            self._vertices = int(status["vertices"])
            self._next_sequence = int(status["sequence"]) + 1
            self._batch = int(status["max_batch"])
            self._thread = threading.Thread(
                target=self._run, name="axiom-durable-owner", daemon=True
            )
            self._thread.start()
        except BaseException:
            self._owner.close()
            raise

    def _admission(self) -> None:
        if self._closing or self._closed or self._failure is not None:
            raise UnavailableError("service is closing, closed or failed")
        if self._outstanding >= self._capacity:
            raise BusyError("outstanding work capacity reached; nothing was admitted")

    def _accepted_one(self) -> None:
        self._outstanding += 1
        self._accepted += 1
        self._peak_outstanding = max(self._peak_outstanding, self._outstanding)
        self._condition.notify()

    def _read(self, action: Callable[[Durable], _T]) -> Receipt[_T]:
        with self._condition:
            self._admission()
            receipt: Receipt[_T] = Receipt()
            self._reads.append(_Work([cast(Receipt[object], receipt)], action=action))
            self._accepted_one()
            return receipt

    def submit(self, request: Request) -> Receipt[Outcome]:
        """Admit one sequenced update/retry, or reject without admission."""
        if (
            type(request) is not Request
            or type(request.operation) is not str
            or request.operation not in ("insert", "delete")
        ):
            raise ValueError("require a typed insert/delete Request")
        _integer(request.sequence, 1, _MAX, "sequence")
        _integer(request.u, 0, self._vertices - 1, "u")
        _integer(request.v, 0, self._vertices - 1, "v")
        request = Request(
            request.sequence,
            request.operation,
            min(request.u, request.v),
            max(request.u, request.v),
        )
        with self._condition:
            self._admission()
            if request.sequence > self._next_sequence:
                raise ValueError(
                    "new request sequences must be contiguous in admission order"
                )
            pending = self._pending.get(request.sequence)
            if pending is not None and pending.request != request:
                raise ValueError(
                    "pending retry payload differs from its accepted request"
                )
            receipt: Receipt[Outcome] = Receipt()
            if pending is not None:
                pending.receipts.append(cast(Receipt[object], receipt))
            elif request.sequence == self._next_sequence:
                work = _Work([cast(Receipt[object], receipt)], request=request)
                self._pending[request.sequence] = work
                try:
                    self._updates.append(work)
                except BaseException:
                    del self._pending[request.sequence]
                    raise
                self._next_sequence += 1
            else:
                self._reads.append(
                    _Work(
                        [cast(Receipt[object], receipt)],
                        action=lambda owner: owner.apply([request])[0],
                    )
                )
            self._accepted_one()
            return receipt

    def partner(self, vertex: int) -> Receipt[tuple[int, int | None]]:
        """Admit an O(1) coherent committed partner query."""
        _integer(vertex, 0, self._vertices - 1, "vertex")
        return self._read(lambda owner: owner.partner(vertex))

    def has_edge(self, u: int, v: int) -> Receipt[tuple[int, bool]]:
        """Admit committed topology with its matching-compatible version."""
        _integer(u, 0, self._vertices - 1, "u")
        _integer(v, 0, self._vertices - 1, "v")
        return self._read(lambda owner: owner.has_edge(u, v))

    def page(
        self, start: int = 0, limit: int = 1024, version: int | None = None
    ) -> Receipt[tuple[int, list[tuple[int, int]], int | None]]:
        """Admit a bounded versioned matching page, never a whole-matching copy."""
        _integer(start, 0, self._vertices, "start")
        _integer(limit, 1, 4096, "limit")
        if version is not None:
            _integer(version, 0, _MAX, "version")
        return self._read(lambda owner: owner.page(start, limit, version))

    def status(self) -> Receipt[dict[str, int | str]]:
        """Admit a committed graph/persistence status query."""
        return self._read(lambda owner: owner.status())

    def checkpoint(self) -> Receipt[dict[str, int]]:
        """Admit explicit durable maintenance under the same single-owner protocol."""
        return self._read(lambda owner: owner.checkpoint())

    def check(self) -> Receipt[bool]:
        """Admit an independent full audit; audit failure disables the service."""

        def audit(owner: Durable) -> bool:
            if not owner.check():
                raise UnavailableError("full graph/matching certificate failed")
            return True

        return self._read(audit)

    def metrics(self) -> dict[str, int | str]:
        """Read admission diagnostics, not an unversioned graph-state escape hatch."""
        with self._condition:
            state = (
                "failed"
                if self._failure is not None
                else "closed"
                if self._closed
                else "closing"
                if self._closing
                else "open"
            )
            return {
                "state": state,
                "capacity": self._capacity,
                "outstanding": self._outstanding,
                "peak_outstanding": self._peak_outstanding,
                "accepted": self._accepted,
                "completed": self._completed,
                "groups": self._groups,
                "largest_group": self._largest_group,
                "batch_limit": self._batch,
                "batch_wait_ns": self._wait_ns,
                "next_admission_sequence": self._next_sequence,
            }

    def _take_slice(self, queue: deque[_Work]) -> deque[_Work]:
        # Allocate the bounded work container before removing admission records.
        chosen = deque(islice(queue, self._batch))
        for _ in chosen:
            queue.popleft()
        return chosen

    def _take(self) -> deque[_Work] | None:
        with self._condition:
            while True:
                if self._reads and self._prefer_reads:
                    self._prefer_reads = False
                    return self._take_slice(self._reads)
                if self._updates:
                    deadline = self._updates[0].receipts[0]._admitted_ns + self._wait_ns
                    remaining = deadline - time.perf_counter_ns()
                    if (
                        self._closing
                        or len(self._updates) >= self._batch
                        or remaining <= 0
                    ):
                        self._prefer_reads = True
                        return self._take_slice(self._updates)
                if self._reads:
                    return self._take_slice(self._reads)
                if self._updates:
                    self._condition.wait(max(0, remaining) / 1_000_000_000)
                elif self._closing:
                    return None
                else:
                    self._condition.wait()

    def _finish(self, work: _Work, value: object, error: BaseException | None) -> None:
        with self._condition:
            if work.finished:
                return
            outstanding = self._outstanding - len(work.receipts)
            completed = self._completed + len(work.receipts)
            for receipt in work.receipts:
                receipt._finish(value, error, work.started_ns or time.perf_counter_ns())
            self._outstanding, self._completed = outstanding, completed
            work.finished = True
            if work.request is not None:
                self._pending.pop(work.request.sequence, None)

    def _fail(self, error: BaseException, current: deque[_Work]) -> None:
        with self._condition:
            self._failure, self._closing = error, True
            for work in current:
                self._finish(work, None, error)
            for queue in (self._updates, self._reads):
                while queue:
                    self._finish(queue.popleft(), None, self._unavailable)
            self._condition.notify_all()

    def _run(self) -> None:
        current: deque[_Work] = deque()
        try:
            while True:
                chosen = self._take()
                if chosen is None:
                    break
                current = chosen
                if current[0].request is not None:
                    started = time.perf_counter_ns()
                    for work in current:
                        work.started_ns = started
                    outcomes = self._owner.apply(
                        [cast(Request, work.request) for work in current]
                    )
                    with self._condition:
                        self._groups += 1
                        self._largest_group = max(self._largest_group, len(current))
                    offset = 0
                    while current:
                        work = current[0]
                        self._finish(work, outcomes[offset], None)
                        current.popleft()
                        offset += 1
                else:
                    while current:
                        work = current[0]
                        work.started_ns = time.perf_counter_ns()
                        try:
                            value = cast(Callable[[Durable], object], work.action)(
                                self._owner
                            )
                        except UnavailableError:
                            raise
                        except (ValueError, RuntimeError, MemoryError) as error:
                            # Reuse only a healthy, nonmutating rejection.
                            self._owner.status()
                            self._finish(work, None, error)
                        else:
                            self._finish(work, value, None)
                        current.popleft()
        except BaseException as error:
            self._fail(error, current)
        finally:
            try:
                self._owner.close()
            except BaseException as error:
                self._close_error = error
                self._failure = self._failure or error
            with self._condition:
                self._closed = True
                self._condition.notify_all()

    def close(self, timeout: float | None = None) -> None:
        """Stop admission, drain accepted work and join; timeout does not cancel it."""
        seconds = _timeout(timeout)
        if not self._close_lock.acquire(blocking=False):
            raise BusyError("another caller is closing the service")
        try:
            with self._condition:
                self._closing = True
                self._condition.notify_all()
            self._thread.join(seconds)
            if self._thread.is_alive():
                raise TimeoutError("service is still draining; call close again")
            if self._close_error is not None:
                # Retry release; do not silently abandon a held lock.
                self._owner.close()
                self._close_error = None
        finally:
            self._close_lock.release()

    def __enter__(self) -> Service:
        """Use explicit ownership in a context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Drain accepted work and release ownership on context exit."""
        self.close()
