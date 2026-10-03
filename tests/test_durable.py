"""Durable paper-matcher replay, atomicity, and bounded-history tests."""

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from axiom import core
from axiom.core import Matcher
from axiom.durable import (
    PAPER_CHUNK,
    CapacityError,
    Durable,
    Outcome,
    RecoveryError,
    Request,
    UnavailableError,
    _digest,
)
from axiom.witness import Witness

MODES = ("basic", "multilevel")


def state(store: Durable) -> tuple:
    """Capture externally visible graph state independently of implementation."""
    status = store.status()
    vertices = status["vertices"]
    return (
        status["mode"],
        status["sequence"],
        status["version"],
        status["edges"],
        status["matching"],
        tuple(store.partner(vertex) for vertex in range(vertices)),
        tuple(
            (left, right)
            for left in range(vertices)
            for right in range(left + 1, vertices)
            if store.has_edge(left, right)[1]
        ),
    )


def witness(store: Durable) -> bytes:
    """Capture the exact in-memory paper state between transactions."""
    return Witness().capture(store._matcher)


def requests() -> list[Request]:
    return [
        Request(1, "insert", 0, 1),
        Request(2, "insert", 2, 3),
        Request(3, "delete", 1, 0),
        Request(4, "insert", 0, 2),
        Request(5, "delete", 7, 8),
    ]


def test_durable_defaults_to_basic_and_rejects_native_matching_mode(
    tmp_path: Path,
) -> None:
    path = tmp_path / "default.db"
    with Durable(path, n=8, width=0) as store:
        assert store.status()["mode"] == "basic"
        assert store.check()
    with pytest.raises(ValueError, match="basic.*multilevel"):
        Durable(tmp_path / "native.db", n=8, mode="native")


@pytest.mark.parametrize("mode", MODES)
def test_exact_witness_replay_after_restart_for_each_paper_mode(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"{mode}.db"
    with Durable(path, n=16, width=0, mode=mode) as store:
        result = store.apply(requests())
        expected = state(store)
        expected_witness = witness(store)
        assert store.check()

    with Durable(path, mode=mode) as recovered:
        assert state(recovered) == expected
        assert witness(recovered) == expected_witness
        assert recovered.apply(requests()) == result
        assert recovered.check()


@pytest.mark.parametrize("mode", MODES)
def test_history_pages_include_nonzero_genesis_graph_version(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"history-{mode}.db"
    with Durable(path, n=8, mode=mode) as store:
        base_version = store.status()["version"]
        outcome = store.apply([Request(1, "insert", 0, 4)])[0]
        page = store.history()
        assert page.records[0].version == outcome.version == base_version + 1
        assert len(page.previous_digest) == 32
    with Durable(path, mode=mode) as recovered:
        assert recovered.history().records[0].version == outcome.version


@pytest.mark.parametrize("mode", MODES)
def test_later_matcher_failure_rolls_back_whole_durable_batch_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    path = tmp_path / f"{mode}.db"
    store = Durable(path, n=20, width=0, mode=mode)
    before = state(store)
    before_witness = witness(store)
    original = Matcher.insert
    attempts = 0

    def fail_second(matcher: Matcher, left: int, right: int) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("injected later paper update failure")
        original(matcher, left, right)

    monkeypatch.setattr(Matcher, "insert", fail_second)
    with pytest.raises(RuntimeError, match="later paper update"):
        store.apply(
            [
                Request(1, "insert", 0, 1),
                Request(2, "insert", 2, 3),
                Request(3, "insert", 4, 5),
            ]
        )
    assert attempts == 2
    assert witness(store) == before_witness
    assert state(store) == before
    assert store.check()
    store.close()
    monkeypatch.undo()

    with closing(sqlite3.connect(path)) as database:
        assert database.execute("SELECT count(*) FROM operations").fetchone() == (0,)
        assert database.execute("SELECT sequence,version FROM control").fetchone() == (
            0,
            0,
        )
    with Durable(path, mode=mode) as recovered:
        assert state(recovered) == before
        assert witness(recovered) == before_witness
        assert recovered.check()


@pytest.mark.parametrize("mode", MODES)
def test_failure_in_later_private_slice_restores_committed_matcher_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    path = tmp_path / f"sliced-{mode}.db"
    store = Durable(path, n=32, width=0, mode=mode, max_batch=24)
    before_status = store.status()
    before_history = store.history()
    before = witness(store)
    original = Matcher.insert
    attempts = 0

    def fail_after_first_private_slice(matcher: Matcher, left: int, right: int) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 10:
            raise RuntimeError("injected later-slice failure")
        original(matcher, left, right)

    monkeypatch.setattr(Matcher, "insert", fail_after_first_private_slice)
    batch = [
        Request(sequence, "insert", 2 * sequence, 2 * sequence + 1)
        for sequence in range(1, 13)
    ]
    with pytest.raises(RuntimeError, match="later-slice"):
        store.apply(batch)

    assert attempts == 10
    assert witness(store) == before
    assert store.status() == before_status
    assert store.history() == before_history
    assert store.check()
    with closing(sqlite3.connect(path)) as database:
        assert (
            database.execute(
                "SELECT sequence,adding,u,v,changed,version,digest "
                "FROM operations ORDER BY sequence"
            ).fetchall()
            == []
        )
        assert database.execute(
            "SELECT sequence,version FROM control WHERE id=1"
        ).fetchone() == (before_status["sequence"], before_status["version"])

    assert store.apply(batch) == tuple(
        Outcome(sequence, True, sequence) for sequence in range(1, 13)
    )
    assert store.check()
    assert store.status()["sequence"] == len(batch)
    assert tuple(record.sequence for record in store.history().records) == tuple(
        range(1, len(batch) + 1)
    )
    committed = state(store)
    committed_witness = witness(store)
    store.close()
    with Durable(path, mode=mode) as recovered:
        assert state(recovered) == committed
        assert witness(recovered) == committed_witness
        assert recovered.check()


@pytest.mark.parametrize("mode", MODES)
def test_large_durable_group_releases_paper_journal_after_each_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """A large durable group must not accumulate bounded paper undo cells."""
    path = tmp_path / f"journal-window-{mode}.db"
    store = Durable(path, n=64, width=0, mode=mode, max_batch=32)
    original = Matcher.batch
    journals = []

    @contextmanager
    def observe_batch(
        matcher: Matcher,
        max_operations: int = 256,
        before_publish=None,
    ):
        with original(matcher, max_operations, before_publish):
            journals.append(matcher.classes)
            yield matcher

    monkeypatch.setattr(Matcher, "batch", observe_batch)
    batch = [
        Request(sequence, "insert", 2 * sequence, 2 * sequence + 1)
        for sequence in range(1, 25)
    ]
    outcomes = store.apply(batch)

    assert len(outcomes) == len(batch)
    assert len(journals) == (len(batch) + PAPER_CHUNK - 1) // PAPER_CHUNK
    assert all(journal is not None for journal in journals)
    assert len({id(journal) for journal in journals}) == len(journals)
    assert store.status()["sequence"] == len(batch)
    assert store.check()
    store.close()


@pytest.mark.parametrize("mode", MODES)
def test_journal_capacity_automatically_replays_with_smaller_private_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    path = tmp_path / f"journal-capacity-{mode}.db"
    store = Durable(path, n=64, width=0, mode=mode, max_batch=32)
    original = Matcher.batch
    attempted = []
    large_chunks = 0

    @contextmanager
    def constrain_batch(
        matcher: Matcher,
        max_operations: int = 256,
        before_publish=None,
    ):
        nonlocal large_chunks
        attempted.append(max_operations)
        if max_operations > 2:
            large_chunks += 1
            if large_chunks == 2:
                raise MemoryError("class journal capacity exceeded")
        with original(matcher, max_operations, before_publish):
            yield matcher

    monkeypatch.setattr(Matcher, "batch", constrain_batch)
    batch = [
        Request(sequence, "insert", 2 * sequence, 2 * sequence + 1)
        for sequence in range(1, 25)
    ]
    outcomes = store.apply(batch)

    assert attempted[:3] == [PAPER_CHUNK, PAPER_CHUNK, PAPER_CHUNK // 2]
    assert outcomes == tuple(
        Outcome(sequence, True, sequence) for sequence in range(1, 25)
    )
    assert store.status()["sequence"] == len(batch)
    assert store.check()
    store.close()
    monkeypatch.undo()
    with Durable(path, mode=mode) as recovered:
        assert recovered.status()["sequence"] == len(batch)
        assert recovered.check()


@pytest.mark.parametrize("mode", MODES)
def test_single_update_journal_exhaustion_is_atomic_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    path = tmp_path / f"single-journal-capacity-{mode}.db"
    store = Durable(path, n=16, width=0, mode=mode)
    before = witness(store)
    original = Matcher.batch

    @contextmanager
    def exhausted_batch(
        matcher: Matcher,
        max_operations: int = 256,
        before_publish=None,
    ):
        raise MemoryError("class journal capacity exceeded")
        yield matcher

    monkeypatch.setattr(Matcher, "batch", exhausted_batch)
    request = [Request(1, "insert", 0, 1)]
    with pytest.raises(MemoryError, match="journal capacity exceeded"):
        store.apply(request)
    assert witness(store) == before
    assert store.status()["sequence"] == 0
    assert store.check()

    monkeypatch.setattr(Matcher, "batch", original)
    assert store.apply(request) == (Outcome(1, True, 1),)
    assert store.check()
    store.close()


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("failure", ["before_commit", "after_commit", "after_publish"])
def test_sqlite_commit_and_graph_publication_fail_stop_then_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    failure: str,
) -> None:
    path = tmp_path / f"{mode}-{failure}.db"
    store = Durable(path, n=16, width=0, mode=mode)
    request = [Request(1, "insert", 0, 1), Request(2, "insert", 2, 3)]
    persist = store._persist

    if failure == "before_commit":

        def fail_before(rows: list) -> None:
            database = store._db()
            database.execute("BEGIN IMMEDIATE")
            database.executemany(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?)", rows[:1]
            )
            raise OSError("injected SQLite pre-commit failure")

        monkeypatch.setattr(store, "_persist", fail_before)
    elif failure == "after_commit":

        def fail_after(rows: list) -> None:
            persist(rows)
            raise OSError("injected lost commit acknowledgment")

        monkeypatch.setattr(store, "_persist", fail_after)
    else:
        publish = core.publish
        publications = 0

        def fail_publication(journals: list) -> None:
            nonlocal publications
            publications += 1
            publish(journals)
            if publications == 1:
                raise OSError("injected post-SQLite publication failure")

        monkeypatch.setattr(core, "publish", fail_publication)

    with pytest.raises((OSError, RuntimeError)):
        store.apply(request)
    for operation in (store.status, store.check, lambda: store.partner(0)):
        with pytest.raises(UnavailableError):
            operation()
    store.close()
    monkeypatch.undo()

    committed = failure in ("after_commit", "after_publish")
    with Durable(path, mode=mode) as recovered:
        if committed:
            assert recovered.status()["sequence"] == 2
            assert recovered.has_edge(0, 1)[1]
            assert recovered.has_edge(2, 3)[1]
            assert recovered.apply(request) == (
                Outcome(1, True, 1),
                Outcome(2, True, 2),
            )
        else:
            assert recovered.status()["sequence"] == 0
            assert not recovered.has_edge(0, 1)[1]
            assert not recovered.has_edge(2, 3)[1]
            assert recovered.apply(request) == (
                Outcome(1, True, 1),
                Outcome(2, True, 2),
            )
        assert recovered.check()


@pytest.mark.parametrize("mode", MODES)
def test_mode_identity_is_persisted_and_mismatch_is_rejected(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / "mode.db"
    other = "multilevel" if mode == "basic" else "basic"
    with Durable(path, n=12, width=0, mode=mode) as store:
        store.apply([Request(1, "insert", 0, 1)])
    with pytest.raises(RecoveryError, match="mode"):
        Durable(path, mode=other)
    with Durable(path, mode=mode) as recovered:
        with closing(sqlite3.connect(path)) as database:
            config = json.loads(
                database.execute("SELECT metadata FROM control").fetchone()[0]
            )
        assert config["mode"] == mode
        assert recovered.status()["mode"] == mode
        assert recovered.check()


def test_old_native_format_is_rejected_without_compatibility_reader(
    tmp_path: Path,
) -> None:
    path = tmp_path / "old.db"
    with closing(sqlite3.connect(path)) as database:
        database.execute(
            "CREATE TABLE control (id INTEGER PRIMARY KEY, metadata TEXT, "
            "sequence INTEGER, version INTEGER, digest BLOB)"
        )
        database.execute(
            "CREATE TABLE operations (sequence INTEGER PRIMARY KEY, "
            "adding INTEGER, u INTEGER, v INTEGER, changed INTEGER, "
            "version INTEGER, digest BLOB)"
        )
        database.execute(
            "CREATE TABLE checkpoints (sequence INTEGER PRIMARY KEY, image BLOB)"
        )
    with pytest.raises(RecoveryError, match="unsupported database format"):
        Durable(path, n=8, mode="basic")


@pytest.mark.parametrize("mode", MODES)
def test_retry_hash_chain_noops_and_duplicate_sequences(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"{mode}.db"
    batch = [
        Request(1, "insert", 0, 1),
        Request(2, "insert", 1, 0),
        Request(3, "delete", 7, 8),
    ]
    with Durable(path, n=16, width=0, mode=mode) as store:
        expected = store.apply(batch)
        assert expected == (
            Outcome(1, True, 1),
            Outcome(2, False, 1),
            Outcome(3, False, 1),
        )
        assert store.apply(batch) == expected
        assert store.apply([batch[0], batch[0]]) == (expected[0], expected[0])
        records = store.history(limit=2)
        following = store.history(start=3, limit=2)
        assert tuple(record.sequence for record in records.records) == (1, 2)
        assert records.has_more
        assert records.records[-1].digest == following.previous_digest
        assert following.records[0].digest == store._tail
        metadata = store._db().execute("SELECT metadata FROM control").fetchone()[0]
        previous = hashlib.sha256(metadata.encode()).digest()
        for record in (*records.records, *following.records):
            previous = _digest(
                previous,
                record.sequence,
                int(record.operation == "insert"),
                record.u,
                record.v,
                record.changed,
                record.version,
            )
            assert previous == record.digest
        with pytest.raises(ValueError, match="differs"):
            store.apply([Request(1, "delete", 0, 1)])
        assert store.check()


@pytest.mark.parametrize("mode", MODES)
def test_history_capacity_rejects_before_mutation_and_preserves_retry(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"{mode}.db"
    with Durable(path, n=10, width=0, mode=mode, max_operations=2) as store:
        batch = [Request(1, "insert", 0, 1), Request(2, "delete", 0, 1)]
        outcome = store.apply(batch)
        before = state(store)
        with pytest.raises(CapacityError, match="history"):
            store.apply([Request(3, "insert", 2, 3)])
        assert state(store) == before
        assert store.apply(batch) == outcome
        assert store.check()


@pytest.mark.parametrize("mode", MODES)
def test_invalid_batch_admission_has_no_partial_side_effects(
    tmp_path: Path, mode: str
) -> None:
    with Durable(
        tmp_path / f"{mode}.db", n=10, width=0, mode=mode, max_batch=3
    ) as store:
        before = witness(store)
        invalid = (
            [Request(2, "insert", 0, 1)],
            [Request(1, "unknown", 0, 1)],  # type: ignore[arg-type]
            [Request(1, "insert", 0, 10)],
            [Request(1, "insert", True, 2)],  # type: ignore[arg-type]
            [Request(1, "insert", 0, 1), Request(1, "delete", 0, 1)],
            [Request(index, "insert", 0, 1) for index in range(1, 5)],
        )
        for batch in invalid:
            with pytest.raises((ValueError, CapacityError)):
                store.apply(batch)
            assert witness(store) == before
            assert store.status()["sequence"] == 0
        assert store.apply([Request(1, "insert", 0, 1)])[0].changed
        assert store.check()


@pytest.mark.parametrize("mode", MODES)
def test_history_checksum_corruption_fails_closed_on_reopen(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"{mode}.db"
    with Durable(path, n=8, mode=mode) as store:
        store.apply([Request(1, "insert", 0, 1)])
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("UPDATE operations SET digest=zeroblob(32)")
    with pytest.raises(RecoveryError, match="operation history"):
        Durable(path, mode=mode)


@pytest.mark.parametrize("mode", MODES)
def test_graph_and_matching_replay_is_deterministic_across_many_batches(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"{mode}.db"
    stream = [
        Request(
            sequence,
            "insert" if sequence % 3 else "delete",
            sequence % 18,
            (sequence * 7) % 18,
        )
        for sequence in range(1, 91)
    ]
    with Durable(path, n=18, width=0, mode=mode, max_batch=15) as store:
        for start in range(0, len(stream), 15):
            store.apply(stream[start : start + 15])
            assert store.check()
        expected_state = state(store)
        expected_witness = witness(store)
    with Durable(path, mode=mode) as recovered:
        assert state(recovered) == expected_state
        assert witness(recovered) == expected_witness
        assert recovered.check()
