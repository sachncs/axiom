"""Bounded threaded admission, group durability, coherent reads and shutdown."""

import random
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from axiom import service as service_module
from axiom.core import Matcher
from axiom.durable import (
    BusyError,
    CapacityError,
    Durable,
    HistoryPage,
    Outcome,
    ReadSnapshot,
    Request,
    UnavailableError,
)
from axiom.service import Receipt, Service

SQLITEFULL = getattr(sqlite3, "SQLITE_FULL", 13)


def create(path: Path, **options: object) -> Service:
    settings = dict(
        n=33,
        width=0,
        queue_capacity=16,
        query_reserve=0,  # Legacy full-capacity tests; reservation tested separately.
        max_batch=4,
        batch_wait_ms=100,
        max_operations=64,
    )
    settings.update(options)
    return Service(path, **settings)


def edits(first: int, count: int) -> list[Request]:
    return [
        Request(seq, "insert" if seq % 2 else "delete", 0, 1)
        for seq in range(first, first + count)
    ]


def completed(receipts: list[Receipt]) -> list:
    return [receipt.result(timeout=5) for receipt in receipts]


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_service_passes_selected_mode_and_does_not_require_checkpoint_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    observed: list[str] = []

    class Owner:
        def __init__(self, path: Path, *, mode: str, **options: object) -> None:
            observed.append(mode)

        def status(self) -> dict[str, int]:
            return {
                "vertices": 8,
                "sequence": 0,
                "max_batch": 4,
                "max_operations": 16,
            }

        def close(self) -> None:
            pass

    monkeypatch.setattr(service_module, "Durable", Owner)
    with Service(tmp_path / f"{mode}.db", mode=mode, queue_capacity=8) as service:
        assert service.metrics()["state"] == "open"
    assert observed == [mode]


def test_service_defaults_to_basic_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str] = []

    class Owner:
        def __init__(self, path: Path, *, mode: str, **options: object) -> None:
            observed.append(mode)

        def status(self) -> dict[str, int]:
            return {
                "vertices": 8,
                "sequence": 0,
                "max_batch": 4,
                "max_operations": 16,
            }

        def close(self) -> None:
            pass

    monkeypatch.setattr(service_module, "Durable", Owner)
    with Service(tmp_path / "default.db", queue_capacity=8):
        pass
    assert observed == ["basic"]


def test_history_exhaustion_rejects_synchronously_without_poisoning_service(
    tmp_path: Path,
) -> None:
    with Service(
        tmp_path / "bounded-history.db",
        n=8,
        width=0,
        queue_capacity=4,
        max_batch=4,
        max_operations=2,
        batch_wait_ms=0,
    ) as service:
        first = Request(1, "insert", 0, 1)
        second = Request(2, "insert", 2, 3)
        assert service.submit(first).result(5) == Outcome(1, True, 1)
        assert service.submit(second).result(5) == Outcome(2, True, 2)
        with pytest.raises(CapacityError, match="history is exhausted"):
            service.submit(Request(3, "delete", 0, 1))
        with pytest.raises(CapacityError, match="history is exhausted"):
            service.submit_batch(
                [Request(3, "delete", 0, 1), Request(4, "delete", 2, 3)]
            )
        assert service.submit(first).result(5) == Outcome(1, True, 1)
        assert service.status().result(5)["sequence"] == 2
        assert service.metrics()["state"] == "open"


@pytest.mark.parametrize("mode", ["native", "", None, 1])
def test_service_rejects_unsupported_modes_before_opening_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: object
) -> None:
    def unexpected(*args: object, **options: object) -> object:
        raise AssertionError("invalid mode must be rejected before owner creation")

    monkeypatch.setattr(service_module, "Durable", unexpected)
    with pytest.raises(ValueError, match="mode must be 'basic' or 'multilevel'"):
        Service(tmp_path / "invalid.db", mode=mode)  # type: ignore[arg-type]


def test_partner_read_waits_in_serialized_owner_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()

    class Owner:
        def __init__(self, path: Path, *, mode: str, **options: object) -> None:
            assert mode == "basic"
            self.sequence = 0
            self.partner_value: int | None = None

        def status(self) -> dict[str, int]:
            return {
                "vertices": 8,
                "sequence": self.sequence,
                "max_batch": 4,
                "max_operations": 16,
            }

        def apply(self, requests: list[Request]) -> tuple[Outcome, ...]:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test release timed out")
            results = []
            for request in requests:
                self.sequence = request.sequence
                self.partner_value = (
                    request.v if request.operation == "insert" else None
                )
                results.append(Outcome(request.sequence, True, request.sequence))
            return tuple(results)

        def partner(self, vertex: int) -> tuple[int, int | None]:
            return self.sequence, self.partner_value

        def close(self) -> None:
            pass

    monkeypatch.setattr(service_module, "Durable", Owner)
    with Service(tmp_path / "queued-partner.db", n=8, queue_capacity=8) as service:
        mutation = service.submit(Request(1, "insert", 0, 1))
        try:
            assert entered.wait(5)
            query = service.partner(0)
            assert not query.done()
        finally:
            release.set()
        assert mutation.result(5) == Outcome(1, True, 1)
        assert query.result(5) == (1, 1)


def test_grouped_single_requests_preserve_results_versions_and_exact_recovery(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    with create(path, max_operations=128) as service:
        for first in range(1, 101, 4):
            receipts = [service.submit(r) for r in edits(first, 4)]
            assert completed(receipts) == [
                Outcome(seq, True, seq) for seq in range(first, first + 4)
            ]
            for receipt in receipts:
                timing = receipt.timing()
                assert receipt.done() and timing is not None
                assert timing.admitted_ns <= timing.started_ns <= timing.completed_ns
        status = service.status().result(5)
        assert status["sequence"] == 100 and status["mode"] == "basic"
        assert service.partner(0).result(5) == (100, None)
        assert service.has_edge(0, 1).result(5) == (100, False)
        assert service.check().result(5)
        metrics = service.metrics()
        assert metrics["largest_group"] == 4 and metrics["groups"] == 25
        assert metrics["outstanding"] == 0
        assert metrics["accepted"] == metrics["completed"]
    assert service.metrics()["state"] == "closed"
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == 100 and recovered.check()
        assert recovered.apply(edits(97, 4)) == tuple(
            Outcome(seq, True, seq) for seq in range(97, 101)
        )


def test_shared_receipt_waiters_and_concurrent_close_preserve_one_acknowledgment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "graph.db"
    service = create(path, batch_wait_ms=0)
    entered, release = threading.Event(), threading.Event()
    original = service._owner._persist

    def paused(rows: list) -> None:
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test release timed out")
        original(rows)

    monkeypatch.setattr(service._owner, "_persist", paused)
    receipt = service.submit(Request(1, "insert", 0, 1))

    def close_client() -> bool:
        try:
            service.close(5)
        except BusyError:
            return False  # Explicit backpressure, never a second concurrent release.
        return True

    try:
        assert entered.wait(5)
        with ThreadPoolExecutor(max_workers=12) as clients:
            waiters = [clients.submit(receipt.result, 5) for _ in range(8)]
            closers = [clients.submit(close_client) for _ in range(4)]
            release.set()
            assert [waiter.result(5) for waiter in waiters] == [Outcome(1, True, 1)] * 8
            closed = [closer.result(5) for closer in closers]
            assert any(closed)
    finally:
        release.set()
        service.close(5)
    assert receipt.result(0) == Outcome(1, True, 1)
    assert service.metrics()["outstanding"] == 0
    with pytest.raises(UnavailableError):
        service.partner(0)
    with Durable(path) as recovered:
        assert recovered.partner(0) == (1, 1) and recovered.check()


def test_pending_retries_share_one_mutation_and_consume_bounded_slots(
    tmp_path: Path,
) -> None:
    with create(tmp_path / "graph.db") as service:
        with service._condition:
            first = service.submit(Request(1, "insert", 0, 1))
            retry = service.submit(Request(1, "insert", 1, 0))
            with pytest.raises(ValueError, match="pending retry"):
                service.submit(Request(1, "delete", 0, 1))
            rest = [service.submit(r) for r in edits(2, 3)]
        assert first.result(5) == retry.result(5) == Outcome(1, True, 1)
        assert completed(rest) == [Outcome(seq, True, seq) for seq in range(2, 5)]
        assert service.status().result(5)["sequence"] == 4
        assert service.metrics()["largest_group"] == 4
        assert service.submit(Request(1, "insert", 0, 1)).result(5) == Outcome(
            1, True, 1
        )
        with pytest.raises(ValueError, match="payload"):
            service.submit(Request(1, "delete", 0, 1)).result(5)
        assert service.metrics()["state"] == "open"


def test_capacity_includes_active_work_and_queries_and_does_not_consume_rejected_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(
        tmp_path / "graph.db", queue_capacity=5, max_batch=2, batch_wait_ms=0
    ) as service:
        entered, release = threading.Event(), threading.Event()
        original = service._owner._persist

        def paused(rows: list) -> None:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test persistence release timed out")
            original(rows)

        monkeypatch.setattr(service._owner, "_persist", paused)
        first = service.submit(edits(1, 1)[0])
        try:
            assert entered.wait(5)
            pending = [service.submit(r) for r in edits(2, 2)]
            query = service.partner(0)
            assert not query.done()
            duplicate = service.submit(edits(1, 1)[0])
            with pytest.raises(BusyError, match="nothing was admitted"):
                service.submit(edits(4, 1)[0])
            assert service.metrics()["outstanding"] == 5
            assert service.metrics()["next_admission_sequence"] == 4
            with pytest.raises(TimeoutError, match="may still commit"):
                first.result(0)
            assert not first.done() and first.timing() is None
        finally:
            release.set()
        assert first.result(5) == Outcome(1, True, 1)
        assert completed(pending) == [Outcome(2, True, 2), Outcome(3, True, 3)]
        assert query.result(5) in ((1, 1), (3, 1))
        assert duplicate.result(5) == first.result(5)
        assert service.submit(edits(4, 1)[0]).result(5) == Outcome(4, True, 4)
        assert service.metrics()["peak_outstanding"] == 5


def test_read_snapshot_is_one_queue_operation_and_copies_bounded_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "graph.db", batch_wait_ms=0) as service:
        entered, release = threading.Event(), threading.Event()
        original = service._owner._persist

        def paused(rows: list) -> None:
            entered.set()
            assert release.wait(5)
            original(rows)

        monkeypatch.setattr(service._owner, "_persist", paused)
        first = service.submit(Request(1, "insert", 0, 1))
        assert entered.wait(5)
        vertices = [0, 1, 0]
        edges = [(0, 1), (1, 0), (0, 2)]
        snapshot = service.read_snapshot(vertices, edges, expected_version=1)
        vertices[:] = [2]
        edges[:] = [(2, 3)]
        second = service.submit(Request(2, "delete", 0, 1))
        try:
            assert not snapshot.done()
        finally:
            release.set()
        assert first.result(5) == Outcome(1, True, 1)
        assert snapshot.result(5) == ReadSnapshot(1, (1, 0, 1), (True, True, False))
        assert second.result(5) == Outcome(2, True, 2)
        assert service.read_snapshot([0], [(0, 1)]).result(5) == ReadSnapshot(
            2, (None,), (False,)
        )
        with pytest.raises(RuntimeError, match="stale"):
            service.read_snapshot([], [], expected_version=1).result(5)
        assert service.metrics()["state"] == "open"


def test_read_snapshot_invalid_bounds_reject_before_service_admission(
    tmp_path: Path,
) -> None:
    with create(tmp_path / "graph.db") as service:
        accepted = service.metrics()["accepted"]
        for vertices, edges, version in (
            ([33], [], None),
            ([True], [], None),
            ([], [(0, 33)], None),
            ([], [(0,)], None),
            ([], [], True),
            (list(range(33)) * 125, [], None),
        ):
            with pytest.raises(ValueError):
                service.read_snapshot(vertices, edges, expected_version=version)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="lists or tuples"):
            service.read_snapshot(iter([0]), [])  # type: ignore[arg-type]
        assert service.metrics()["accepted"] == accepted
        assert service.read_snapshot([], []).result(5) == ReadSnapshot(0, (), ())


def test_read_snapshot_owner_failure_fails_queued_work_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "graph.db"
    with create(path, batch_wait_ms=0) as service:
        assert service.submit(Request(1, "insert", 0, 1)).result(5).version == 1
        entered, release = threading.Event(), threading.Event()

        def fail_snapshot(*args: object, **kwargs: object) -> ReadSnapshot:
            entered.set()
            assert release.wait(5)
            raise OSError("injected owner storage/read failure")

        monkeypatch.setattr(service._owner, "read_snapshot", fail_snapshot)
        failed = service.read_snapshot([0], [(0, 1)])
        assert entered.wait(5)
        queued = service.status()
        release.set()
        with pytest.raises(OSError, match="storage/read"):
            failed.result(5)
        with pytest.raises(UnavailableError):
            queued.result(5)
        assert service.metrics()["state"] == "failed"
    with Durable(path) as recovered:
        assert recovered.read_snapshot([0, 1], [(0, 1)]) == ReadSnapshot(
            1, (1, 0), (True,)
        )
        assert recovered.check()


def test_history_is_a_bounded_owner_query_and_rejects_invalid_admission(
    tmp_path: Path,
) -> None:
    with create(tmp_path / "graph.db", batch_wait_ms=0) as service:
        invalid = service.metrics()["accepted"]
        for start, limit in ((0, 1), (None, 0), (None, 4097), (True, 1)):
            with pytest.raises(ValueError):
                service.history(start, limit)
        assert service.metrics()["accepted"] == invalid
        assert service.submit(Request(1, "insert", 0, 1)).result(5).version == 1
        assert service.submit(Request(2, "insert", 0, 1)).result(5).version == 1
        page = service.history(limit=1).result(5)
        assert isinstance(page, HistoryPage)
        assert page.latest_sequence == 2
        assert page.has_more
        assert page.records[0].sequence == 1 and page.records[0].changed
        second = service.history(start=2, limit=2).result(5)
        assert second.previous_digest == page.records[0].digest
        assert second.records[0].sequence == 2 and not second.records[0].changed


def test_default_read_reservation_preserves_queries_under_full_update_admission(
    tmp_path, monkeypatch
):
    with Service(
        tmp_path / "graph.db",
        n=16,
        width=0,
        queue_capacity=4,
        max_batch=1,
        max_operations=32,
        batch_wait_ms=0,
    ) as service:
        entered, release = threading.Event(), threading.Event()
        original = service._owner._persist

        def paused(rows):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test sync release timed out")
            original(rows)

        monkeypatch.setattr(service._owner, "_persist", paused)
        first = service.submit(edits(1, 1)[0])
        try:
            assert entered.wait(5)
            pending = [service.submit(request) for request in edits(2, 2)]
            for request in (edits(4, 1)[0], edits(1, 1)[0]):
                with pytest.raises(BusyError, match="query slots reserved"):
                    service.submit(request)
            queries = [service.partner(0)]
            assert not queries[0].done()
            assert service.metrics()["outstanding"] == 4
            assert service.metrics()["query_reserve"] == 1
            assert service.metrics()["next_admission_sequence"] == 4
            with pytest.raises(BusyError, match="outstanding"):
                service.status()
        finally:
            release.set()
        assert first.result(5) == Outcome(1, True, 1)
        assert completed(pending) == [Outcome(2, True, 2), Outcome(3, True, 3)]
        assert completed(queries)[0] in ((1, 1), (3, 1))
        assert service.submit(edits(4, 1)[0]).result(5) == Outcome(4, True, 4)
        assert service.metrics()["peak_outstanding"] == 4


def test_single_slot_service_defaults_to_no_reservation(tmp_path):
    with Service(
        tmp_path / "single.db",
        n=16,
        width=0,
        queue_capacity=1,
        max_batch=1,
        max_operations=32,
        batch_wait_ms=0,
    ) as service:
        assert service.metrics()["query_reserve"] == 0
        assert service.submit(edits(1, 1)[0]).result(5) == Outcome(1, True, 1)
        assert service.partner(0).result(5) == (1, 1)


def test_close_timeout_stops_admission_but_drains_without_cancelling_accepted_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "graph.db"
    service = create(path)
    entered, release = threading.Event(), threading.Event()
    original = service._owner._persist

    def paused(rows: list) -> None:
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test persistence release timed out")
        original(rows)

    monkeypatch.setattr(service._owner, "_persist", paused)
    receipts = [service.submit(r) for r in edits(1, 4)]
    try:
        assert entered.wait(5)
        receipts.extend(service.submit(r) for r in edits(5, 4))
        with pytest.raises(TimeoutError, match="draining"):
            service.close(0)
        with pytest.raises(UnavailableError):
            service.submit(edits(9, 1)[0])
        assert service.metrics()["state"] == "closing"
        with pytest.raises(BusyError, match="live owner"):
            Durable(path)
    finally:
        release.set()
        service.close(5)
    assert completed(receipts) == [Outcome(seq, True, seq) for seq in range(1, 9)]
    service.close(0)  # Idempotent after release.
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == 8 and recovered.check()


@pytest.mark.parametrize(
    "stage", ["prepare", "partial_write", "after_commit", "after_publish"]
)
def test_uncertain_update_fails_all_waiters_and_recovers_only_committed_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    path = tmp_path / "graph.db"
    service = create(path)
    entered, release = threading.Event(), threading.Event()
    original = service._owner._persist

    def failed(payload: object) -> None:
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test failure release timed out")
        if stage == "after_commit":
            original(payload)
        elif stage == "partial_write":
            db = service._owner._db()
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO operations VALUES(?,?,?,?,?,?,?)", payload[0])
        raise OSError("injected persistence/publication failure")

    if stage == "after_publish":
        from axiom.views import Views

        original_commit = Views.commit
        injected = False

        def cleanup_failure(owner: Views) -> None:
            nonlocal injected
            if injected:
                return original_commit(owner)
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test cleanup release timed out")
            original_commit(owner)
            injected = True
            raise OSError("injected post-publication cleanup failure")

        monkeypatch.setattr(Views, "commit", cleanup_failure)
    else:
        monkeypatch.setattr(service._owner, "_persist", failed)
    current = [service.submit(r) for r in edits(1, 4)]
    try:
        assert entered.wait(5)
        duplicate = service.submit(edits(1, 1)[0])
        queued = [service.submit(r) for r in edits(5, 4)]
        queued.append(service.status())
    finally:
        release.set()
    for receipt in current + [duplicate]:
        with pytest.raises(
            (OSError, RuntimeError), match="injected|publication cleanup"
        ):
            receipt.result(5)
    for receipt in queued:
        with pytest.raises(UnavailableError):
            receipt.result(5)
    service.close(5)
    assert service.metrics()["state"] == "failed"
    assert service.metrics()["outstanding"] == 0
    with pytest.raises(UnavailableError):
        service.submit(edits(9, 1)[0])
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == (4 if stage.startswith("after") else 0)
        assert recovered.check()
        if stage.startswith("after"):
            assert recovered.apply(edits(1, 4)) == tuple(
                Outcome(seq, True, seq) for seq in range(1, 5)
            )


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_sqlite_full_update_commit_fails_closed_and_recovers_exact_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    path = tmp_path / f"sqlite-full-{mode}.db"
    first = Request(1, "insert", 0, 1)
    second = Request(2, "delete", 0, 1)
    with create(path, mode=mode) as initialized:
        assert initialized.submit(first).result(5) == Outcome(1, True, 1)

    service = create(path, mode=mode, batch_wait_ms=0)

    def reject_commit(rows: list) -> None:
        database = service._owner._db()
        database.execute("BEGIN IMMEDIATE")
        database.execute("INSERT INTO operations VALUES(?, ?, ?, ?, ?, ?, ?)", rows[0])
        error = sqlite3.OperationalError("database or disk is full")
        error.sqlite_errorcode = SQLITEFULL
        raise error

    monkeypatch.setattr(service._owner, "_persist", reject_commit)
    receipt = service.submit(second)
    with pytest.raises(sqlite3.OperationalError) as failure:
        receipt.result(5)
    assert failure.value.sqlite_errorcode == SQLITEFULL
    assert service.metrics()["state"] == "failed"
    with pytest.raises(UnavailableError):
        service.partner(0)
    with pytest.raises(UnavailableError):
        service.has_edge(0, 1)
    service.close(5)

    with Durable(path, mode=mode) as recovered:
        assert recovered.status()["mode"] == mode
        assert recovered.status()["sequence"] == 1
        assert recovered.check()
        assert recovered.apply([first]) == (Outcome(1, True, 1),)
        assert recovered.apply([second]) == (Outcome(2, True, 2),)

    with Durable(path, mode=mode) as reopened:
        assert reopened.status()["sequence"] == 2
        assert reopened.partner(0) == (2, None)
        assert reopened.check()
        assert reopened.apply([second]) == (Outcome(2, True, 2),)

    from axiom.durable import RecoveryError

    incompatible = "multilevel" if mode == "basic" else "basic"
    with pytest.raises(RecoveryError, match="mode"):
        Durable(path, mode=incompatible)


def test_explicit_batch_is_one_isolated_durable_commit_and_exact_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "atomic-batch.db"
    with create(path, batch_wait_ms=100) as service:
        calls: list[int] = []
        original = service._owner._persist

        def counted(rows: list) -> None:
            calls.append(len(rows))
            original(rows)

        monkeypatch.setattr(service._owner, "_persist", counted)
        # Hold admission while enqueueing to make the boundaries deterministic.
        with service._condition:
            before = service.submit(Request(1, "insert", 0, 1))
            batch = service.submit_batch(
                [Request(2, "insert", 1, 2), Request(3, "insert", 2, 3)]
            )
            after = service.submit(Request(4, "delete", 0, 1))
        assert before.result(5) == Outcome(1, True, 1)
        assert batch.result(5) == (Outcome(2, True, 2), Outcome(3, True, 3))
        assert after.result(5) == Outcome(4, True, 4)
        assert calls == [1, 2, 1]
        assert service.metrics()["groups"] == 3
        assert service.metrics()["largest_group"] == 2
        assert service.status().result(5)["sequence"] == 4
        assert service.check().result(5)
        assert service.submit_batch(
            [Request(2, "insert", 2, 1), Request(3, "insert", 3, 2)]
        ).result(5) == (Outcome(2, True, 2), Outcome(3, True, 3))
        with pytest.raises(ValueError, match="payload"):
            service.submit_batch(
                [Request(2, "delete", 1, 2), Request(3, "insert", 2, 3)]
            ).result(5)
        assert service.metrics()["state"] == "open"
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == 4
        assert recovered.check()


@pytest.mark.parametrize(
    "batch, message",
    [
        ([], "nonempty"),
        ([Request(1, "insert", 0, 1), Request(3, "insert", 1, 2)], "contiguous"),
        ([Request(1, "insert", 0, 1), Request(1, "delete", 1, 2)], "contiguous"),
        ([Request(1, "insert", 0, 1)] * 5, "configured"),
        ([Request(1, "other", 0, 1)], "typed"),
        ([Request(True, "insert", 0, 1)], "sequence"),
        ([Request(1, "insert", 0, 33)], "v"),
    ],
)
def test_invalid_explicit_batch_does_not_consume_sequence_or_admission(
    tmp_path: Path, batch: list[Request], message: str
) -> None:
    with create(tmp_path / "invalid-batch.db") as service:
        with pytest.raises(ValueError, match=message):
            service.submit_batch(batch)
        assert service.metrics()["next_admission_sequence"] == 1
        assert service.metrics()["accepted"] == 0
        assert service.submit(Request(1, "insert", 0, 1)).result(5) == Outcome(
            1, True, 1
        )


def test_batch_capacity_rejection_consumes_no_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(
        tmp_path / "batch-capacity.db", queue_capacity=2, batch_wait_ms=0
    ) as service:
        entered, release = threading.Event(), threading.Event()
        original = service._owner._persist

        def paused(rows: list) -> None:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test persistence release timed out")
            original(rows)

        monkeypatch.setattr(service._owner, "_persist", paused)
        first = service.submit(Request(1, "insert", 0, 1))
        try:
            assert entered.wait(5)
            queued = service.submit(Request(2, "delete", 0, 1))
            with pytest.raises(BusyError, match="nothing was admitted"):
                service.submit_batch(
                    [Request(3, "insert", 0, 2), Request(4, "insert", 1, 2)]
                )
            assert service.metrics()["next_admission_sequence"] == 3
        finally:
            release.set()
        assert first.result(5) == Outcome(1, True, 1)
        assert queued.result(5) == Outcome(2, True, 2)
        assert service.submit_batch(
            [Request(3, "insert", 0, 2), Request(4, "insert", 1, 2)]
        ).result(5) == (Outcome(3, True, 3), Outcome(4, True, 4))


def test_pending_batch_retries_share_receipt_but_partial_overlap_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "pending-batch.db", batch_wait_ms=0) as service:
        entered, release = threading.Event(), threading.Event()
        original = service._owner._persist

        def paused(rows: list) -> None:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test persistence release timed out")
            original(rows)

        monkeypatch.setattr(service._owner, "_persist", paused)
        batch = [Request(1, "insert", 0, 1), Request(2, "insert", 1, 2)]
        try:
            with service._condition:
                first = service.submit_batch(batch)
            assert entered.wait(5)
            barrier = threading.Barrier(8)

            def retry() -> Receipt[tuple[Outcome, ...]]:
                barrier.wait(timeout=5)
                return service.submit_batch(
                    [Request(1, "insert", 1, 0), Request(2, "insert", 2, 1)]
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                duplicates = [executor.submit(retry) for _ in range(8)]
                retries = [client.result(5) for client in duplicates]
            with pytest.raises(ValueError, match="different bounds or payload"):
                service.submit_batch([Request(2, "insert", 1, 2)])
            with pytest.raises(ValueError, match="different bounds or payload"):
                service.submit_batch(
                    [Request(1, "delete", 0, 1), Request(2, "insert", 1, 2)]
                )
            assert service.metrics()["next_admission_sequence"] == 3
            assert service.metrics()["outstanding"] == 9
        finally:
            release.set()
        expected = (Outcome(1, True, 1), Outcome(2, True, 2))
        assert first.result(5) == expected
        assert [receipt.result(5) for receipt in retries] == [expected] * 8
        assert service.metrics()["accepted"] == service.metrics()["completed"] == 9
        assert service.check().result(5)


def test_historical_batch_retry_cannot_overlap_later_pending_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "historical-overlap.db", batch_wait_ms=0) as service:
        assert service.submit(Request(1, "insert", 0, 1)).result(5) == Outcome(
            1, True, 1
        )
        entered, release = threading.Event(), threading.Event()
        original = service._owner._persist

        def paused(rows: list) -> None:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test persistence release timed out")
            original(rows)

        monkeypatch.setattr(service._owner, "_persist", paused)
        second = service.submit(Request(2, "insert", 1, 2))
        try:
            assert entered.wait(5)
            with pytest.raises(ValueError, match="different bounds or payload"):
                service.submit_batch(
                    [Request(1, "insert", 0, 1), Request(2, "insert", 1, 2)]
                )
            assert service.metrics()["next_admission_sequence"] == 3
            assert service.metrics()["outstanding"] == 1
        finally:
            release.set()
        assert second.result(5) == Outcome(2, True, 2)
        assert service.metrics()["accepted"] == service.metrics()["completed"] == 2
        assert service.check().result(5)


@pytest.mark.parametrize("after_commit", [False, True])
def test_failed_explicit_batch_recovers_only_whole_durable_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_commit: bool,
) -> None:
    path = tmp_path / f"batch-failure-{after_commit}.db"
    service = create(path, batch_wait_ms=0)
    original = service._owner._persist

    def fail(rows: list) -> None:
        if after_commit:
            original(rows)
        raise OSError("injected batch persistence failure")

    monkeypatch.setattr(service._owner, "_persist", fail)
    receipt = service.submit_batch(
        [Request(1, "insert", 0, 1), Request(2, "insert", 1, 2)]
    )
    with pytest.raises(OSError, match="injected batch"):
        receipt.result(5)
    metrics = service.metrics()
    assert metrics["state"] == "failed"
    assert metrics["outstanding"] == 0
    assert metrics["groups"] == metrics["largest_group"] == 0
    service.close(5)
    with Durable(path) as recovered:
        expected_sequence = 2 if after_commit else 0
        assert recovered.status()["sequence"] == expected_sequence
        assert recovered.status()["version"] == expected_sequence
        assert recovered.check()
        if after_commit:
            assert recovered.apply(
                [Request(1, "insert", 0, 1), Request(2, "insert", 1, 2)]
            ) == (Outcome(1, True, 1), Outcome(2, True, 2))


def test_failure_during_acknowledgment_cannot_overwrite_already_delivered_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "graph.db"
    service = create(path)
    entered, release = threading.Event(), threading.Event()
    original = Receipt._finish
    injected = False

    def interrupt(
        receipt: Receipt[object],
        value: object,
        error: BaseException | None,
        started: int,
    ) -> None:
        nonlocal injected
        original(receipt, value, error, started)
        if isinstance(value, Outcome) and not injected:
            injected = True
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test acknowledgment release timed out")
            raise OSError("injected response delivery failure")

    monkeypatch.setattr(Receipt, "_finish", interrupt)
    receipts = [service.submit(r) for r in edits(1, 4)]
    clients = ThreadPoolExecutor(max_workers=1)
    try:
        assert entered.wait(5)
        first = receipts[0].result(5)
        assert first == Outcome(1, True, 1)
        queued = clients.submit(service.submit, edits(5, 1)[0])
    finally:
        release.set()
    for receipt in receipts[1:]:
        with pytest.raises(OSError, match="response delivery"):
            receipt.result(5)
    try:
        queued_receipt = queued.result(5)
    except UnavailableError:
        pass
    else:
        with pytest.raises(UnavailableError):
            queued_receipt.result(5)
    clients.shutdown()
    service.close(5)
    assert receipts[0].result(0) == first  # Previously delivered success stays success.
    assert service.metrics()["outstanding"] == 0
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == 4
        assert recovered.apply(edits(1, 4))[0] == first


def test_fresh_capacity_failure_rejects_without_admission_or_fail_stop(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capacity.db"
    with create(path, queue_capacity=1, max_batch=2, max_operations=1) as service:
        with pytest.raises(CapacityError):
            service.submit_batch(
                [Request(1, "insert", 0, 1), Request(2, "insert", 1, 2)]
            )
        assert service.metrics()["state"] == "open"
        assert service.status().result(5)["sequence"] == 0
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == 0 and recovered.status()["edges"] == 0
        assert recovered.check()


def test_bounded_group_container_failure_preserves_all_admission_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "graph.db") as service:

        def fail_take(queue: object) -> object:
            raise MemoryError("injected bounded group reservation failure")

        monkeypatch.setattr(service, "_take_slice", fail_take)
        with service._condition:
            receipts = [service.submit(r) for r in edits(1, 4)]
        for receipt in receipts:
            with pytest.raises(UnavailableError):
                receipt.result(5)
    assert service.metrics()["outstanding"] == 0
    assert service.metrics()["accepted"] == service.metrics()["completed"] == 4


def test_nonmutating_rejections_allow_reuse(tmp_path: Path) -> None:
    with create(tmp_path / "graph.db", batch_wait_ms=0) as service:
        assert service.submit(Request(1, "insert", 0, 1)).result(5).changed
        with pytest.raises(RuntimeError, match="stale"):
            service.page(version=0).result(5)
        assert service.checkpoint().result(5)["wal_pages"] >= 0
        assert service.submit(Request(2, "delete", 0, 1)).result(5) == Outcome(
            2, True, 2
        )
        assert service.check().result(5)


def test_failed_full_audit_disables_service_and_all_queued_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "graph.db") as service:
        monkeypatch.setattr(service._owner, "check", lambda: False)
        with service._condition:
            audit = service.check()
            query = service.status()
        with pytest.raises(UnavailableError, match="certificate"):
            audit.result(5)
        with pytest.raises(UnavailableError):
            query.result(5)
    assert service.metrics()["state"] == "failed"
    assert service.metrics()["maintenance_outstanding"] == 0


def test_maintenance_class_counts_queued_jobs_and_releases_all_slots_on_fail_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "graph.db", maintenance_capacity=2) as service:
        monkeypatch.setattr(service._owner, "check", lambda: False)
        with service._condition:
            audit = service.check()
            queued = service.checkpoint()
            assert service.metrics()["maintenance_outstanding"] == 2
            with pytest.raises(BusyError, match="maintenance"):
                service.checkpoint()
        for receipt in (audit, queued):
            with pytest.raises(UnavailableError):
                receipt.result(5)
    assert service.metrics()["maintenance_outstanding"] == 0
    assert service.metrics()["outstanding"] == 0


@pytest.mark.parametrize("stage", ["before_commit", "after_commit", "after_publish"])
def test_process_death_with_queued_clients_recovers_only_durable_prefix(
    tmp_path: Path, stage: str
) -> None:
    path = tmp_path / "crash.db"
    script = """
import os, sys
from axiom.service import Service
from axiom.durable import Request
stage = sys.argv[2]
s = Service(sys.argv[1], n=33, width=0, queue_capacity=16, max_batch=4,
            batch_wait_ms=100,
            max_operations=64)
if stage == 'after_publish':
    from axiom.views import Views
    original = Views.commit
    def die(owner):
        original(owner)
        os._exit(73)
    Views.commit = die
else:
    original = s._owner._persist
    def die(payload):
        if stage != 'before_commit':
            original(payload)
        os._exit(73)
    s._owner._persist = die
with s._condition:
    receipts = [s.submit(Request(seq, 'insert' if seq % 2 else 'delete', 0, 1))
                for seq in range(1, 9)]
receipts[0].result(5)
raise RuntimeError('death injection did not run')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), stage], timeout=10
    )
    assert result.returncode == 73
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == (0 if stage == "before_commit" else 4)
        assert recovered.check()
        if stage != "before_commit":
            assert recovered.apply(edits(1, 4)) == tuple(
                Outcome(seq, True, seq) for seq in range(1, 5)
            )


def test_expired_retry_refuses_without_new_mutation_or_disabling_service(
    tmp_path: Path,
) -> None:
    with create(tmp_path / "graph.db", queue_capacity=4) as service:
        for first in range(1, 21, 4):
            completed([service.submit(r) for r in edits(first, 4)])
        assert service.submit(edits(1, 1)[0]).result(5) == Outcome(1, True, 1)
        assert service.status().result(5)["sequence"] == 20
        assert service.metrics()["state"] == "open"
        assert service.submit(edits(20, 1)[0]).result(5) == Outcome(20, True, 20)


def test_concurrent_clients_and_queries_agree_with_exact_versioned_reference(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    rng, reference = random.Random(821), Matcher(33, mode="basic")
    requests, expected, partners = [], [], {0: {}}
    version = 0
    for seq in range(1, 513):
        adding, u, v = bool(rng.randrange(2)), rng.randrange(33), rng.randrange(33)
        operation = "insert" if adding else "delete"
        requests.append(Request(seq, operation, u, v))
        existed = reference.graph.has_edge(u, v)
        getattr(reference, operation)(u, v)
        changed = (not existed and u != v) if adding else (existed and u != v)
        version += changed
        expected.append(Outcome(seq, changed, version))
        partners[version] = dict(reference.partner_map)
    with create(
        path,
        queue_capacity=64,
        max_batch=8,
        max_operations=1024,
    ) as service:
        admission = threading.Lock()
        barrier = threading.Barrier(8)
        cursor, results, failures = 0, {}, []

        def writer() -> None:
            nonlocal cursor
            try:
                barrier.wait(timeout=5)
                while True:
                    with admission:
                        chunk = requests[cursor : cursor + 8]
                        cursor += len(chunk)
                        receipts = [service.submit(r) for r in chunk]
                    if not chunk:
                        break
                    for request, receipt in zip(chunk, receipts, strict=True):
                        results[request.sequence] = receipt.result(5)
            except BaseException as error:
                failures.append(error)

        def reader() -> None:
            try:
                barrier.wait(timeout=5)
                for index in range(256):
                    vertex = index % 33
                    version, partner = service.partner(vertex).result(5)
                    assert partners[version].get(vertex) == partner
            except BaseException as error:
                failures.append(error)

        workers = [threading.Thread(target=writer) for _ in range(4)]
        workers.extend(threading.Thread(target=reader) for _ in range(4))
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        assert all(not worker.is_alive() for worker in workers) and failures == []
        assert [results[seq] for seq in range(1, 513)] == expected
        assert service.check().result(5)
        assert service.metrics()["peak_outstanding"] <= 64
    with Durable(path) as recovered:
        for u in range(33):
            assert recovered.partner(u)[1] == reference.partner_map.get(u)
            for v in range(u + 1, 33):
                assert recovered.has_edge(u, v)[1] == reference.graph.has_edge(u, v)


@pytest.mark.parametrize(
    "options",
    [
        {"queue_capacity": 0},
        {"queue_capacity": True},
        {"queue_capacity": 16385},
        {"batch_wait_ms": -1},
        {"batch_wait_ms": float("nan")},
        {"batch_wait_ms": float("inf")},
        {"batch_wait_ms": True},
        {"batch_wait_ms": 10**1000},
        {"maintenance_capacity": 0},
        {"maintenance_capacity": True},
        {"maintenance_capacity": 65},
        {"queue_capacity": 4, "maintenance_capacity": 5},
        {"query_reserve": -1},
        {"query_reserve": True},
        {"query_reserve": 16},
    ],
)
def test_invalid_service_policy_releases_any_acquired_owner(
    tmp_path: Path, options: dict
) -> None:
    path = tmp_path / "graph.db"
    with pytest.raises(ValueError):
        create(path, **options)
    if path.exists():
        with Durable(path) as store:
            assert store.check()


def test_store_mode_is_persisted_and_mismatch_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mode.db"
    with Service(path, n=16, width=0) as service:
        assert service.status().result(5)["mode"] == "basic"
    from axiom.durable import RecoveryError

    with pytest.raises(RecoveryError, match="mode"):
        Service(path, mode="multilevel")


@pytest.mark.parametrize("timeout", [-1, True, float("inf"), float("nan"), 10**1000])
def test_invalid_wait_timeout_cannot_cancel_work(
    tmp_path: Path, timeout: float
) -> None:
    with create(tmp_path / "graph.db") as service:
        receipt = service.status()
        with pytest.raises(ValueError):
            receipt.result(timeout)
        with pytest.raises(ValueError):
            service.close(timeout)
        assert receipt.result(5)["sequence"] == 0
        assert service.metrics()["state"] == "open"
