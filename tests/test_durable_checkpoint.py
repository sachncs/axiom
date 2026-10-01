"""Atomic durable checkpoints, bounded replay, retirement and crash recovery."""

import hashlib
import random
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from pathlib import Path

import pytest
from test_durable import snapshot
from test_engine import Reference

from axiom.durable import (
    BusyError,
    CapacityError,
    Durable,
    ExpiredError,
    Outcome,
    RecoveryError,
    Request,
    UnavailableError,
    _checkpoint_digest,
)


def create(path: Path, **options: int) -> Durable:
    return Durable(
        path,
        n=33,
        width=0,
        max_batch=4,
        max_operations=24,
        checkpoint_interval=8,
        retain_operations=4,
        **options,
    )


def edits(first: int, count: int) -> list[Request]:
    return [
        Request(seq, "insert" if seq % 2 else "delete", 0, 1)
        for seq in range(first, first + count)
    ]


def test_auto_checkpoints_run_past_history_limit_and_preserve_retained_retries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    results = {}
    with create(path) as store:
        for first in range(1, 101, 4):
            batch = edits(first, 4)
            result = store.apply(batch)
            results.update((outcome.sequence, outcome) for outcome in result)
            assert all(o.changed and o.version == o.sequence for o in result)
            assert store.status()["retained_operations"] <= 12
            assert store.check()
        state = snapshot(store)
        status = store.status()
        assert status["sequence"] == 100 and status["checkpoint_generation"] == 12
        assert status["checkpoint_sequence"] == 96 and status["retired_floor"] == 92
        assert store.apply(edits(93, 4)) == tuple(results[seq] for seq in range(93, 97))
        with pytest.raises(ExpiredError):
            store.apply([Request(92, "delete", 0, 1)])
        assert snapshot(store) == state
    with Durable(path) as recovered:
        assert snapshot(recovered) == state and recovered.check()
        assert recovered.status()["max_batch"] == 4
        assert recovered.status()["checkpoint_generation"] == 12
        assert recovered.apply(edits(97, 4)) == tuple(
            results[seq] for seq in range(97, 101)
        )
        with pytest.raises(ExpiredError):
            recovered.apply([Request(1, "insert", 0, 1)])
        assert recovered.apply(edits(101, 4)) == tuple(
            Outcome(seq, True, seq) for seq in range(101, 105)
        )


def test_manual_checkpoint_is_not_a_new_graph_version_and_keeps_exact_matching(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    with create(path) as store:
        store.apply(
            [
                Request(1, "insert", 0, 1),
                Request(2, "insert", 1, 2),
                Request(3, "insert", 2, 3),
                Request(4, "delete", 0, 1),
            ]
        )
        store.apply([Request(5, "insert", 3, 4), Request(6, "insert", 0, 4)])
        before = snapshot(store)
        result = store.checkpoint()
        assert result == {
            "checkpoint_sequence": 6,
            "retired_floor": 2,
            "retained_operations": 4,
            "generation": 1,
        }
        assert snapshot(store) == before
        assert store.checkpoint()["generation"] == 2
        assert snapshot(store) == before
    with Durable(path) as recovered:
        assert snapshot(recovered) == before


def test_v2_policy_is_persisted_and_never_silently_applied_to_legacy_store(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy.db"
    with Durable(legacy, n=33, width=0) as store:
        with pytest.raises(ValueError, match="v2"):
            store.checkpoint()
        assert store.check()
    with pytest.raises(RecoveryError):
        Durable(legacy, checkpoint_interval=8)
    with pytest.raises(RecoveryError):
        Durable(legacy, retain_operations=4)
    path = tmp_path / "v2.db"
    with create(path):
        pass
    with pytest.raises(RecoveryError, match="metadata"):
        Durable(path, retain_operations=5)
    with Durable(path) as recovered:
        assert recovered.status()["retain_operations"] == 4


@pytest.mark.parametrize(
    "options",
    [
        {"checkpoint_interval": 0},
        {"checkpoint_interval": True},
        {"checkpoint_interval": 8, "retain_operations": 1},
        {
            "checkpoint_interval": 8,
            "retain_operations": 8,
            "max_operations": 16,
            "max_batch": 4,
        },
    ],
)
def test_invalid_policy_cannot_initialize_a_serving_store(
    tmp_path: Path, options: dict
) -> None:
    with pytest.raises(ValueError):
        Durable(tmp_path / "bad.db", n=33, **options)


def test_snapshot_capacity_admission_rejects_growth_but_allows_exact_noops(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capacity.db"
    # One-edge image capacity: 40 + 8*n + 8*m.
    with create(path, max_snapshot_bytes=40 + 8 * 33 + 8) as store:
        result = store.apply([Request(1, "insert", 0, 1)])
        before = snapshot(store)
        with pytest.raises(CapacityError, match="image capacity"):
            store.apply([Request(2, "insert", 1, 2)])
        assert snapshot(store) == before
        assert store.apply([Request(2, "insert", 0, 1)])[0].changed is False
        assert store.checkpoint()["checkpoint_sequence"] == 2
        assert store.apply([Request(1, "insert", 0, 1)]) == result


@pytest.mark.parametrize(
    "stage", ["before_write", "after_partial_write", "after_commit", "after_install"]
)
def test_checkpoint_failure_retirement_is_atomic_and_uncertain_owner_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    path = tmp_path / "graph.db"
    store = create(path)
    for first in (1, 5):
        store.apply(edits(first, 4))
    state = snapshot(store)
    persist, install = store._persist_checkpoint, store._install_checkpoint

    def fail_persist(record: object) -> None:
        if stage == "after_partial_write":
            store._db().execute("BEGIN IMMEDIATE")
            store._db().execute("DELETE FROM operations WHERE sequence<=4")
            store._db().execute("UPDATE control SET generation=1")
        elif stage == "after_commit":
            persist(record)
        raise OSError("injected checkpoint write/barrier failure")

    def fail_install(record: object) -> None:
        install(record)
        raise OSError("injected checkpoint publication failure")

    if stage == "after_install":
        monkeypatch.setattr(store, "_install_checkpoint", fail_install)
    else:
        monkeypatch.setattr(store, "_persist_checkpoint", fail_persist)
    with pytest.raises(OSError):
        store.checkpoint()
    with pytest.raises(UnavailableError):
        store.status()
    store.close()
    with Durable(path) as recovered:
        assert snapshot(recovered) == state and recovered.check()
        committed = stage in ("after_commit", "after_install")
        assert recovered.status()["retired_floor"] == (4 if committed else 0)
        assert recovered.apply(edits(5, 4)) == tuple(
            Outcome(seq, True, seq) for seq in range(5, 9)
        )
        if committed:
            with pytest.raises(ExpiredError):
                recovered.apply(edits(1, 4))
        else:
            assert recovered.apply(edits(1, 4)) == tuple(
                Outcome(seq, True, seq) for seq in range(1, 5)
            )


@pytest.mark.parametrize("stage", ["before_commit", "after_commit", "after_install"])
def test_process_death_cannot_separate_checkpoint_from_history_retirement(
    tmp_path: Path, stage: str
) -> None:
    path = tmp_path / "graph.db"
    script = """
import os,sys
from axiom.durable import Durable,Request
d=Durable(sys.argv[1],n=33,width=0,max_batch=4,max_operations=24,
          checkpoint_interval=8,retain_operations=4)
for start in (1,5):
    batch=[Request(i,'insert' if i%2 else 'delete',0,1)
           for i in range(start,start+4)]
    d.apply(batch)
persist,install=d._persist_checkpoint,d._install_checkpoint
def crash_persist(record):
    if sys.argv[2]=='before_commit':
        connection=d._db()
        class CrashBeforeCommit:
            def execute(self,sql,*args):
                if sql=='COMMIT': os._exit(79)
                return connection.execute(sql,*args)
            def __getattr__(self,name): return getattr(connection,name)
        d._connection=CrashBeforeCommit()
        persist(record)
    else:
        persist(record)
    os._exit(79)
def crash_install(record):
    install(record); os._exit(79)
if sys.argv[2]=='after_install': d._install_checkpoint=crash_install
else: d._persist_checkpoint=crash_persist
d.checkpoint()
"""
    child = subprocess.run([sys.executable, "-c", script, str(path), stage], timeout=15)
    assert child.returncode == 79
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == recovered.status()["version"] == 8
        assert recovered.status()["edges"] == recovered.status()["matching"] == 0
        assert recovered.status()["retired_floor"] == (
            0 if stage == "before_commit" else 4
        )
        assert recovered.check()
        assert recovered.apply(edits(5, 4)) == tuple(
            Outcome(seq, True, seq) for seq in range(5, 9)
        )


@pytest.mark.parametrize(
    "corruption",
    [
        "image",
        "certificate",
        "missing_checkpoint",
        "floor",
        "anchor",
        "cache",
        "missing_tail",
    ],
)
def test_corrupt_checkpoint_cache_or_suffix_refuses_recovery(
    tmp_path: Path, corruption: str
) -> None:
    path = tmp_path / "graph.db"
    with create(path) as store:
        for first in (1, 5):
            store.apply(edits(first, 4))
        store.checkpoint()
        store.apply(edits(9, 4))
    with closing(sqlite3.connect(path)) as db, db:
        if corruption == "image":
            data = bytearray(db.execute("SELECT image FROM checkpoints").fetchone()[0])
            data[24] ^= 1  # a structurally valid changed version still must fail SHA
            db.execute("UPDATE checkpoints SET image=?", (bytes(data),))
        elif corruption == "missing_checkpoint":
            db.execute("DELETE FROM checkpoints")
        elif corruption == "floor":
            db.execute("UPDATE checkpoints SET floor=3")
        elif corruption == "cache":
            db.execute("UPDATE operations SET changed=0 WHERE sequence=5")
        elif corruption == "missing_tail":
            db.execute("DELETE FROM operations WHERE sequence=12")
        else:
            column = "digest" if corruption == "certificate" else "anchor"
            db.execute(f"UPDATE checkpoints SET {column}=zeroblob(32)")
    with pytest.raises((RecoveryError, ValueError)):
        Durable(path)


def test_checksum_valid_invalid_native_partner_is_not_silently_repaired(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    with create(path) as store:
        store.apply(edits(1, 4))
        store.checkpoint()  # Empty graph: every partner must be free.
    with closing(sqlite3.connect(path)) as db, db:
        row = db.execute(
            "SELECT sequence,version,floor,floor_version,generation,anchor,tail,image "
            "FROM checkpoints"
        ).fetchone()
        metadata = db.execute("SELECT metadata FROM control").fetchone()[0]
        image = bytearray(row[-1])
        image[44:48] = (0).to_bytes(4, "little")  # illegal self partner of vertex 0
        image_digest = hashlib.sha256(image).digest()
        digest = _checkpoint_digest(metadata, *row[:-1], image_digest)
        db.execute(
            "UPDATE checkpoints SET image=?,image_digest=?,digest=?",
            (bytes(image), image_digest, digest),
        )
    with pytest.raises(RecoveryError, match="checkpoint"):
        Durable(path)


def test_uncertified_live_history_cannot_be_hidden_by_retirement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    store = create(path)
    store.apply(edits(1, 4))
    store.apply(edits(5, 4))
    store._db().execute("UPDATE operations SET digest=zeroblob(32) WHERE sequence=1")
    with pytest.raises(RecoveryError, match="history"):
        store.checkpoint()
    with pytest.raises(UnavailableError):
        store.partner(0)
    store.close()
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 8
    with pytest.raises(RecoveryError):
        Durable(path)


def test_checkpoint_gate_rejects_queries_without_private_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "graph.db") as store:
        store.apply(edits(1, 4))
        entered, release = threading.Event(), threading.Event()
        original = store._persist_checkpoint
        failures = []

        def paused(record: object) -> None:
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test checkpoint release timed out")
            original(record)

        def run() -> None:
            try:
                store.checkpoint()
            except BaseException as error:
                failures.append(error)

        monkeypatch.setattr(store, "_persist_checkpoint", paused)
        worker = threading.Thread(target=run)
        worker.start()
        try:
            assert entered.wait(timeout=5)
            with pytest.raises(BusyError):
                store.partner(0)
            with pytest.raises(BusyError):
                store.apply(edits(5, 4))
        finally:
            release.set()
            worker.join(timeout=5)
        assert not worker.is_alive() and failures == []
        assert store.status()["checkpoint_generation"] == 1 and store.check()


def test_random_reference_decisions_and_retries_survive_repeated_checkpoints(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.db"
    reference = Reference(33)
    rng = random.Random(703)
    outcomes, requests = {}, {}
    with create(path) as store:
        for first in range(1, 501, 4):
            batch = []
            for seq in range(first, first + 4):
                adding, u, v = (
                    bool(rng.randrange(2)),
                    rng.randrange(33),
                    rng.randrange(33),
                )
                request = Request(seq, "insert" if adding else "delete", u, v)
                changed = reference.edit(u, v, adding)
                requests[seq], outcomes[seq] = (
                    request,
                    Outcome(seq, changed, reference.version),
                )
                batch.append(request)
            assert store.apply(batch) == tuple(outcomes[r.sequence] for r in batch)
            if first % 20 == 1:
                store.checkpoint()
            assert store.check()
        before = snapshot(store)
    with Durable(path) as recovered:
        assert snapshot(recovered) == before
        for u in range(33):
            assert recovered.partner(u)[1] == reference.partners.get(u)
            for v in range(u + 1, 33):
                assert recovered.has_edge(u, v)[1] == reference.graph.has_edge(u, v)
        for seq in range(497, 501):
            assert recovered.apply([requests[seq]]) == (outcomes[seq],)


def test_checkpoint_allocation_failure_before_persistence_keeps_owner_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with create(tmp_path / "graph.db") as store:
        store.apply(edits(1, 4))
        before = snapshot(store)

        def fail_record() -> object:
            raise MemoryError("injected checkpoint reservation failure")

        original = store._checkpoint_record
        monkeypatch.setattr(store, "_checkpoint_record", fail_record)
        with pytest.raises(MemoryError):
            store.checkpoint()
        assert snapshot(store) == before and store.check()
        monkeypatch.setattr(store, "_checkpoint_record", original)
        assert store.checkpoint()["generation"] == 1


def test_actual_sqlite_full_checkpoint_failure_keeps_last_acknowledged_prefix(
    tmp_path: Path,
) -> None:
    path = tmp_path / "full.db"
    store = Durable(
        path,
        n=50000,
        max_database_bytes=1 << 20,
        max_snapshot_bytes=2 << 20,
        max_batch=4,
        max_operations=24,
        checkpoint_interval=8,
        retain_operations=4,
    )
    result = store.apply([Request(1, "delete", 0, 1)])
    status = store.status()
    with pytest.raises(sqlite3.DatabaseError, match="full"):
        store.checkpoint()
    with pytest.raises(UnavailableError):
        store.status()
    store.close()
    with Durable(path, max_database_bytes=1 << 20) as recovered:
        assert recovered.status()["sequence"] == status["sequence"] == 1
        assert recovered.status()["version"] == status["version"]
        assert recovered.status()["checkpoint_generation"] == 0
        assert recovered.check() and recovered.has_edge(0, 1)[1] is False
        assert recovered.apply([Request(1, "delete", 0, 1)]) == result


def test_checkpoint_publication_precondition_failure_undoes_inserted_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "graph.db"
    store = create(path)
    store.apply(edits(1, 4))
    connection = store._db()

    class NoPublication:
        def execute(self, sql: str, *args: object) -> object:
            if sql.startswith("UPDATE control SET generation="):

                class Rejected:
                    rowcount = 0

                return Rejected()
            return connection.execute(sql, *args)

        def __getattr__(self, name: str) -> object:
            return getattr(connection, name)

    monkeypatch.setattr(store, "_connection", NoPublication())
    with pytest.raises(RecoveryError, match="precondition"):
        store.checkpoint()
    with pytest.raises(UnavailableError):
        store.partner(0)
    store.close()
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == 4
        assert recovered.status()["checkpoint_generation"] == 0
        assert recovered.apply(edits(1, 4)) == tuple(
            Outcome(seq, True, seq) for seq in range(1, 5)
        )
