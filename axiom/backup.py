"""Bounded SQLite snapshot copying and no-overwrite local publication.

Used only under the durable owner's gate. No direct independent live database
access, source mutation, graph clone, or user callback is introduced here.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


class BackupError(RuntimeError):
    """Report failed/uncertain backup publication, not a failed graph mutation.

    The destination may already contain a complete snapshot after publication began.
    Never overwrite it to retry. Restore/inspect it independently or use a fresh path.
    """


def _copy_pages(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    page_size: int,
    maximum: int,
    deadline: float,
) -> None:
    def progress(status: int, remaining: int, total: int) -> None:
        if status in (5, 6):  # SQLITE_BUSY/SQLITE_LOCKED, including Python 3.10.
            raise BackupError("SQLite backup encountered contention")
        if total * page_size > maximum:
            raise BackupError("backup image exceeds max_bytes")
        if time.monotonic() >= deadline:
            raise BackupError("backup deadline exceeded; blocking I/O is not preempted")

    source.backup(target, pages=256, progress=progress, sleep=0)


def _sync_file(path: Path) -> None:
    import fcntl

    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
        if sys.platform == "darwin":
            fcntl.fcntl(descriptor, fcntl.F_FULLFSYNC)
    finally:
        os.close(descriptor)


def _publish(temporary: Path, destination: Path) -> None:
    # A same-filesystem hard link publishes complete bytes and refuses overwrite.
    os.link(temporary, destination, follow_symlinks=False)
    descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def copy(
    source: sqlite3.Connection,
    source_path: Path,
    destination: Path,
    maximum: int,
    deadline: float,
) -> dict[str, int | str]:
    """Copy the committed SQLite snapshot; coordinate the destination owner lock."""
    import fcntl

    destination = destination.absolute()
    resolved = destination.resolve()
    reserved = {
        Path(str(source_path.resolve()) + suffix)
        for suffix in ("", ".owner", "-wal", "-shm", "-journal")
    }
    if resolved in reserved or not destination.parent.is_dir():
        raise ValueError(
            "backup requires a distinct path in an existing local directory"
        )
    if destination.is_symlink():
        raise ValueError("backup destination must not be a symlink")
    lock = -1
    try:
        lock = os.open(
            str(destination) + ".owner",
            os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for suffix in ("", "-wal", "-shm", "-journal"):
            if os.path.lexists(str(destination) + suffix):
                raise BackupError("backup destination or sidecar already exists")
        if source.in_transaction:
            raise BackupError("backup requires an idle committed source")
        page_size = source.execute("PRAGMA page_size").fetchone()[0]
        pages = source.execute("PRAGMA page_count").fetchone()[0]
        if pages * page_size > maximum:
            raise BackupError("backup image exceeds max_bytes")
        control = source.execute("SELECT * FROM control WHERE id=1").fetchone()
        # A private temporary directory also isolates SQLite's temporary sidecars.
        with TemporaryDirectory(
            prefix=".axiom-backup-", dir=destination.parent
        ) as work:
            image = Path(work) / "snapshot.db"
            descriptor = os.open(image, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)
            target = sqlite3.connect(image, isolation_level=None, timeout=0)
            try:
                for setting in (
                    f"page_size={page_size}",
                    f"max_page_count={maximum // page_size}",
                    "synchronous=FULL",
                    "fullfsync=ON",
                    "cache_size=-4096",
                    "mmap_size=0",
                    "trusted_schema=OFF",
                ):
                    target.execute(f"PRAGMA {setting}")
                _copy_pages(source, target, page_size, maximum, deadline)
                if target.execute("PRAGMA journal_mode=DELETE").fetchone() != (
                    "delete",
                ):
                    raise BackupError("backup cannot be made self-contained")
                if target.execute("PRAGMA freelist_count").fetchone()[0]:
                    # Compact only the private copy. INTO avoids an in-place
                    # rewrite journal, retaining recovery headroom on tight
                    # filesystems. Never vacuum the live authority.
                    compact = Path(work) / "compact.db"
                    descriptor = os.open(
                        compact, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
                    )
                    os.close(descriptor)

                    def expired() -> int:
                        return int(time.monotonic() >= deadline)

                    target.set_progress_handler(expired, 1000)
                    try:
                        target.execute("VACUUM INTO ?", (str(compact),))
                    finally:
                        target.set_progress_handler(None, 0)
                    target.close()
                    image = compact
                    target = sqlite3.connect(image, isolation_level=None, timeout=0)
                    for setting in (
                        "cache_size=-4096",
                        "mmap_size=0",
                        "trusted_schema=OFF",
                    ):
                        target.execute(f"PRAGMA {setting}")
                if (
                    target.execute("PRAGMA quick_check").fetchone() != ("ok",)
                    or target.execute("SELECT * FROM control WHERE id=1").fetchone()
                    != control
                ):
                    raise BackupError("backup SQLite/control integrity check failed")
            finally:
                target.close()
            size = image.stat().st_size
            if size > maximum:
                raise BackupError("backup image exceeds max_bytes")
            digest = hashlib.sha256()
            with image.open("rb") as stream:
                while block := stream.read(1 << 20):
                    digest.update(block)
            if time.monotonic() >= deadline:
                raise BackupError("backup deadline exceeded before publication")
            _sync_file(image)
            # Allocate the result before publication, so ordinary allocation
            # failure cannot turn a published backup into a missing receipt.
            result: dict[str, int | str] = {
                "sequence": control[2],
                "version": control[3],
                "bytes": size,
                "sha256": digest.hexdigest(),
                "path": str(destination),
            }
            _publish(image, destination)
            return result
    except (OSError, sqlite3.Error) as error:
        raise BackupError("backup I/O failed; destination may already exist") from error
    finally:
        if lock >= 0:
            os.close(lock)
