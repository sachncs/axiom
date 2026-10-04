"""Durable external identifier mapping and graph-query contracts."""

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from axiom.durable import (
    CapacityError,
    Durable,
    ExternalRequest,
    RecoveryError,
    Request,
    _digest,
)
from axiom.witness import Witness


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_external_identifiers_round_trip_and_address_durable_graph(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"external-{mode}.db"
    worker = "7"
    job = UUID("00112233-4455-6677-8899-aabbccddeeff")
    integer = 7
    with Durable(path, n=8, width=0, mode=mode) as store:
        worker_slot = store.register_identifier(worker)
        job_slot = store.register_identifier(job)
        integer_slot = store.register_identifier(integer)
        assert (worker_slot, job_slot, integer_slot) == (0, 1, 2)
        assert store.register_identifier(worker) == worker_slot
        assert store.resolve_identifier(worker) == worker_slot
        assert store.resolve_identifier(job) == job_slot
        assert store.resolve_identifier(integer) == integer_slot
        assert store.external_identifier(worker_slot) == worker
        assert store.external_identifier(job_slot) == job
        assert store.external_identifier(integer_slot) == integer
        assert store.external_identifier(7) is None

        outcomes = store.apply_external([ExternalRequest(1, "insert", worker, job)])
        assert outcomes[0].changed
        assert store.partner_external(worker) == (1, job)
        assert store.has_edge_external(worker, job) == (1, True)
        snapshot = store.read_snapshot_external(
            [worker, job, integer], [(worker, job)], expected_version=1
        )
        assert snapshot.version == 1
        assert snapshot.partners == (job, worker, None)
        assert snapshot.has_edges == (True,)
        before = Witness().capture(store._matcher)

    with Durable(path, mode=mode) as recovered:
        assert recovered.resolve_identifier(worker) == worker_slot
        assert recovered.resolve_identifier(job) == job_slot
        assert recovered.resolve_identifier(integer) == integer_slot
        assert recovered.partner_external(worker) == (1, job)
        assert Witness().capture(recovered._matcher) == before
        assert recovered.check()


def test_external_unknown_id_and_exhaustion_do_not_consume_graph_sequence(
    tmp_path: Path,
) -> None:
    with Durable(tmp_path / "bounded-identifiers.db", n=2, width=0) as store:
        store.register_identifier("known")
        with pytest.raises(KeyError, match="not registered"):
            store.apply_external([ExternalRequest(1, "insert", "known", "missing")])
        store.register_identifier("other")
        with pytest.raises(CapacityError, match="no free identifier slots"):
            store.register_identifier("overflow")
        assert store.status()["sequence"] == 0
        assert store.register_identifier("known") == 0


def test_identifier_registration_commit_failure_rolls_back_allocation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identifier-atomic.db"
    with Durable(path, n=4, width=0) as store:
        store._db().execute(
            "CREATE TRIGGER reject_identifier BEFORE INSERT ON identifiers "
            "BEGIN SELECT RAISE(ABORT, 'injected mapping failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="mapping failure"):
            store.register_identifier("alice")
        assert store._db().execute(
            "SELECT next_vertex FROM identity_control WHERE id=1"
        ).fetchone() == (0,)
        assert store._db().execute("SELECT count(*) FROM identifiers").fetchone() == (
            0,
        )
        store._db().execute("DROP TRIGGER reject_identifier")
        assert store.register_identifier("alice") == 0


def test_corrupt_identifier_mapping_fails_closed_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "corrupt-identifiers.db"
    with Durable(path, n=4, width=0) as store:
        store.register_identifier("alice")
    with sqlite3.connect(path) as database:
        database.execute("UPDATE identifiers SET vertex=3 WHERE vertex=0")

    with pytest.raises(RecoveryError, match="identifier"):
        Durable(path, mode="basic")


def test_v1_operation_history_rejects_trigger_then_migrates_to_identifier_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "upgrade-v1.db"
    with Durable(path, n=8, width=0, mode="multilevel") as store:
        outcomes = store.apply(
            [
                # Version progression includes a no-op and a successful delete.
                Request(1, "insert", 0, 1),
                Request(2, "insert", 0, 1),
                Request(3, "delete", 0, 1),
            ]
        )
        expected = Witness().capture(store._matcher)
        expected_tail = store._tail
        assert [outcome.version for outcome in outcomes] == [1, 1, 2]

    with sqlite3.connect(path) as database:
        metadata, sequence, version, _ = database.execute(
            "SELECT metadata,sequence,version,digest FROM control WHERE id=1"
        ).fetchone()
        config = json.loads(metadata)
        config["format"] = "axiom-paper-sqlite-replay-v1"
        del config["identifier_codec"]
        legacy_metadata = json.dumps(config, sort_keys=True, separators=(",", ":"))
        tail = hashlib.sha256(legacy_metadata.encode()).digest()
        rows = database.execute(
            "SELECT sequence,adding,u,v,changed,version FROM operations "
            "ORDER BY sequence"
        ).fetchall()
        for row in rows:
            tail = _digest(tail, row[0], row[1], row[2], row[3], bool(row[4]), row[5])
            database.execute(
                "UPDATE operations SET digest=? WHERE sequence=?", (tail, row[0])
            )
        database.execute(
            "UPDATE control SET metadata=?,digest=? WHERE id=1",
            (legacy_metadata, tail),
        )
        database.execute("DROP TABLE identifiers")
        database.execute("DROP TABLE identity_control")
        database.execute(
            "CREATE TRIGGER reject_upgrade BEFORE UPDATE ON control "
            "BEGIN SELECT RAISE(ABORT, 'injected migration failure'); END"
        )

    # Recovery rejects externally added schema behavior before running the
    # migration. The legacy tables, metadata and digest chain remain untouched.
    with pytest.raises(RecoveryError, match="unsupported database schema objects"):
        Durable(path, mode="multilevel")
    with sqlite3.connect(path) as database:
        assert (
            database.execute("SELECT metadata FROM control WHERE id=1").fetchone()[0]
            == legacy_metadata
        )
        assert database.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall() == [("control",), ("operations",)]
        database.execute("DROP TRIGGER reject_upgrade")

    with Durable(path, mode="multilevel") as migrated:
        metadata = json.loads(
            migrated._db()
            .execute("SELECT metadata FROM control WHERE id=1")
            .fetchone()[0]
        )
        assert metadata["format"] == "axiom-paper-sqlite-replay-v2"
        assert metadata["identifier_codec"] == "typed-external-id-v1"
        assert migrated.status()["sequence"] == sequence
        assert migrated.status()["version"] == version
        # V1 addressed slots directly; migration preserves every referenced
        # integer ID before assigning new IDs to the remaining capacity.
        assert migrated.external_identifier(0) == 0
        assert migrated.external_identifier(1) == 1
        assert migrated.register_identifier("new-id") == 2
        assert migrated.resolve_identifier("new-id") == 2
        assert Witness().capture(migrated._matcher) == expected
        assert migrated._tail == expected_tail
        assert migrated.check()
