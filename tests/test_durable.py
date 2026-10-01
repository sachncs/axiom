"""Durable publication, retry, recovery, and bounded-owner regression tests."""

import gc
import hashlib
import json
import random
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from axiom.durable import (
    BusyError,
    CapacityError,
    Durable,
    Outcome,
    RecoveryError,
    Request,
    UnavailableError,
)
from axiom.engine import Engine


def snapshot(store: Durable) -> tuple:
    status = store.status()
    vertices = status["vertices"]
    assert isinstance(vertices, int)
    return (
        status["version"],
        status["sequence"],
        status["edges"],
        status["matching"],
        tuple(store.partner(u) for u in range(vertices)),
        tuple(
            (u, v)
            for u in range(vertices)
            for v in range(u + 1, vertices)
            if store.has_edge(u, v)[1]
        ),
    )


def test_batch_acknowledgment_retries_and_exact_recovery(tmp_path: Path) -> None:
    path = tmp_path / "graph.db"
    requests = [
        Request(1, "delete", 1, 0),
        Request(2, "insert", 0, 4),
        Request(3, "insert", 4, 0),
        Request(4, "delete", 0, 0),
    ]
    with Durable(path, n=16) as store:
        result = store.apply(requests)
        assert result == (
            Outcome(1, True, 2),
            Outcome(2, True, 3),
            Outcome(3, False, 3),
            Outcome(4, False, 3),
        )
        assert store.apply(requests) == result
        assert store.apply([requests[0], requests[0]]) == (result[0], result[0])
        before = snapshot(store)
        assert store.check()
    with Durable(path) as store:
        assert snapshot(store) == before and store.check()
        assert store.apply(requests) == result
        assert store.status()["synchronous"] == "FULL"
        assert store.status()["fullfsync"] == 1


def test_invalid_admission_is_atomic_and_subsequent_valid_use_works(
    tmp_path: Path,
) -> None:
    with Durable(tmp_path / "graph.db", n=16, max_batch=4) as store:
        before = snapshot(store)
        for requests, error in (
            ([Request(2, "insert", 0, 4)], ValueError),
            ([Request(1, "insert", 0, 16)], ValueError),
            ([Request(1, "insert", 0, 4), Request(1, "delete", 0, 4)], ValueError),
            ([Request(1, "insert", 0, 4)] * 5, CapacityError),
            ([Request(True, "insert", 0, 4)], ValueError),
        ):
            with pytest.raises(error):
                store.apply(requests)
            assert snapshot(store) == before
        result = store.apply([Request(1, "insert", 0, 4)] * 2)
        assert result == (Outcome(1, True, 2),) * 2
        with pytest.raises(ValueError, match="differs"):
            store.apply([Request(1, "delete", 0, 4)])
        assert store.status()["sequence"] == 1


def test_history_capacity_rejects_before_edit_and_preserves_retries(
    tmp_path: Path,
) -> None:
    with Durable(tmp_path / "graph.db", n=16, max_operations=2) as store:
        requests = [Request(1, "delete", 0, 1), Request(2, "insert", 0, 4)]
        result = store.apply(requests)
        before = snapshot(store)
        with pytest.raises(CapacityError, match="history"):
            store.apply([Request(3, "delete", 1, 2)])
        assert snapshot(store) == before
        assert store.apply(requests) == result


def test_native_budget_failure_restores_entire_batch_without_durable_rows(
    tmp_path: Path,
) -> None:
    metadata = Engine(16).memory()["allocated"]
    with Durable(tmp_path / "graph.db", n=16, width=0, budget=metadata + 416) as store:
        before = snapshot(store)
        with pytest.raises(MemoryError):
            store.apply([Request(i, "insert", 0, i) for i in range(1, 8)])
        assert snapshot(store) == before and store.check()
        assert store.apply([Request(1, "insert", 0, 15)]) == (Outcome(1, True, 1),)


@pytest.mark.parametrize(
    "stage", ["before_write", "after_partial_write", "after_commit", "after_publish"]
)
def test_persistence_or_publication_failure_is_fail_stop_and_retries_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    path = tmp_path / "graph.db"
    store = Durable(path, n=16)
    original_persist, original_publish = store._persist, store._publish
    request = Request(1, "delete", 0, 1)

    def fail_persist(rows: list) -> None:
        if stage == "after_partial_write":
            db = store._db()
            db.execute("BEGIN IMMEDIATE")
            db.executemany("INSERT INTO operations VALUES(?,?,?,?,?,?,?)", rows)
        elif stage == "after_commit":
            original_persist(rows)
        raise OSError("injected disk/barrier failure")

    def fail_publish(token: int) -> None:
        original_publish(token)
        raise OSError("injected post-publication acknowledgment loss")

    if stage == "after_publish":
        monkeypatch.setattr(store, "_publish", fail_publish)
    else:
        monkeypatch.setattr(store, "_persist", fail_persist)
    with pytest.raises(OSError):
        store.apply([request])
    for query in (
        store.status,
        store.check,
        lambda: store.partner(0),
        lambda: store.apply([request]),
    ):
        with pytest.raises(UnavailableError):
            query()
    store.close()
    with Durable(path) as recovered:
        committed = stage in ("after_commit", "after_publish")
        assert recovered.status()["sequence"] == int(committed)
        assert recovered.has_edge(0, 1)[1] == (not committed)
        assert recovered.apply([request]) == (Outcome(1, True, 2),)
        assert recovered.status()["sequence"] == 1 and recovered.check()


def test_private_state_is_not_visible_and_concurrent_admission_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, release = Event(), Event()
    with Durable(tmp_path / "graph.db", n=16) as store:
        original = store._persist

        def paused(rows: list) -> None:
            prepared.set()
            assert release.wait(5)
            original(rows)

        monkeypatch.setattr(store, "_persist", paused)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(store.apply, [Request(1, "delete", 0, 1)])
            assert prepared.wait(5)
            try:
                for operation in (
                    store.status,
                    store.close,
                    lambda: store.partner(0),
                    lambda: store.apply([Request(2, "insert", 0, 4)]),
                ):
                    with pytest.raises(BusyError):
                        operation()
            finally:
                release.set()
            assert future.result(timeout=5) == (Outcome(1, True, 2),)
        assert store.partner(0)[0] == 2 and not store.has_edge(0, 1)[1]


def test_single_process_owner_and_lock_reuse(tmp_path: Path) -> None:
    path = tmp_path / "graph.db"
    with Durable(path, n=16), pytest.raises(BusyError):
        Durable(path)
    with Durable(path) as store:
        assert store.check()
    with pytest.raises(ValueError, match="differs"):
        Durable(path, n=17)
    with Durable(path) as store:
        assert store.check()


@pytest.mark.parametrize(
    "corruption", ["checksum", "missing_tail", "outcome", "format", "control"]
)
def test_semantic_corruption_refuses_recovery(tmp_path: Path, corruption: str) -> None:
    path = tmp_path / "graph.db"
    with Durable(path, n=16) as store:
        store.apply([Request(1, "delete", 0, 1), Request(2, "insert", 0, 4)])
    with closing(sqlite3.connect(path)) as db, db:
        if corruption == "checksum":
            db.execute("UPDATE operations SET digest=zeroblob(32) WHERE sequence=1")
        elif corruption == "missing_tail":
            db.execute("DELETE FROM operations WHERE sequence=2")
        elif corruption == "outcome":
            db.execute("UPDATE operations SET changed=0 WHERE sequence=1")
        elif corruption == "format":
            metadata = json.loads(
                db.execute("SELECT metadata FROM control").fetchone()[0]
            )
            metadata["backend"] = "unknown"
            db.execute("UPDATE control SET metadata=?", (json.dumps(metadata),))
        else:
            db.execute("UPDATE control SET version=777")
    with pytest.raises(RecoveryError):
        Durable(path)


@pytest.mark.parametrize("stage", ["before_commit", "after_commit", "after_publish"])
def test_process_death_recovers_only_committed_history(
    tmp_path: Path, stage: str
) -> None:
    path = tmp_path / "graph.db"
    script = """
import os, sys
from axiom.durable import Durable, Request
store=Durable(sys.argv[1], n=16)
stage=sys.argv[2]
persist, publish=store._persist, store._publish
def crash_persist(rows):
    if stage == 'before_commit':
        db=store._db()
        db.execute('BEGIN IMMEDIATE')
        db.executemany('INSERT INTO operations VALUES(?,?,?,?,?,?,?)', rows)
    else:
        persist(rows)
    os._exit(73)
def crash_publish(token):
    publish(token)
    os._exit(73)
if stage == 'after_publish':
    store._publish=crash_publish
else:
    store._persist=crash_persist
store.apply([Request(1,'delete',0,1), Request(2,'insert',0,4)])
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(path), stage], timeout=15
    )
    assert process.returncode == 73
    with Durable(path) as store:
        committed = stage != "before_commit"
        assert store.status()["sequence"] == (2 if committed else 0)
        assert store.has_edge(0, 1)[1] == (not committed)
        assert store.check()
        assert store.apply(
            [Request(1, "delete", 0, 1), Request(2, "insert", 0, 4)]
        ) == (
            Outcome(1, True, 2),
            Outcome(2, True, 3),
        )


def test_close_is_idempotent_and_closed_calls_reject(tmp_path: Path) -> None:
    store = Durable(tmp_path / "graph.db", n=0, width=0)
    assert store.page() == (0, [], None) and store.apply([]) == ()
    store.close()
    store.close()
    assert not hasattr(store, "_engine")
    with pytest.raises(UnavailableError):
        store.status()


def test_sqlite_page_limit_failure_recovers_last_acknowledged_batch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "full.db"
    store = Durable(
        path, n=4, width=0, max_database_bytes=1 << 20, max_operations=32768
    )
    last_sequence = 0
    try:
        for first in range(1, 32769, 256):
            requests = [
                Request(seq, "insert" if seq % 2 else "delete", 0, 1)
                for seq in range(first, first + 256)
            ]
            try:
                store.apply(requests)
            except sqlite3.DatabaseError as error:
                assert "full" in str(error).lower()
                with pytest.raises(UnavailableError):
                    store.status()
                break
            last_sequence = first + 255
        else:
            pytest.fail("expected a real SQLite page-limit/disk-full rejection")
    finally:
        store.close()
    assert 0 < last_sequence < 32768
    with Durable(path, max_database_bytes=1 << 20, max_operations=32768) as recovered:
        assert recovered.status()["sequence"] == last_sequence
        assert recovered.status()["version"] == last_sequence
        assert recovered.status()["edges"] == recovered.status()["matching"] == 0
        assert recovered.check()


def test_mixed_batches_match_independent_python_reference_across_restarts(
    tmp_path: Path,
) -> None:
    from test_engine import Reference

    path = tmp_path / "graph.db"
    oracle = Reference(33)
    rng = random.Random(813)
    with Durable(path, n=33, width=0) as store:
        for first in range(1, 801, 40):
            requests, expected = [], []
            for sequence in range(first, first + 40):
                u, v = rng.randrange(33), rng.randrange(33)
                adding = bool(rng.randrange(2))
                changed = oracle.edit(u, v, adding)
                requests.append(
                    Request(sequence, "insert" if adding else "delete", u, v)
                )
                expected.append(Outcome(sequence, changed, oracle.version))
            assert store.apply(requests) == tuple(expected)
            assert store.check()
        before = snapshot(store)
    with Durable(path) as recovered:
        assert snapshot(recovered) == before
        assert recovered.status()["version"] == oracle.version
        for u in range(33):
            assert recovered.partner(u)[1] == oracle.partners.get(u)
            for v in range(u + 1, 33):
                assert recovered.has_edge(u, v)[1] == oracle.graph.has_edge(u, v)


def test_checksum_valid_wrong_outcome_still_fails_deterministic_replay(
    tmp_path: Path,
) -> None:
    from axiom.durable import _digest

    path = tmp_path / "wrong-outcome.db"
    with Durable(path, n=16) as store:
        store.apply([Request(1, "delete", 0, 1), Request(2, "insert", 0, 4)])
    with closing(sqlite3.connect(path)) as db, db:
        metadata = db.execute("SELECT metadata FROM control").fetchone()[0]
        tail = hashlib.sha256(metadata.encode()).digest()
        rows = db.execute("SELECT * FROM operations ORDER BY sequence").fetchall()
        for seq, adding, u, v, changed, version, _ in rows:
            changed = 0 if seq == 1 else changed
            tail = _digest(tail, seq, adding, u, v, bool(changed), version)
            db.execute(
                "UPDATE operations SET changed=?,digest=? WHERE sequence=?",
                (changed, tail, seq),
            )
        db.execute("UPDATE control SET digest=?", (tail,))
    with pytest.raises(RecoveryError, match="operation history") as error:
        Durable(path)
    assert "outcome disagrees" in str(error.value.__cause__)


def test_failed_independent_audit_disables_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Durable(tmp_path / "graph.db", n=16) as store:
        monkeypatch.setattr(store, "_engine", SimpleNamespace(check=lambda: False))
        assert store.check() is False
        with pytest.raises(UnavailableError):
            store.apply([Request(1, "delete", 0, 1)])


def test_live_retry_corruption_never_becomes_a_success_acknowledgment(
    tmp_path: Path,
) -> None:
    with Durable(tmp_path / "graph.db", n=16) as store:
        request = Request(1, "delete", 0, 1)
        assert store.apply([request]) == (Outcome(1, True, 2),)
        store._db().execute("UPDATE operations SET changed=0 WHERE sequence=1")
        with pytest.raises(RecoveryError, match="checksum"):
            store.apply([request])
        with pytest.raises(UnavailableError):
            store.partner(0)


def test_other_process_cannot_create_a_second_live_owner(tmp_path: Path) -> None:
    path = tmp_path / "graph.db"
    with Durable(path, n=16):
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from axiom.durable import Durable, BusyError\n"
                "try: Durable(sys.argv[1])\n"
                "except BusyError: sys.exit(0)\n"
                "sys.exit(99)",
                str(path),
            ],
            timeout=10,
        )
        assert process.returncode == 0


def test_truncated_database_refuses_recovery(tmp_path: Path) -> None:
    path = tmp_path / "broken.db"
    with Durable(path, n=16) as store:
        store.apply([Request(1, "delete", 0, 1)])
    with path.open("r+b") as damaged:
        damaged.truncate(200)
    with pytest.raises((sqlite3.DatabaseError, RecoveryError)):
        Durable(path)


def test_abandoned_owner_cleanup_does_not_leak_process_lock(tmp_path: Path) -> None:
    path = tmp_path / "graph.db"
    store = Durable(path, n=16)
    with pytest.warns(ResourceWarning, match="unclosed durable owner"):
        del store
        gc.collect()
    with Durable(path) as recovered:
        assert recovered.check()
