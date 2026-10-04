"""Self-contained SQLite backup and exact paper-mode restore coverage."""

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from axiom import backup
from axiom.backup import BackupError
from axiom.durable import Durable, Outcome, Request
from axiom.witness import Witness

MODES = ("basic", "multilevel")


def edits() -> list[Request]:
    return [
        Request(1, "insert", 0, 1),
        Request(2, "insert", 2, 3),
        Request(3, "delete", 1, 0),
        Request(4, "insert", 0, 2),
        Request(5, "delete", 3, 2),
        Request(6, "insert", 4, 5),
    ]


def graphstate(store: Durable) -> tuple:
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
    return Witness().capture(store._matcher)


@pytest.mark.parametrize("mode", MODES)
def test_backup_restores_exact_mode_witness_and_retries_from_wal(
    tmp_path: Path, mode: str
) -> None:
    source_path = tmp_path / f"source-{mode}.db"
    backup_path = tmp_path / f"backup-{mode}.db"
    with Durable(source_path, n=20, width=0, mode=mode) as source:
        source._db().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        source._db().execute("PRAGMA wal_autocheckpoint=0")
        expected_outcomes = source.apply(edits())
        expected_state = graphstate(source)
        expected_witness = witness(source)
        receipt = source.backup(backup_path)
        assert graphstate(source) == expected_state
        assert witness(source) == expected_witness
        assert source.check()

        assert receipt["sequence"] == expected_state[1] == 6
        assert receipt["version"] == expected_state[2]
        assert receipt["path"] == str(backup_path)
        assert receipt["bytes"] == backup_path.stat().st_size
        assert receipt["sha256"] == hashlib.sha256(backup_path.read_bytes()).hexdigest()
        assert backup_path.stat().st_mode & 0o777 == 0o600
        assert not Path(f"{backup_path}-wal").exists()
        assert not Path(f"{backup_path}-shm").exists()

        later = Request(7, "insert", 6, 7)
        assert source.apply([later]) == (Outcome(7, True, expected_state[2] + 1),)

    with Durable(backup_path, mode=mode) as restored:
        assert graphstate(restored) == expected_state
        assert witness(restored) == expected_witness
        assert restored.apply(edits()) == expected_outcomes
        assert restored.apply([later]) == (Outcome(7, True, expected_state[2] + 1),)
        assert restored.check()


@pytest.mark.parametrize("suffix", ["", ".owner", "-wal", "-shm", "-journal"])
def test_backup_refuses_source_and_reserved_sidecar_paths(
    tmp_path: Path, suffix: str
) -> None:
    source_path = tmp_path / "source.db"
    with Durable(source_path, n=8, width=0) as source:
        before = graphstate(source)
        with pytest.raises(ValueError, match="distinct"):
            source.backup(Path(f"{source_path}{suffix}"))
        assert graphstate(source) == before
        assert source.check()


@pytest.mark.parametrize("existing", ["file", "symlink", "sidecar", "owned"])
def test_backup_never_overwrites_or_uses_an_owned_destination(
    tmp_path: Path, existing: str
) -> None:
    destination = tmp_path / "backup.db"
    with Durable(tmp_path / "source.db", n=8, width=0) as source:
        owner = None
        if existing == "owned":
            owner = Durable(destination, n=8, width=0)
        elif existing == "symlink":
            destination.symlink_to(source._path)
        else:
            target = destination if existing == "file" else Path(f"{destination}-wal")
            target.touch()
        try:
            with pytest.raises((BackupError, ValueError)):
                source.backup(destination)
            assert source.check()
            if existing == "file":
                assert destination.read_bytes() == b""
            if owner is not None:
                assert owner.status()["sequence"] == 0
                assert owner.check()
        finally:
            if owner is not None:
                owner.close()


@pytest.mark.parametrize(
    "stage", ["copy", "sync", "before_publish", "after_link", "after_publish"]
)
def test_backup_failure_preserves_source_and_only_publishes_complete_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    destination = tmp_path / "backup.db"
    helper = {"copy": "_copy_pages", "sync": "_sync_file"}.get(stage, "_publish")
    original = getattr(backup, helper)

    def fail(*args: object, **kwargs: object) -> None:
        if stage == "after_link":
            os.link(*args, **kwargs)
        elif stage == "after_publish":
            original(*args, **kwargs)
        raise OSError("injected backup failure")

    with Durable(tmp_path / "source.db", n=16, width=0, mode="multilevel") as source:
        source.apply(edits())
        before = graphstate(source)
        before_witness = witness(source)
        monkeypatch.setattr(backup, helper, fail)
        with pytest.raises(BackupError):
            source.backup(destination)
        assert graphstate(source) == before
        assert witness(source) == before_witness
        assert source.check()
        assert not list(tmp_path.glob(".axiom-backup-*"))
        assert destination.exists() == (stage in ("after_link", "after_publish"))
        if destination.exists():
            with Durable(destination, mode="multilevel") as restored:
                assert graphstate(restored) == before
                assert witness(restored) == before_witness
                assert restored.check()
        monkeypatch.undo()
        assert source.apply([Request(7, "insert", 6, 7)])[0].sequence == 7


@pytest.mark.parametrize(
    "options",
    [
        {"max_bytes": 0},
        {"max_bytes": True},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"timeout": True},
    ],
)
def test_invalid_backup_bounds_create_no_image_or_owner_file(
    tmp_path: Path, options: dict
) -> None:
    destination = tmp_path / "backup.db"
    with (
        Durable(tmp_path / "source.db", n=8, width=0) as source,
        pytest.raises(ValueError),
    ):
        source.backup(destination, **options)
    assert not destination.exists()
    assert not Path(f"{destination}.owner").exists()


def test_backup_size_limit_and_private_compaction_leave_source_unchanged(
    tmp_path: Path,
) -> None:
    source_path, destination = tmp_path / "source.db", tmp_path / "backup.db"
    with Durable(source_path, n=16, width=0) as source:
        source.apply(edits())
        database = source._db()
        database.execute("CREATE TABLE scratch (payload BLOB)")
        database.execute("INSERT INTO scratch VALUES (zeroblob(2097152))")
        database.execute("DROP TABLE scratch")
        database.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        page_count = database.execute("PRAGMA page_count").fetchone()[0]
        free_count = database.execute("PRAGMA freelist_count").fetchone()[0]
        assert free_count > 400
        before = graphstate(source)
        before_witness = witness(source)
        source_bytes = source_path.read_bytes()

        with pytest.raises(BackupError, match="max_bytes"):
            source.backup(tmp_path / "too-small.db", max_bytes=1 << 20)
        assert not (tmp_path / "too-small.db").exists()

        receipt = source.backup(destination)
        assert source_path.read_bytes() == source_bytes
        assert database.execute("PRAGMA page_count").fetchone() == (page_count,)
        assert database.execute("PRAGMA freelist_count").fetchone() == (free_count,)
        assert graphstate(source) == before
        assert witness(source) == before_witness
        assert source.check()

        with sqlite3.connect(destination) as copied:
            assert copied.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert copied.execute("PRAGMA freelist_count").fetchone() == (0,)
            assert copied.execute("PRAGMA page_count").fetchone()[0] < page_count - 400
            assert copied.execute("SELECT count(*) FROM operations").fetchone() == (6,)
        assert receipt["bytes"] == destination.stat().st_size
        assert receipt["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()

    with Durable(destination, mode="basic") as restored:
        assert graphstate(restored) == before
        assert witness(restored) == before_witness
        assert restored.check()


@pytest.mark.parametrize(
    "status,total,deadline", [(5, 10, 10), (6, 10, 10), (0, 1000000, 10), (0, 10, 0)]
)
def test_copy_progress_rejects_contention_size_growth_and_expired_deadline(
    monkeypatch: pytest.MonkeyPatch, status: int, total: int, deadline: float
) -> None:
    class Source:
        def backup(self, target, *, pages, progress, sleep):
            assert pages == 256 and sleep == 0
            progress(status, total - 1, total)

    monkeypatch.setattr(backup.time, "monotonic", lambda: 1)
    with pytest.raises(BackupError):
        backup._copy_pages(Source(), None, 4096, 1 << 20, deadline)
