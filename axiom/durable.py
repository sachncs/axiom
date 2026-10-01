"""Bounded single-owner durable batches for the explicitly selected native engine.

This first format replays a bounded operation history. Native checkpoints and
history compaction are deliberately not claimed yet. Use a private local POSIX
directory, not a network filesystem or an independently writable database.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import threading
import warnings
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from axiom.engine import Engine


class BusyError(RuntimeError):
    """Reject admission while the sole owner is updating, querying, or recovering."""


class CapacityError(RuntimeError):
    """Reject before mutation when the bounded history or batch is exhausted."""


class RecoveryError(RuntimeError):
    """Refuse to serve an uncertified or incompatible persistent state."""


class UnavailableError(RuntimeError):
    """Require close/recovery after uncertain persistence or publication."""


@dataclass(frozen=True)
class Request:
    """Identify one operation in a contiguous, single sequenced request stream."""

    sequence: int
    operation: Literal["insert", "delete"]
    u: int
    v: int


@dataclass(frozen=True)
class Outcome:
    """Return the original transition result and its logical mutation version."""

    sequence: int
    changed: bool
    version: int


_MAX = (1 << 63) - 1
_FORMAT = "axiom-native-sqlite-replay-v1"
_BACKEND = "incremental-minimum-free-neighbor-v1"
_RECORD = struct.Struct("<QBII?Q")


def _integer(value: int, minimum: int, maximum: int, name: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")


def _digest(
    previous: bytes,
    sequence: int,
    adding: int,
    u: int,
    v: int,
    changed: bool,
    version: int,
) -> bytes:
    return hashlib.sha256(
        previous + _RECORD.pack(sequence, adding, u, v, changed, version)
    ).digest()


class Durable:
    """Publish certified batches only after SQLite FULL-WAL commit succeeds.

    No internal admission queue: concurrent calls fail fast with BusyError. New
    sequences start at 1 and must be contiguous; retries must carry the identical
    canonical payload. Every retained result, including no-ops, is durable.
    At max_operations, new requests reject until checkpoint support is delivered.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        n: int | None = None,
        width: int = 2,
        budget: int = 1 << 30,
        max_batch: int = 256,
        max_operations: int = 65536,
        max_database_bytes: int = 64 << 20,
    ) -> None:
        """Create/recover a private local database with explicit bounded limits."""
        if os.name != "posix":
            raise ValueError("the durable owner lock currently requires POSIX")
        _integer(budget, 1, _MAX, "budget")
        _integer(max_batch, 1, 4096, "max_batch")
        _integer(max_operations, 1, 1_000_000, "max_operations")
        _integer(max_database_bytes, 1 << 20, 1 << 30, "max_database_bytes")
        _integer(width, 0, 0xFFFFFFFF, "width")
        if n is not None:
            _integer(n, 0, 0xFFFFFFFF, "n")
        self._path = Path(path).absolute()
        if self._path.is_symlink() or not self._path.parent.is_dir():
            raise ValueError(
                "require a non-symlink file in an existing local directory"
            )
        self._lock = threading.Lock()
        self._closed = False
        self._failed = False
        self._max_batch = max_batch
        self._max_operations = max_operations
        self._budget = budget
        self._connection: sqlite3.Connection | None = None
        self._lock_fd = -1
        self._count = 0
        self._tail = bytes(32)
        try:
            self._acquire_owner()
            self._connection = sqlite3.connect(
                self._path,
                isolation_level=None,
                timeout=0,
                check_same_thread=False,
            )
            self._configure(max_database_bytes)
            self._recover(n, width)
            descriptor = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except BaseException:
            self._release()
            raise

    def _acquire_owner(self) -> None:
        import fcntl

        flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
        self._lock_fd = os.open(str(self._path) + ".owner", flags, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise BusyError("database already has a live owner") from error

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise UnavailableError("durable store is closed")
        return self._connection

    def _configure(self, maximum: int) -> None:
        db = self._db()
        if db.execute("PRAGMA journal_mode=WAL").fetchone() != ("wal",):
            raise RecoveryError("SQLite WAL mode is unavailable")
        for setting in (
            "synchronous=FULL",
            "fullfsync=ON",
            "checkpoint_fullfsync=ON",
            "wal_autocheckpoint=256",
            "journal_size_limit=4194304",
            "cache_size=-4096",
            "mmap_size=0",
            "trusted_schema=OFF",
        ):
            db.execute(f"PRAGMA {setting}")
        for name, expected in (
            ("synchronous", 2),
            ("fullfsync", 1),
            ("checkpoint_fullfsync", 1),
            ("wal_autocheckpoint", 256),
        ):
            if db.execute(f"PRAGMA {name}").fetchone() != (expected,):
                raise RecoveryError(f"SQLite rejected required setting: {name}")
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        pages = maximum // page_size
        if db.execute(f"PRAGMA max_page_count={pages}").fetchone() != (pages,):
            raise CapacityError("existing database exceeds the configured page limit")
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RecoveryError("SQLite structural integrity check failed")

    def _recover(self, requested: int | None, width: int) -> None:
        db = self._db()
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        if not tables:
            if requested is None:
                raise ValueError("n is required to initialize an empty database")
            self._engine = Engine(requested, budget=self._budget)
            if width:
                self._engine.ring(width)
            metadata = json.dumps(
                {
                    "format": _FORMAT,
                    "backend": _BACKEND,
                    "n": requested,
                    "width": width,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            self._tail = hashlib.sha256(metadata.encode()).digest()
            self._base_digest = self._tail
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "CREATE TABLE control (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "metadata TEXT NOT NULL, sequence INTEGER NOT NULL, "
                    "version INTEGER NOT NULL, digest BLOB NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE operations (sequence INTEGER PRIMARY KEY, "
                    "adding INTEGER NOT NULL, u INTEGER NOT NULL, v INTEGER NOT NULL, "
                    "changed INTEGER NOT NULL, version INTEGER NOT NULL, "
                    "digest BLOB NOT NULL)"
                )
                db.execute(
                    "INSERT INTO control VALUES(1, ?, 0, ?, ?)",
                    (metadata, self._engine.version, self._tail),
                )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
            return
        if tables != [("control",), ("operations",)]:
            raise RecoveryError("unrecognized durable schema")
        control = db.execute(
            "SELECT metadata, sequence, version, digest FROM control WHERE id=1 "
            "AND length(metadata)<=4096 AND length(digest)=32"
        ).fetchone()
        if (
            control is None
            or db.execute("SELECT count(*) FROM control").fetchone()[0] != 1
        ):
            raise RecoveryError("invalid durable control record")
        metadata, sequence, version, tail = control
        try:
            config = json.loads(metadata)
            if (
                not isinstance(config, dict)
                or set(config) != {"format", "backend", "n", "width"}
                or config["format"] != _FORMAT
                or config["backend"] != _BACKEND
            ):
                raise ValueError("unsupported format/backend")
            _integer(config["n"], 0, 0xFFFFFFFF, "stored n")
            _integer(config["width"], 0, 0xFFFFFFFF, "stored width")
            _integer(sequence, 0, self._max_operations, "stored sequence")
            _integer(version, 0, _MAX, "stored version")
        except (TypeError, ValueError) as error:
            raise RecoveryError("invalid durable metadata") from error
        if requested is not None and requested != config["n"]:
            raise ValueError("requested vertex universe differs from durable state")
        if db.execute("SELECT count(*) FROM operations").fetchone()[0] != sequence:
            raise RecoveryError("durable history count disagrees with control record")
        self._engine = Engine(config["n"], budget=self._budget)
        if config["width"]:
            self._engine.ring(config["width"])
        self._tail = hashlib.sha256(metadata.encode()).digest()
        self._base_digest = self._tail
        for row in db.execute(
            "SELECT sequence, adding, u, v, changed, version, digest "
            "FROM operations ORDER BY sequence"
        ):
            seq, adding, u, v, changed, recorded, digest = row
            try:
                _integer(seq, self._count + 1, self._count + 1, "operation sequence")
                _integer(adding, 0, 1, "stored operation")
                _integer(u, 0, self._engine.n - 1, "stored u")
                _integer(v, u, self._engine.n - 1, "stored v")
                _integer(changed, 0, 1, "stored transition")
                _integer(recorded, 0, _MAX, "stored version")
                expected = _digest(
                    self._tail, seq, adding, u, v, bool(changed), recorded
                )
                if digest != expected:
                    raise ValueError("operation checksum mismatch")
                actual = (
                    self._engine.insert(u, v) if adding else self._engine.delete(u, v)
                )
                if actual != bool(changed) or self._engine.version != recorded:
                    raise ValueError(
                        "operation outcome disagrees with deterministic replay"
                    )
                self._tail = expected
                self._count += 1
            except (ValueError, TypeError, RuntimeError, struct.error) as error:
                raise RecoveryError("invalid committed operation history") from error
        if (
            self._count != sequence
            or self._tail != tail
            or self._engine.version != version
            or not self._engine.check()
        ):
            raise RecoveryError("recovered graph/matching/control certificate failed")

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        if not self._lock.acquire(blocking=False):
            raise BusyError("durable owner is busy; retry admission later")
        try:
            if self._closed or self._failed:
                raise UnavailableError("store is closed or failed; close and recover")
            yield
        finally:
            self._lock.release()

    def _validate(self, requests: Sequence[Request]) -> tuple[Request, ...]:
        if type(requests) not in (tuple, list) or len(requests) > self._max_batch:
            raise CapacityError("require a list/tuple no larger than max_batch")
        canonical: list[Request] = []
        for request in requests:
            if (
                type(request) is not Request
                or type(request.operation) is not str
                or request.operation not in ("insert", "delete")
            ):
                raise ValueError("require typed insert/delete requests")
            _integer(request.sequence, 1, _MAX, "sequence")
            _integer(request.u, 0, self._engine.n - 1, "u")
            _integer(request.v, 0, self._engine.n - 1, "v")
            canonical.append(
                Request(
                    request.sequence,
                    request.operation,
                    min(request.u, request.v),
                    max(request.u, request.v),
                )
            )
        return tuple(canonical)

    def _persist(self, rows: list[tuple[int, int, int, int, int, int, bytes]]) -> None:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        db.executemany("INSERT INTO operations VALUES(?, ?, ?, ?, ?, ?, ?)", rows)
        last = rows[-1]
        updated = db.execute(
            "UPDATE control SET sequence=?, version=?, digest=? WHERE id=1",
            (last[0], last[5], last[6]),
        )
        if updated.rowcount != 1:
            raise RecoveryError("durable control record disappeared")
        db.execute("COMMIT")

    def _publish(self, token: int) -> None:
        self._engine.commit(token)

    def _retry(self, request: Request) -> Outcome:
        try:
            row = (
                self._db()
                .execute(
                    "SELECT adding,u,v,changed,version,digest,"
                    "(SELECT digest FROM operations WHERE sequence=?) "
                    "FROM operations WHERE sequence=?",
                    (request.sequence - 1, request.sequence),
                )
                .fetchone()
            )
            if row is None:
                raise RecoveryError("retained durable outcome disappeared")
            adding, u, v, changed, version, digest, previous = row
            _integer(adding, 0, 1, "retry operation")
            _integer(u, 0, self._engine.n - 1, "retry u")
            _integer(v, u, self._engine.n - 1, "retry v")
            _integer(changed, 0, 1, "retry transition")
            _integer(version, 0, self._engine.version, "retry version")
            previous = self._base_digest if request.sequence == 1 else previous
            if (
                type(previous) is not bytes
                or len(previous) != 32
                or digest
                != _digest(
                    previous,
                    request.sequence,
                    adding,
                    u,
                    v,
                    bool(changed),
                    version,
                )
            ):
                raise RecoveryError("retained durable outcome checksum failed")
        except (sqlite3.Error, RecoveryError, ValueError, TypeError, struct.error):
            self._failed = True
            raise
        if (adding, u, v) != (int(request.operation == "insert"), request.u, request.v):
            raise ValueError("retry payload differs from its durable operation")
        return Outcome(request.sequence, bool(changed), version)

    def apply(self, requests: Sequence[Request]) -> tuple[Outcome, ...]:
        """Durably apply one bounded atomic group; return only after publication.

        A persistence/publication exception makes the owner unavailable, even if
        in-memory rollback succeeds. Recovery and identical retries determine
        whether a commit survived; exceptions are never success acknowledgments.
        """
        with self._exclusive():
            requests = self._validate(requests)
            plans: dict[int, Request] = {}
            outcomes: dict[int, Outcome] = {}
            next_sequence = self._count + 1
            for request in requests:
                if request.sequence in plans:
                    if plans[request.sequence] != request:
                        raise ValueError("conflicting payload for the same sequence")
                elif request.sequence < next_sequence:
                    plans[request.sequence] = request
                    outcomes[request.sequence] = self._retry(request)
                elif request.sequence == next_sequence:
                    plans[request.sequence] = request
                    next_sequence += 1
                else:
                    raise ValueError("new request sequences must be contiguous")
            fresh = tuple(r for seq, r in plans.items() if seq > self._count)
            if self._count + len(fresh) > self._max_operations:
                raise CapacityError(
                    "bounded replay history is full; checkpoint support pending"
                )
            if not fresh:
                return tuple(outcomes[r.sequence] for r in requests)
            version = self._engine.version
            if version + len(fresh) > _MAX:
                raise CapacityError("durable mutation sequence exhausted")
            token = self._engine.begin()
            rows = []
            tail = self._tail
            persisting = False
            try:
                for request in fresh:
                    adding = int(request.operation == "insert")
                    changed = (
                        self._engine.insert(request.u, request.v)
                        if adding
                        else self._engine.delete(request.u, request.v)
                    )
                    version += changed
                    tail = _digest(
                        tail,
                        request.sequence,
                        adding,
                        request.u,
                        request.v,
                        changed,
                        version,
                    )
                    rows.append(
                        (
                            request.sequence,
                            adding,
                            request.u,
                            request.v,
                            int(changed),
                            version,
                            tail,
                        )
                    )
                    outcomes[request.sequence] = Outcome(
                        request.sequence, changed, version
                    )
                result = tuple(outcomes[r.sequence] for r in requests)
                persisting = True
                self._persist(rows)
                self._publish(token)
                self._count += len(fresh)
                self._tail = tail
                return result
            except BaseException:
                # Diagnostic allocation must never make a failed owner available.
                self._failed = True
                try:
                    if self._engine.active:
                        self._engine.rollback(token)
                    if self._db().in_transaction:
                        self._db().execute("ROLLBACK")
                    self._failed = persisting or self._engine.poisoned
                except BaseException:
                    self._failed = True
                raise

    def partner(self, vertex: int) -> tuple[int, int | None]:
        """Read a partner and its coherent committed version without full copying."""
        with self._exclusive():
            return self._engine.version, self._engine.partner(vertex)

    def status(self) -> dict[str, int | str]:
        """Read bounded committed counts, native memory and persistence settings."""
        with self._exclusive():
            return {
                "version": self._engine.version,
                "sequence": self._count,
                "vertices": self._engine.n,
                "edges": self._engine.num_edges(),
                "matching": self._engine.size(),
                "native_bytes": self._engine.memory()["allocated"],
                "sqlite": sqlite3.sqlite_version,
                "synchronous": "FULL",
                "fullfsync": 1,
                "max_operations": self._max_operations,
                "max_batch": self._max_batch,
            }

    def page(
        self,
        start: int = 0,
        limit: int = 1024,
        version: int | None = None,
    ) -> tuple[int, list[tuple[int, int]], int | None]:
        """Read a bounded matching page, rejecting stale continuation versions."""
        with self._exclusive():
            return self._engine.page(start, limit, version)

    def has_edge(self, u: int, v: int) -> tuple[int, bool]:
        """Read committed topology and its matching-compatible version."""
        with self._exclusive():
            return self._engine.version, self._engine.has_edge(u, v)

    def check(self) -> bool:
        """Run an explicit full native audit, not an ordinary-update scan."""
        with self._exclusive():
            try:
                verified = self._engine.check()
            except BaseException:
                self._failed = True
                raise
            if not verified:
                self._failed = True
            return verified

    def _release(self) -> None:
        # Retain ownership if the database connection cannot be closed safely.
        self._closed = True
        if self._connection is not None:
            self._connection.close()
        self._connection = None
        if self._lock_fd >= 0:
            os.close(self._lock_fd)
            self._lock_fd = -1
        if hasattr(self, "_engine"):
            del self._engine

    def close(self) -> None:
        """Close even a failed owner; never unlink its persistent lock file."""
        if not self._lock.acquire(blocking=False):
            raise BusyError("cannot close an active owner")
        try:
            self._release()
        finally:
            self._lock.release()

    def __enter__(self) -> Durable:
        """Use an owner as a context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Release database and process ownership on context exit."""
        self.close()

    def __del__(self) -> None:
        """Best-effort abandoned-owner cleanup; prefer explicit close/context use."""
        if getattr(self, "_lock_fd", -1) >= 0:
            try:
                self._release()
                warnings.warn("unclosed durable owner", ResourceWarning, stacklevel=2)
            except BaseException:
                # Destructors cannot safely report/resolve a close failure.
                pass
