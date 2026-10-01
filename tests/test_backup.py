"""Self-contained WAL backups, exact restore, admission and failure boundaries."""

import hashlib
import shutil
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from axiom import backup
from axiom.backup import BackupError
from axiom.durable import BusyError, Durable, ExpiredError, Outcome, Request
from axiom.service import Service


def create(path: Path, checkpointed: bool = True) -> Durable:
    return Durable(
        path,
        n=16,
        width=0,
        max_batch=4,
        max_operations=32 if checkpointed else 64,
        checkpoint_interval=8 if checkpointed else None,
        retain_operations=8 if checkpointed else None,
    )


def edit(sequence: int) -> Request:
    return Request(sequence, "insert" if sequence % 2 else "delete", 0, 1)


def state(store: Durable) -> tuple:
    status = store.status()
    return (
        tuple(store.partner(u) for u in range(16)),
        tuple(
            (u, v)
            for u in range(16)
            for v in range(u + 1, 16)
            if store.has_edge(u, v)[1]
        ),
        tuple(
            status[key]
            for key in (
                "sequence",
                "version",
                "retired_floor",
                "checkpoint_sequence",
                "checkpoint_generation",
                "retained_operations",
            )
        ),
    )


@pytest.mark.parametrize("checkpointed", [False, True])
def test_backup_captures_uncheckpointed_wal_and_exact_retry_retirement(
    tmp_path: Path, checkpointed: bool
) -> None:
    path, destination = tmp_path / "source.db", tmp_path / "backup.db"
    with create(path, checkpointed) as source:
        # Establish a main-file baseline, then keep subsequent commits in WAL.
        source._db().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        source._db().execute("PRAGMA wal_autocheckpoint=0")
        for seq in range(1, 38):
            assert source.apply([edit(seq)]) == (Outcome(seq, True, seq),)
        before = state(source)
        stale = tmp_path / "unsafe-main-only.db"
        shutil.copyfile(path, stale)
        connection = sqlite3.connect(stale)
        try:
            assert connection.execute("SELECT sequence FROM control").fetchone() == (0,)
        finally:
            connection.close()
        result = source.backup(destination)
        assert state(source) == before and source.check()
        assert result["sequence"] == result["version"] == 37
        assert result["bytes"] == destination.stat().st_size
        assert result["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
        assert destination.stat().st_mode & 0o777 == 0o600
        assert not Path(str(destination) + "-wal").exists()
        assert not Path(str(destination) + "-shm").exists()
        source.apply([edit(38)])
        with Durable(destination) as restored:
            assert state(restored) == before and restored.check()
            assert restored.apply([edit(37)]) == (Outcome(37, True, 37),)
            if checkpointed:
                with pytest.raises(ExpiredError):
                    restored.apply([edit(1)])
            else:
                assert restored.apply([edit(1)]) == (Outcome(1, True, 1),)
            assert restored.apply([edit(38)]) == (Outcome(38, True, 38),)
        assert state(source) != before


@pytest.mark.parametrize("suffix", ["", ".owner", "-wal", "-shm", "-journal"])
def test_backup_never_publishes_over_source_or_reserved_sidecars(
    tmp_path: Path, suffix: str
) -> None:
    path = tmp_path / "source.db"
    with create(path) as source:
        before = state(source)
        with pytest.raises(ValueError, match="distinct"):
            source.backup(Path(str(path) + suffix))
        assert state(source) == before and source.check()


@pytest.mark.parametrize("existing", ["file", "symlink", "sidecar", "owned"])
def test_backup_refuses_existing_or_owned_destination_without_overwrite(
    tmp_path: Path, existing: str
) -> None:
    target = tmp_path / "backup.db"
    with create(tmp_path / "source.db") as source:
        before = state(source)
        other = None
        if existing == "owned":
            other = create(target)
        elif existing == "symlink":
            target.symlink_to(source._path)
        else:
            protected = target if existing == "file" else Path(str(target) + "-wal")
            protected.touch()
        try:
            with pytest.raises((BackupError, ValueError)):
                source.backup(target)
            assert state(source) == before and source.check()
            if existing == "file":
                assert target.read_bytes() == b""
            if other:
                assert other.status()["sequence"] == 0 and other.check()
        finally:
            if other:
                other.close()


@pytest.mark.parametrize(
    "stage", ["copy", "sync", "before_publish", "after_link", "after_publish"]
)
def test_backup_failure_never_changes_source_or_leaves_partial_published_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    destination = tmp_path / "backup.db"
    target = {"copy": "_copy_pages", "sync": "_sync_file"}.get(stage, "_publish")
    original = getattr(backup, target)

    def failed(*args: object) -> None:
        if stage == "after_link":
            import os

            os.link(*args)
        elif stage in ("copy", "after_publish"):
            original(*args)
        raise OSError("injected backup I/O failure")

    with create(tmp_path / "source.db") as source:
        source.apply([edit(1)])
        before = state(source)
        monkeypatch.setattr(backup, target, failed)
        with pytest.raises(BackupError):
            source.backup(destination)
        assert state(source) == before and source.check()
        assert not list(tmp_path.glob(".axiom-backup-*"))
        assert destination.exists() == (stage in ("after_link", "after_publish"))
        if destination.exists():
            with Durable(destination) as restored:
                assert state(restored) == before and restored.check()
        assert source.apply([edit(2)]) == (Outcome(2, True, 2),)


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
def test_invalid_backup_policy_does_not_create_destination(
    tmp_path: Path, options: dict
) -> None:
    destination = tmp_path / "backup.db"
    with create(tmp_path / "source.db") as source, pytest.raises(ValueError):
        source.backup(destination, **options)
    assert not destination.exists() and not Path(str(destination) + ".owner").exists()


def test_backup_size_limit_rejects_before_copy_and_source_remains_usable(
    tmp_path: Path,
):
    destination = tmp_path / "backup.db"
    with Durable(
        tmp_path / "source.db",
        n=150000,
        width=0,
        max_batch=1,
        checkpoint_interval=8,
        retain_operations=8,
    ) as source:
        source.checkpoint()
        assert (
            source._db().execute("PRAGMA page_count").fetchone()[0]
            * source._db().execute("PRAGMA page_size").fetchone()[0]
            > 1 << 20
        )
        with pytest.raises(BackupError, match="max_bytes"):
            source.backup(destination, max_bytes=1 << 20)
        assert not destination.exists()
        assert source.check() and source.apply([edit(1)]) == (Outcome(1, True, 1),)


def test_service_backup_blocks_mutations_but_not_partner_reads_and_failure_is_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    original = backup._copy_pages

    def paused(*args: object) -> None:
        entered.set()
        if not release.wait(5):
            raise RuntimeError("backup test release timed out")
        original(*args)

    destination = tmp_path / "backup.db"
    with Service(
        tmp_path / "source.db",
        n=16,
        width=0,
        queue_capacity=8,
        max_batch=4,
        checkpoint_interval=8,
        retain_operations=8,
        max_operations=32,
        batch_wait_ms=0,
    ) as service:
        assert service.submit(edit(1)).result(5) == Outcome(1, True, 1)
        monkeypatch.setattr(backup, "_copy_pages", paused)
        receipt = service.backup(destination)
        try:
            assert entered.wait(5)
            update = service.submit(edit(2))
            assert service.partner(0).result(0) == (1, 1)
            assert not receipt.done() and not update.done()
            with pytest.raises(BusyError):
                service._owner.partner(0)
            with pytest.raises(BusyError):
                Durable(destination)
        finally:
            release.set()
        assert receipt.result(5)["sequence"] == 1
        assert update.result(5) == Outcome(2, True, 2)
        with pytest.raises(BackupError):
            service.backup(destination).result(5)
        assert service.metrics()["state"] == "open"
        assert service.submit(edit(3)).result(5) == Outcome(3, True, 3)
        with Durable(destination) as restored:
            assert restored.partner(0) == (1, 1) and restored.check()


@pytest.mark.parametrize(
    "status,total,deadline", [(5, 10, 10), (6, 10, 10), (0, 1000000, 10), (0, 10, 0)]
)
def test_copy_progress_rejects_contention_size_growth_and_deadline(
    monkeypatch: pytest.MonkeyPatch, status: int, total: int, deadline: float
) -> None:
    class Source:
        def backup(self, target, *, pages, progress, sleep):
            assert pages == 256 and sleep == 0
            progress(status, total - 1, total)

    monkeypatch.setattr(backup.time, "monotonic", lambda: 1)
    with pytest.raises(BackupError):
        backup._copy_pages(Source(), None, 4096, 1 << 20, deadline)


def test_source_control_disagreement_refuses_backup_and_disables_owner(tmp_path: Path):
    destination = tmp_path / "backup.db"
    with create(tmp_path / "source.db") as source:
        source._db().execute("UPDATE control SET sequence=1")
        from axiom.durable import UnavailableError

        with pytest.raises(UnavailableError, match="control"):
            source.backup(destination)
        with pytest.raises(UnavailableError):
            source.partner(0)
    assert not destination.exists()


@pytest.mark.parametrize(
    "stage", ["during_copy", "before_publish", "after_link", "after_publish"]
)
def test_process_death_during_backup_leaves_only_absent_or_complete_destination(
    tmp_path: Path, stage: str
) -> None:
    source, destination = tmp_path / "source.db", tmp_path / "backup.db"
    with Durable(
        source,
        n=150000 if stage == "during_copy" else 16,
        width=0,
        max_batch=4,
        max_operations=32,
        checkpoint_interval=8,
        retain_operations=8,
    ) as store:
        store.checkpoint()
        store.apply([edit(1)])
        before = state(store)
    script = """
import os, sys
from pathlib import Path
from axiom import backup
from axiom.durable import Durable
source, destination, stage = sys.argv[1:]
target = '_copy_pages' if stage == 'during_copy' else '_publish'
original = getattr(backup, target)
def die(*args):
    if stage == 'during_copy':
        source, target = args[:2]
        def partial(status, remaining, total):
            os._exit(73 if remaining > 0 else 74)
        source.backup(target, pages=1, progress=partial, sleep=0)
    elif stage == 'after_link':
        os.link(*args)
    elif stage != 'before_publish':
        original(*args)
    os._exit(73)
setattr(backup, target, die)
with Durable(source) as store:
    store.backup(Path(destination))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(source), str(destination), stage], timeout=10
    )
    assert result.returncode == 73
    assert destination.exists() == (stage in ("after_link", "after_publish"))
    if destination.exists():
        with Durable(destination) as restored:
            assert state(restored) == before and restored.check()
    with Durable(source) as restored:
        assert state(restored) == before and restored.check()
        assert restored.apply([edit(2)]) == (Outcome(2, True, 2),)
