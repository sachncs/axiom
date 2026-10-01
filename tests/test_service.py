"""Bounded threaded admission, group durability, coherent reads and shutdown."""

import random
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_engine import Reference

from axiom.durable import (
    BusyError,
    CapacityError,
    Durable,
    ExpiredError,
    Outcome,
    Request,
    UnavailableError,
)
from axiom.service import Receipt, Service


def create(path: Path, **options: object) -> Service:
    settings = dict(
        n=33,
        width=0,
        queue_capacity=16,
        query_reserve=0,  # Legacy full-capacity tests; reservation tested separately.
        max_batch=4,
        batch_wait_ms=100,
        checkpoint_interval=8,
        retain_operations=32,
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


def test_grouped_single_requests_preserve_results_versions_and_exact_recovery(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    with create(path) as service:
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
        assert status["sequence"] == 100 and status["checkpoint_generation"] == 12
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
        tmp_path / "graph.db", queue_capacity=4, max_batch=2, batch_wait_ms=0
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
            assert query.done() and query.result(0) == (0, None)
            duplicate = service.submit(edits(1, 1)[0])
            with pytest.raises(BusyError, match="nothing was admitted"):
                service.submit(edits(4, 1)[0])
            with pytest.raises(BusyError):
                service.partner(1)
            assert service.metrics()["outstanding"] == 4
            assert service.metrics()["next_admission_sequence"] == 4
            with pytest.raises(TimeoutError, match="may still commit"):
                first.result(0)
            assert not first.done() and first.timing() is None
        finally:
            release.set()
        assert first.result(5) == Outcome(1, True, 1)
        assert completed(pending) == [Outcome(2, True, 2), Outcome(3, True, 3)]
        assert duplicate.result(5) == first.result(5)
        assert service.submit(edits(4, 1)[0]).result(5) == Outcome(4, True, 4)
        assert service.metrics()["peak_outstanding"] == 4


@pytest.mark.parametrize("maintenance", [False, True])
def test_partner_reads_published_state_during_owner_sync_without_queueing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, maintenance: bool
) -> None:
    with create(tmp_path / "graph.db", batch_wait_ms=0) as service:
        assert service.submit(Request(1, "insert", 0, 1)).result(5) == Outcome(
            1, True, 1
        )
        entered, release = threading.Event(), threading.Event()
        target = "_persist_checkpoint" if maintenance else "_persist"
        original = getattr(service._owner, target)

        def paused(payload: object) -> None:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test sync release timed out")
            original(payload)

        monkeypatch.setattr(service._owner, target, paused)
        work = (
            service.checkpoint()
            if maintenance
            else service.submit(Request(2, "delete", 0, 1))
        )
        try:
            assert entered.wait(5)
            for _ in range(100):
                for vertex, partner in ((0, 1), (1, 0), (2, None)):
                    receipt = service.partner(vertex)
                    assert receipt.done() and receipt.result(0) == (1, partner)
            assert not work.done()
            assert service.metrics()["outstanding"] == 1
        finally:
            release.set()
        work.result(5)
        assert service.partner(0).result(0) == ((1, 1) if maintenance else (2, None))
        assert service.check().result(5)


def test_default_read_reservation_preserves_queries_under_full_update_admission(
    tmp_path, monkeypatch
):
    with Service(
        tmp_path / "graph.db",
        n=16,
        width=0,
        queue_capacity=4,
        max_batch=1,
        checkpoint_interval=8,
        retain_operations=8,
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
            for _ in range(100):
                assert service.partner(0).result(0) == (0, None)
            assert service.metrics()["outstanding"] == 3
            assert service.metrics()["query_reserve"] == 1
            assert service.metrics()["next_admission_sequence"] == 4
            status = service.status()  # Other reads still share the global bound.
            with pytest.raises(BusyError, match="outstanding"):
                service.partner(0)
        finally:
            release.set()
        assert first.result(5) == Outcome(1, True, 1)
        assert completed(pending) == [Outcome(2, True, 2), Outcome(3, True, 3)]
        assert status.result(5)["sequence"] in (1, 2, 3)
        assert service.submit(edits(4, 1)[0]).result(5) == Outcome(4, True, 4)
        assert service.metrics()["peak_outstanding"] == 4


def test_single_slot_service_defaults_to_no_reservation(tmp_path):
    with Service(
        tmp_path / "single.db",
        n=16,
        width=0,
        queue_capacity=1,
        max_batch=1,
        checkpoint_interval=8,
        retain_operations=8,
        max_operations=32,
        batch_wait_ms=0,
    ) as service:
        assert service.metrics()["query_reserve"] == 0
        assert service.submit(edits(1, 1)[0]).result(5) == Outcome(1, True, 1)
        assert service.partner(0).result(0) == (1, 1)


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
    original = (
        service._owner._publish if stage == "after_publish" else service._owner._persist
    )

    def failed(payload: object) -> None:
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test failure release timed out")
        if stage in ("after_commit", "after_publish"):
            original(payload)
        elif stage == "partial_write":
            db = service._owner._db()
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO operations VALUES(?,?,?,?,?,?,?)", payload[0])
        raise OSError("injected persistence/publication failure")

    target = "_publish" if stage == "after_publish" else "_persist"
    monkeypatch.setattr(service._owner, target, failed)
    current = [service.submit(r) for r in edits(1, 4)]
    try:
        assert entered.wait(5)
        duplicate = service.submit(edits(1, 1)[0])
        queued = [service.submit(r) for r in edits(5, 4)]
        queued.append(service.status())
    finally:
        release.set()
    for receipt in current + [duplicate]:
        with pytest.raises(OSError, match="injected"):
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


def test_failure_during_acknowledgment_cannot_overwrite_already_delivered_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "graph.db"
    service = create(path)
    entered, release = threading.Event(), threading.Event()
    original = service._finish
    injected = False

    def interrupt(work: object, value: object, error: object) -> None:
        nonlocal injected
        original(work, value, error)
        if isinstance(value, Outcome) and not injected:
            injected = True
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test acknowledgment release timed out")
            raise OSError("injected response delivery failure")

    monkeypatch.setattr(service, "_finish", interrupt)
    receipts = [service.submit(r) for r in edits(1, 4)]
    try:
        assert entered.wait(5)
        first = receipts[0].result(5)
        assert first == Outcome(1, True, 1)
        queued = service.submit(edits(5, 1)[0])
    finally:
        release.set()
    for receipt in receipts[1:]:
        with pytest.raises(OSError, match="response delivery"):
            receipt.result(5)
    with pytest.raises(UnavailableError):
        queued.result(5)
    service.close(5)
    assert receipts[0].result(0) == first  # Previously delivered success stays success.
    assert service.metrics()["outstanding"] == 0
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == 4
        assert recovered.apply(edits(1, 4))[0] == first


def test_fresh_capacity_failure_rolls_back_group_and_stops_sequenced_service(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capacity.db"
    with create(path, max_batch=2, max_snapshot_bytes=40 + 8 * 33 + 8) as service:
        with service._condition:
            receipts = [
                service.submit(Request(1, "insert", 0, 1)),
                service.submit(Request(2, "insert", 1, 2)),
            ]
        for receipt in receipts:
            with pytest.raises(CapacityError):
                receipt.result(5)
    assert service.metrics()["state"] == "failed"
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


def test_nonmutating_rejections_and_checkpoint_reservation_failure_allow_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "graph.db", batch_wait_ms=0) as service:
        assert service.submit(Request(1, "insert", 0, 1)).result(5).changed
        with pytest.raises(RuntimeError, match="stale"):
            service.page(version=0).result(5)
        original = service._owner._checkpoint_record

        def fail_record() -> object:
            raise MemoryError("injected pre-persistence reservation failure")

        monkeypatch.setattr(service._owner, "_checkpoint_record", fail_record)
        with pytest.raises(MemoryError):
            service.checkpoint().result(5)
        assert service.metrics()["state"] == "open"
        monkeypatch.setattr(service._owner, "_checkpoint_record", original)
        assert service.checkpoint().result(5)["generation"] == 1
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
            batch_wait_ms=100, checkpoint_interval=8, retain_operations=32,
            max_operations=64)
name = '_publish' if stage == 'after_publish' else '_persist'
original = getattr(s._owner, name)
def die(payload):
    if stage != 'before_commit':
        original(payload)
    os._exit(73)
setattr(s._owner, name, die)
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
    with create(
        tmp_path / "graph.db", queue_capacity=4, retain_operations=4
    ) as service:
        for first in range(1, 21, 4):
            completed([service.submit(r) for r in edits(first, 4)])
        with pytest.raises(ExpiredError):
            service.submit(edits(1, 1)[0]).result(5)
        assert service.status().result(5)["sequence"] == 20
        assert service.metrics()["state"] == "open"
        assert service.submit(edits(20, 1)[0]).result(5) == Outcome(20, True, 20)


def test_concurrent_clients_and_queries_agree_with_exact_versioned_reference(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    rng, reference = random.Random(821), Reference(33)
    requests, expected, partners = [], [], {0: {}}
    for seq in range(1, 513):
        adding, u, v = bool(rng.randrange(2)), rng.randrange(33), rng.randrange(33)
        requests.append(Request(seq, "insert" if adding else "delete", u, v))
        changed = reference.edit(u, v, adding)
        expected.append(Outcome(seq, changed, reference.version))
        partners[reference.version] = dict(reference.partners)
    with create(
        path,
        queue_capacity=64,
        max_batch=8,
        retain_operations=64,
        checkpoint_interval=32,
        max_operations=128,
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
            assert recovered.partner(u)[1] == reference.partners.get(u)
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
        {"queue_capacity": 33},
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


def test_service_does_not_implicitly_upgrade_legacy_and_defaults_new_store_to_v2(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy.db"
    with Durable(legacy, n=16):
        pass
    with pytest.raises(ValueError, match="v2"):
        Service(legacy)
    with Durable(legacy) as store:
        assert store.check()
    with Service(tmp_path / "new.db", n=16) as service:
        assert service.status().result(5)["checkpoint_interval"] == 32768


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
