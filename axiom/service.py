"""Bounded asynchronous admission to one certified FULL-WAL mutation owner.

The service selects one of the paper matching modes, Basic or Multilevel.
It does not provide network transport, caller authentication or a latency SLA.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Generic, TypeVar, cast
from uuid import UUID

from axiom.durable import (
    MAX_READS,
    BusyError,
    CapacityError,
    Durable,
    ExternalRequest,
    ExternalSnapshot,
    HistoryPage,
    Outcome,
    ReadSnapshot,
    RecoveryError,
    Request,
    UnavailableError,
)
from axiom.identifier import Identifier

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
    requests: tuple[Request, ...] | None = None
    external: ExternalRequest | None = None
    externals: tuple[ExternalRequest, ...] | None = None
    action: Callable[[Durable], object] | None = None
    started_ns: int = 0
    finished: bool = False
    maintenance: bool = False
    explicit: bool = False


class Service:
    """Aggregate updates with bounded outstanding work and coherent query results.

    One global request stream must be sequenced by callers. Pending identical IDs
    share the original mutation/outcome. Partner reads use the last publication;
    other reads run between groups. Neither is a FIFO barrier: wait for an update
    acknowledgment before read-your-write. Concurrent client calls are supported
    on GIL-enabled CPython; the native binding rejects free-threaded builds.
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
        maintenance_capacity: int = 1,
        query_reserve: int | None = None,
        max_batch: int | None = None,
        batch_wait_ms: float = 1.0,
        max_operations: int | None = None,
        max_database_bytes: int = 64 << 20,
        mode: str = "basic",
    ) -> None:
        """Open a selected paper mode and start its single local mutation worker."""
        if mode not in ("basic", "multilevel"):
            raise ValueError("mode must be 'basic' or 'multilevel'")
        _integer(queue_capacity, 1, 16384, "queue_capacity")
        if query_reserve is None:
            query_reserve = min(1, queue_capacity - 1)
        _integer(query_reserve, 0, queue_capacity - 1, "query_reserve")
        _integer(
            maintenance_capacity, 1, min(64, queue_capacity), "maintenance_capacity"
        )
        if type(batch_wait_ms) not in (int, float) or not 0 <= batch_wait_ms <= 100:
            raise ValueError("batch_wait_ms must be finite in [0,100]")
        self._condition = threading.Condition()
        self._close_lock = threading.Lock()
        self._updates: deque[_Work] = deque()
        self._reads: deque[_Work] = deque()
        self._pending: dict[int, _Work] = {}
        self._capacity = queue_capacity
        self._query_reserve = query_reserve
        self._maintenance_capacity = maintenance_capacity
        self._maintenance = 0
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
            mode=mode,
            width=width,
            budget=budget,
            max_batch=max_batch,
            max_operations=max_operations,
            max_database_bytes=max_database_bytes,
        )
        try:
            status = self._owner.status()
            self._vertices = int(status["vertices"])
            self._next_sequence = int(status["sequence"]) + 1
            self._batch = int(status["max_batch"])
            self._max_operations = int(status["max_operations"])
            self._thread = threading.Thread(
                target=self._run, name="axiom-durable-owner", daemon=True
            )
            self._thread.start()
        except BaseException:
            self._owner.close()
            raise

    def _admission(self, *, update: bool = False) -> None:
        if self._closing or self._closed or self._failure is not None:
            raise UnavailableError("service is closing, closed or failed")
        if self._outstanding >= self._capacity:
            raise BusyError("outstanding work capacity reached; nothing was admitted")
        if update and self._outstanding >= self._capacity - self._query_reserve:
            raise BusyError(
                "update capacity reached; query slots reserved; nothing was admitted"
            )

    def _accepted_one(self) -> None:
        self._outstanding += 1
        self._accepted += 1
        self._peak_outstanding = max(self._peak_outstanding, self._outstanding)
        self._condition.notify()

    def _read(
        self, action: Callable[[Durable], _T], *, maintenance: bool = False
    ) -> Receipt[_T]:
        with self._condition:
            self._admission()
            if maintenance and self._maintenance >= self._maintenance_capacity:
                raise BusyError("maintenance capacity reached; nothing was admitted")
            receipt: Receipt[_T] = Receipt()
            self._reads.append(
                _Work(
                    [cast(Receipt[object], receipt)],
                    action=action,
                    maintenance=maintenance,
                )
            )
            self._maintenance += maintenance
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
            self._admission(update=True)
            if request.sequence > self._next_sequence:
                raise ValueError(
                    "new request sequences must be contiguous in admission order"
                )
            pending = self._pending.get(request.sequence)
            if pending is not None and pending.request != request:
                raise ValueError(
                    "pending retry payload differs from its accepted request"
                )
            if pending is None and request.sequence == self._next_sequence:
                if request.sequence > self._max_operations:
                    raise CapacityError("durable operation history is exhausted")
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

    def submit_batch(self, requests: Sequence[Request]) -> Receipt[tuple[Outcome, ...]]:
        """Admit one explicitly atomic, bounded durable mutation batch.

        Fresh batches must begin at the next admission sequence and use a
        contiguous range. A wholly historical batch is an exact retry and is
        checked by Durable against retained history. A batch is one admission
        slot and one Durable.apply call; it is never coalesced with submit work.
        While a fresh batch is pending, only a whole identical retry shares its
        receipt; partial or conflicting overlaps are rejected.
        """
        if type(requests) not in (list, tuple) or not requests:
            raise ValueError("batch must be a nonempty list or tuple of Requests")
        if len(requests) > self._batch:
            raise ValueError("batch exceeds configured durable batch limit")
        normalized: list[Request] = []
        for request in requests:
            if (
                type(request) is not Request
                or type(request.operation) is not str
                or request.operation not in ("insert", "delete")
            ):
                raise ValueError("require typed insert/delete Requests")
            _integer(request.sequence, 1, _MAX, "sequence")
            _integer(request.u, 0, self._vertices - 1, "u")
            _integer(request.v, 0, self._vertices - 1, "v")
            normalized.append(
                Request(
                    request.sequence,
                    request.operation,
                    min(request.u, request.v),
                    max(request.u, request.v),
                )
            )
        batch = tuple(normalized)
        if any(
            right.sequence != left.sequence + 1
            for left, right in zip(batch, batch[1:], strict=False)
        ):
            raise ValueError("batch request sequences must be contiguous")

        with self._condition:
            self._admission(update=True)
            first, last = batch[0].sequence, batch[-1].sequence
            overlapping = [
                self._pending.get(sequence) for sequence in range(first, last + 1)
            ]
            if any(work is not None for work in overlapping):
                pending = overlapping[0]
                if (
                    pending is not None
                    and pending.explicit
                    and pending.action is None
                    and pending.requests == batch
                    and all(work is pending for work in overlapping)
                ):
                    retry_receipt: Receipt[tuple[Outcome, ...]] = Receipt()
                    pending.receipts.append(cast(Receipt[object], retry_receipt))
                    self._accepted_one()
                    return retry_receipt
                raise ValueError(
                    "batch overlaps admitted work with different bounds or payload"
                )
            if last < self._next_sequence:
                receipt: Receipt[tuple[Outcome, ...]] = Receipt()
                self._reads.append(
                    _Work(
                        [cast(Receipt[object], receipt)],
                        action=lambda owner: owner.apply(batch),
                        requests=batch,
                        explicit=True,
                    )
                )
            elif first == self._next_sequence:
                if last > self._max_operations:
                    raise CapacityError("durable operation history is exhausted")
                receipt = Receipt()
                work = _Work(
                    [cast(Receipt[object], receipt)],
                    requests=batch,
                    explicit=True,
                )
                try:
                    for request in batch:
                        self._pending[request.sequence] = work
                    self._updates.append(work)
                except BaseException:
                    for request in batch:
                        self._pending.pop(request.sequence, None)
                    raise
                self._next_sequence += len(batch)
            else:
                raise ValueError("new batch must begin at the next admission sequence")
            self._accepted_one()
            return receipt

    def register_identifier(self, value: str | int | UUID) -> Receipt[int]:
        """Durably allocate an external identity in update admission order."""
        Identifier.encode(value)
        with self._condition:
            self._admission(update=True)
            receipt: Receipt[int] = Receipt()
            work = _Work(
                [cast(Receipt[object], receipt)],
                action=lambda owner: owner.register_identifier(value),
                explicit=True,
            )
            self._updates.append(work)
            self._accepted_one()
            return receipt

    def submit_external(self, request: ExternalRequest) -> Receipt[Outcome]:
        """Admit one durable update addressed by stable external identifiers."""
        request = request.normalize()
        # Mappings are immutable. Resolve before allocating a sequence so an
        # invalid ID cannot leave an admission gap while later work is queued.
        self._owner.resolve_identifier(request.u)
        self._owner.resolve_identifier(request.v)
        with self._condition:
            self._admission(update=True)
            if request.sequence > self._next_sequence:
                raise ValueError(
                    "new request sequences must be contiguous in admission order"
                )
            pending = self._pending.get(request.sequence)
            if pending is not None and pending.external != request:
                raise ValueError(
                    "pending retry payload differs from its accepted request"
                )
            if pending is None and request.sequence == self._next_sequence:
                if request.sequence > self._max_operations:
                    raise CapacityError("durable operation history is exhausted")
            receipt: Receipt[Outcome] = Receipt()
            if pending is not None:
                pending.receipts.append(cast(Receipt[object], receipt))
            elif request.sequence == self._next_sequence:
                work = _Work(
                    [cast(Receipt[object], receipt)],
                    external=request,
                    action=lambda owner: owner.apply_external([request])[0],
                    explicit=True,
                )
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
                        external=request,
                        action=lambda owner: owner.apply_external([request])[0],
                    )
                )
            self._accepted_one()
            return receipt

    def submit_external_batch(
        self, requests: Sequence[ExternalRequest]
    ) -> Receipt[tuple[Outcome, ...]]:
        """Admit one bounded atomic batch whose edges use external IDs."""
        if type(requests) not in (list, tuple) or not requests:
            raise ValueError("batch must be a nonempty list or tuple of requests")
        if len(requests) > self._batch:
            raise ValueError("batch exceeds configured durable batch limit")
        batch = tuple(request.normalize() for request in requests)
        if any(
            right.sequence != left.sequence + 1
            for left, right in zip(batch, batch[1:], strict=False)
        ):
            raise ValueError("batch request sequences must be contiguous")
        for request in batch:
            self._owner.resolve_identifier(request.u)
            self._owner.resolve_identifier(request.v)

        with self._condition:
            self._admission(update=True)
            first, last = batch[0].sequence, batch[-1].sequence
            overlapping = [
                self._pending.get(sequence) for sequence in range(first, last + 1)
            ]
            if any(work is not None for work in overlapping):
                pending = overlapping[0]
                if (
                    pending is not None
                    and pending.explicit
                    and pending.action is not None
                    and pending.externals == batch
                    and all(work is pending for work in overlapping)
                ):
                    receipt: Receipt[tuple[Outcome, ...]] = Receipt()
                    pending.receipts.append(cast(Receipt[object], receipt))
                    self._accepted_one()
                    return receipt
                raise ValueError(
                    "batch overlaps admitted work with different bounds or payload"
                )
            if last < self._next_sequence:
                receipt = Receipt()
                self._reads.append(
                    _Work(
                        [cast(Receipt[object], receipt)],
                        externals=batch,
                        action=lambda owner: owner.apply_external(batch),
                        explicit=True,
                    )
                )
            elif first == self._next_sequence:
                if last > self._max_operations:
                    raise CapacityError("durable operation history is exhausted")
                receipt = Receipt()
                work = _Work(
                    [cast(Receipt[object], receipt)],
                    externals=batch,
                    action=lambda owner: owner.apply_external(batch),
                    explicit=True,
                )
                try:
                    for request in batch:
                        self._pending[request.sequence] = work
                    self._updates.append(work)
                except BaseException:
                    for request in batch:
                        self._pending.pop(request.sequence, None)
                    raise
                self._next_sequence += len(batch)
            else:
                raise ValueError("new batch must begin at the next admission sequence")
            self._accepted_one()
            return receipt

    def partner_external(
        self, value: str | int | UUID
    ) -> Receipt[tuple[int, str | int | UUID | None]]:
        """Queue a partner query returning only stable external identifiers."""
        Identifier.encode(value)
        return self._read(lambda owner: owner.partner_external(value))

    def has_edge_external(
        self, left: str | int | UUID, right: str | int | UUID
    ) -> Receipt[tuple[int, bool]]:
        """Queue one versioned edge query by stable external identifiers."""
        Identifier.encode(left)
        Identifier.encode(right)
        return self._read(lambda owner: owner.has_edge_external(left, right))

    def read_snapshot_external(
        self,
        vertices: Sequence[str | int | UUID],
        edges: Sequence[tuple[str | int | UUID, str | int | UUID]],
        *,
        expected_version: int | None = None,
    ) -> Receipt[ExternalSnapshot]:
        """Read a bounded set of external IDs at one committed version."""
        if type(vertices) not in (list, tuple) or type(edges) not in (list, tuple):
            raise ValueError("vertices and edges must be lists or tuples")
        if len(vertices) + len(edges) > MAX_READS:
            raise ValueError("read snapshot exceeds 4096 total queries")
        if expected_version is not None:
            _integer(expected_version, 0, _MAX, "expected_version")
        for vertex in vertices:
            Identifier.encode(vertex)
        saved_edges: list[tuple[str | int | UUID, str | int | UUID]] = []
        for edge in edges:
            if type(edge) not in (list, tuple) or len(edge) != 2:
                raise ValueError("each edge query must be a pair")
            Identifier.encode(edge[0])
            Identifier.encode(edge[1])
            saved_edges.append((edge[0], edge[1]))
        saved_vertices = tuple(vertices)
        stable_edges = tuple(saved_edges)
        return self._read(
            lambda owner: owner.read_snapshot_external(
                saved_vertices, stable_edges, expected_version=expected_version
            )
        )

    def partner(self, vertex: int) -> Receipt[tuple[int, int | None]]:
        """Queue a partner read on the serialized owner stream."""
        _integer(vertex, 0, self._vertices - 1, "vertex")
        return self._read(lambda owner: owner.partner(vertex))

    def has_edge(self, u: int, v: int) -> Receipt[tuple[int, bool]]:
        """Admit committed topology with its matching-compatible version."""
        _integer(u, 0, self._vertices - 1, "u")
        _integer(v, 0, self._vertices - 1, "v")
        return self._read(lambda owner: owner.has_edge(u, v))

    def read_snapshot(
        self,
        vertices: Sequence[int],
        edges: Sequence[tuple[int, int]],
        *,
        expected_version: int | None = None,
    ) -> Receipt[ReadSnapshot]:
        """Queue aligned partner/edge reads as one serialized owner operation."""
        if type(vertices) not in (list, tuple) or type(edges) not in (list, tuple):
            raise ValueError("vertices and edges must be lists or tuples")
        if len(vertices) + len(edges) > MAX_READS:
            raise ValueError("read snapshot exceeds 4096 total queries")
        if expected_version is not None:
            _integer(expected_version, 0, _MAX, "expected_version")
        for vertex in vertices:
            _integer(vertex, 0, self._vertices - 1, "vertex")
        for edge in edges:
            if type(edge) not in (list, tuple) or len(edge) != 2:
                raise ValueError("each edge query must be a pair")
            _integer(edge[0], 0, self._vertices - 1, "u")
            _integer(edge[1], 0, self._vertices - 1, "v")
        saved_vertices, saved_edges = (
            tuple(vertices),
            tuple((edge[0], edge[1]) for edge in edges),
        )
        return self._read(
            lambda owner: owner.read_snapshot(
                saved_vertices, saved_edges, expected_version=expected_version
            )
        )

    def history(
        self, start: int | None = None, limit: int = 256
    ) -> Receipt[HistoryPage]:
        """Queue one bounded page of retained, verifiable durable operations."""
        if start is not None:
            _integer(start, 1, _MAX, "start")
        _integer(limit, 1, MAX_READS, "limit")
        return self._read(lambda owner: owner.history(start, limit))

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
        return self._read(lambda owner: owner.checkpoint(), maintenance=True)

    def check(self) -> Receipt[bool]:
        """Admit an independent full audit; audit failure disables the service."""

        def audit(owner: Durable) -> bool:
            if not owner.check():
                raise UnavailableError("full graph/matching certificate failed")
            return True

        return self._read(audit, maintenance=True)

    def backup(
        self, path: str | Path, *, max_bytes: int = 64 << 20, timeout: float = 30.0
    ) -> Receipt[dict[str, int | str]]:
        """Admit a bounded owner snapshot; partner reads remain available during I/O."""
        destination = Path(path).absolute()
        _integer(max_bytes, 1 << 20, 1 << 30, "max_bytes")
        if type(timeout) not in (int, float) or not 0 < timeout <= 3600:
            raise ValueError("backup timeout must be finite and in (0, 3600]")
        return self._read(
            lambda owner: owner.backup(
                destination, max_bytes=max_bytes, timeout=timeout
            ),
            maintenance=True,
        )

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
                "query_reserve": self._query_reserve,
                "update_admission_limit": self._capacity - self._query_reserve,
                "maintenance_capacity": self._maintenance_capacity,
                "maintenance_outstanding": self._maintenance,
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
        first = queue[0]
        if first.explicit:
            chosen = deque((first,))
        else:
            chosen = deque()
            for work in islice(queue, self._batch):
                if work.explicit:
                    break
                chosen.append(work)
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
        self.complete((work,), (value,), error)

    def complete(
        self,
        works: Sequence[_Work],
        values: Sequence[object],
        error: BaseException | None,
    ) -> None:
        """Publish work results and counters under one condition-lock acquisition."""
        if len(works) != len(values):
            raise ValueError("each completed work item needs one result")
        with self._condition:
            for work, value in zip(works, values, strict=True):
                if work.finished:
                    continue
                outstanding = self._outstanding - len(work.receipts)
                completed = self._completed + len(work.receipts)
                for receipt in work.receipts:
                    receipt._finish(
                        value, error, work.started_ns or time.perf_counter_ns()
                    )
                self._outstanding, self._completed = outstanding, completed
                self._maintenance -= work.maintenance
                work.finished = True
                if work.requests is not None:
                    for request in work.requests:
                        self._pending.pop(request.sequence, None)
                elif work.request is not None:
                    self._pending.pop(work.request.sequence, None)
                elif work.externals is not None:
                    for external_request in work.externals:
                        self._pending.pop(external_request.sequence, None)
                elif work.external is not None:
                    self._pending.pop(work.external.sequence, None)

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
                if current[0].request is not None or (
                    current[0].requests is not None and current[0].action is None
                ):
                    started = time.perf_counter_ns()
                    for work in current:
                        work.started_ns = started
                    if current[0].explicit:
                        outcomes = self._owner.apply(
                            cast(tuple[Request, ...], current[0].requests)
                        )
                        with self._condition:
                            self._groups += 1
                            self._largest_group = max(
                                self._largest_group, len(outcomes)
                            )
                        self._finish(current[0], outcomes, None)
                        current.popleft()
                        continue
                    outcomes = self._owner.apply(
                        [cast(Request, work.request) for work in current]
                    )
                    with self._condition:
                        self._groups += 1
                        self._largest_group = max(self._largest_group, len(current))
                    self.complete(current, outcomes, None)
                    current.clear()
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
                        except RecoveryError:
                            # Persistence/recovery failures are never safe to reuse.
                            raise
                        except (
                            KeyError,
                            ValueError,
                            RuntimeError,
                            MemoryError,
                        ) as error:
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
