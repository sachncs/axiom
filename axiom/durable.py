"""Bounded single-owner durable batches for the explicitly selected native engine.

Legacy v1 replays a bounded history; explicitly enabled v2 checkpoints retire
history atomically while retaining a declared retry window. Use a private local
POSIX directory, not a network filesystem or independently writable database.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import threading
import time
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


class ExpiredError(ValueError):
    """Reject a retired sequence without guessing its outcome or mutating again."""


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


@dataclass(frozen=True)
class ReadSnapshot:
    """Aligned immutable answers observed at one committed graph version."""

    version: int
    partners: tuple[int | None, ...]
    has_edges: tuple[bool, ...]


_MAX = (1 << 63) - 1
MAX_READS = 4096
_FORMAT = "axiom-native-sqlite-replay-v1"
_CHECKPOINT_FORMAT = "axiom-native-sqlite-checkpoint-v2"
_BACKEND = "incremental-minimum-free-neighbor-v1"
_RECORD = struct.Struct("<QBII?Q")


@dataclass(frozen=True)
class _Checkpoint:
    sequence: int
    version: int
    floor: int
    floor_version: int
    generation: int
    anchor: bytes
    tail: bytes
    image: bytes
    image_digest: bytes
    digest: bytes


def _checkpoint_digest(
    metadata: str,
    sequence: int,
    version: int,
    floor: int,
    floor_version: int,
    generation: int,
    anchor: bytes,
    tail: bytes,
    image_digest: bytes,
) -> bytes:
    return hashlib.sha256(
        metadata.encode()
        + struct.pack("<QQQQQ", sequence, version, floor, floor_version, generation)
        + anchor
        + tail
        + image_digest
    ).digest()


def _integer(value: object, minimum: int, maximum: int, name: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


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
    Legacy v1 rejects at max_operations. Explicit v2 checkpoint mode bounds the
    retained table instead and rejects expired retries, never replaying them anew.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        n: int | None = None,
        width: int = 2,
        budget: int = 1 << 30,
        max_batch: int | None = None,
        max_operations: int | None = None,
        max_database_bytes: int = 64 << 20,
        checkpoint_interval: int | None = None,
        retain_operations: int | None = None,
        max_snapshot_bytes: int = 64 << 20,
    ) -> None:
        """Create/recover a private local database with explicit bounded limits."""
        if os.name != "posix":
            raise ValueError("the durable owner lock currently requires POSIX")
        _integer(budget, 1, _MAX, "budget")
        if max_batch is not None:
            _integer(max_batch, 1, 4096, "max_batch")
        if max_operations is not None:
            _integer(max_operations, 1, 1_000_000, "max_operations")
        if checkpoint_interval is not None:
            _integer(checkpoint_interval, 1, 1_000_000, "checkpoint_interval")
        if retain_operations is not None:
            _integer(retain_operations, 1, 1_000_000, "retain_operations")
        _integer(max_snapshot_bytes, 40, 1 << 30, "max_snapshot_bytes")
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
        self._publication_lock = threading.RLock()
        self._closed = False
        self._failed = False
        self._requested_batch = max_batch
        self._requested_operations = max_operations
        self._requested_interval = checkpoint_interval
        self._requested_retention = retain_operations
        self._max_batch = 256 if max_batch is None else max_batch
        self._max_operations = 65536 if max_operations is None else max_operations
        self._interval = 0 if checkpoint_interval is None else checkpoint_interval
        self._retention = 16384 if retain_operations is None else retain_operations
        self._max_snapshot_bytes = max_snapshot_bytes
        self._floor = self._checkpoint_sequence = self._generation = 0
        self._floor_version = 0
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
            if not self._interval and self._requested_retention is not None:
                raise ValueError("retry retention requires checkpoint_interval")
            config = {
                "format": _FORMAT,
                "backend": _BACKEND,
                "n": requested,
                "width": width,
            }
            if self._interval:
                config.update(
                    format=_CHECKPOINT_FORMAT,
                    checkpoint_interval=self._interval,
                    retain_operations=self._retention,
                    batch_limit=self._max_batch,
                    history_limit=self._max_operations,
                )
                self._history_policy(config)
            self._engine = Engine(requested, budget=self._budget)
            if width:
                self._engine.ring(width)
            if self._interval:
                self._image_admission(())
            metadata = json.dumps(
                config,
                sort_keys=True,
                separators=(",", ":"),
            )
            self._tail = hashlib.sha256(metadata.encode()).digest()
            self._base_digest = self._tail
            self._metadata = metadata
            self._anchor = self._tail
            self._floor_version = self._engine.version
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "CREATE TABLE control (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "metadata TEXT NOT NULL, sequence INTEGER NOT NULL, "
                    "version INTEGER NOT NULL, digest BLOB NOT NULL"
                    + (
                        ", generation INTEGER NOT NULL DEFAULT 0"
                        if self._interval
                        else ""
                    )
                    + ")"
                )
                db.execute(
                    "CREATE TABLE operations (sequence INTEGER PRIMARY KEY, "
                    "adding INTEGER NOT NULL, u INTEGER NOT NULL, v INTEGER NOT NULL, "
                    "changed INTEGER NOT NULL, version INTEGER NOT NULL, "
                    "digest BLOB NOT NULL)"
                )
                db.execute(
                    "INSERT INTO control(id,metadata,sequence,version,digest) "
                    "VALUES(1, ?, 0, ?, ?)",
                    (metadata, self._engine.version, self._tail),
                )
                if self._interval:
                    db.execute(
                        "CREATE TABLE checkpoints (id INTEGER PRIMARY KEY CHECK(id=1), "
                        "sequence INTEGER NOT NULL, version INTEGER NOT NULL, "
                        "floor INTEGER NOT NULL, floor_version INTEGER NOT NULL, "
                        "generation INTEGER NOT NULL, anchor BLOB NOT NULL, "
                        "tail BLOB NOT NULL, image BLOB NOT NULL, "
                        "image_digest BLOB NOT NULL, digest BLOB NOT NULL)"
                    )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
            return
        if tables not in (
            [("control",), ("operations",)],
            [("checkpoints",), ("control",), ("operations",)],
        ):
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
                or config.get("format") not in (_FORMAT, _CHECKPOINT_FORMAT)
                or config["backend"] != _BACKEND
            ):
                raise ValueError("unsupported format/backend")
            base_keys = {"format", "backend", "n", "width"}
            if config["format"] == _CHECKPOINT_FORMAT:
                if set(config) != base_keys | {
                    "checkpoint_interval",
                    "retain_operations",
                    "batch_limit",
                    "history_limit",
                }:
                    raise ValueError("invalid checkpoint format configuration")
                if tables != [("checkpoints",), ("control",), ("operations",)]:
                    raise ValueError("checkpoint table missing")
                self._history_policy(config)
            elif (
                set(config) != base_keys
                or len(tables) != 2
                or self._requested_interval is not None
                or self._requested_retention is not None
            ):
                raise ValueError("legacy format cannot silently enable checkpoints")
            _integer(config["n"], 0, 0xFFFFFFFF, "stored n")
            _integer(config["width"], 0, 0xFFFFFFFF, "stored width")
            _integer(
                sequence,
                0,
                _MAX if self._interval else self._max_operations,
                "stored sequence",
            )
            _integer(version, 0, _MAX, "stored version")
        except (TypeError, ValueError, KeyError) as error:
            raise RecoveryError("invalid durable metadata") from error
        if requested is not None and requested != config["n"]:
            raise ValueError("requested vertex universe differs from durable state")
        self._metadata = metadata
        self._base_digest = hashlib.sha256(metadata.encode()).digest()
        self._anchor = self._base_digest
        checkpoint_tail = self._restore_checkpoint(config, sequence, version)
        self._tail = self._anchor
        self._count = self._floor
        retained = db.execute("SELECT count(*) FROM operations").fetchone()[0]
        if retained != sequence - self._floor or retained > self._max_operations:
            raise RecoveryError("durable history count disagrees with control record")
        previous_version = self._floor_version
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
                if recorded != previous_version + changed:
                    raise ValueError("operation version progression failed")
                expected = _digest(
                    self._tail, seq, adding, u, v, bool(changed), recorded
                )
                if digest != expected:
                    raise ValueError("operation checksum mismatch")
                if seq > self._checkpoint_sequence:
                    actual = (
                        self._engine.insert(u, v)
                        if adding
                        else self._engine.delete(u, v)
                    )
                    if actual != bool(changed) or self._engine.version != recorded:
                        raise ValueError(
                            "operation outcome disagrees with deterministic replay"
                        )
                elif seq == self._checkpoint_sequence and (
                    expected != checkpoint_tail or recorded != self._engine.version
                ):
                    raise ValueError("checkpoint/cache boundary disagrees")
                self._tail = expected
                self._count += 1
                previous_version = recorded
            except (ValueError, TypeError, RuntimeError, struct.error) as error:
                raise RecoveryError("invalid committed operation history") from error
        if (
            self._count != sequence
            or self._tail != tail
            or self._engine.version != version
            or not self._engine.check()
        ):
            raise RecoveryError("recovered graph/matching/control certificate failed")

    def _history_policy(self, config: dict[str, object]) -> None:
        interval = _integer(
            config["checkpoint_interval"], 1, 1_000_000, "checkpoint_interval"
        )
        retention = _integer(
            config["retain_operations"], 1, 1_000_000, "retain_operations"
        )
        batch = _integer(config["batch_limit"], 1, 4096, "batch_limit")
        capacity = _integer(config["history_limit"], 1, 1_000_000, "history_limit")
        if retention < batch or interval + retention + batch > capacity:
            raise ValueError(
                "require batch <= retention and "
                "interval+retention+batch <= history limit"
            )
        for supplied, stored in (
            (self._requested_interval, interval),
            (self._requested_retention, retention),
            (self._requested_batch, batch),
            (self._requested_operations, capacity),
        ):
            if supplied is not None and supplied != stored:
                raise ValueError(
                    "requested checkpoint policy differs from persisted policy"
                )
        self._interval, self._retention = interval, retention
        self._max_batch, self._max_operations = batch, capacity

    def _restore_checkpoint(
        self, config: dict[str, object], sequence: int, version: int
    ) -> bytes:
        db = self._db()
        row = None
        if self._interval:
            self._generation = db.execute(
                "SELECT generation FROM control WHERE id=1"
            ).fetchone()[0]
            _integer(self._generation, 0, _MAX, "checkpoint generation")
            count = db.execute("SELECT count(*) FROM checkpoints").fetchone()[0]
            if count != int(self._generation > 0):
                raise RecoveryError("checkpoint generation/record count disagrees")
            if self._generation:
                row = db.execute(
                    "SELECT sequence,version,floor,floor_version,generation,anchor,"
                    "tail,image_digest,digest,length(image),typeof(image) "
                    "FROM checkpoints WHERE id=1"
                ).fetchone()
                if row is None:
                    raise RecoveryError("committed checkpoint disappeared")
        if row is None:
            n = _integer(config["n"], 0, 0xFFFFFFFF, "stored n")
            width = _integer(config["width"], 0, 0xFFFFFFFF, "stored width")
            self._engine = Engine(n, budget=self._budget)
            if width:
                self._engine.ring(width)
            self._floor_version = self._engine.version
            return self._base_digest
        (
            seq,
            saved_version,
            floor,
            floor_version,
            generation,
            anchor,
            tail,
            image_digest,
            digest,
            size,
            kind,
        ) = row
        try:
            _integer(seq, 0, sequence, "checkpoint sequence")
            _integer(saved_version, 0, version, "checkpoint version")
            _integer(floor, 0, seq, "retired floor")
            _integer(floor_version, 0, saved_version, "retired floor version")
            _integer(
                generation, self._generation, self._generation, "checkpoint generation"
            )
            _integer(size, 40, 1 << 30, "image size")
            if kind != "blob" or any(
                type(value) is not bytes or len(value) != 32
                for value in (anchor, tail, image_digest, digest)
            ):
                raise ValueError("invalid checkpoint digest/image type")
            if (
                floor != max(0, seq - self._retention)
                or sequence - seq >= self._interval + self._max_batch
                or digest
                != _checkpoint_digest(
                    self._metadata,
                    seq,
                    saved_version,
                    floor,
                    floor_version,
                    generation,
                    anchor,
                    tail,
                    image_digest,
                )
            ):
                raise ValueError("checkpoint policy/certificate disagrees")
            if size > self._max_snapshot_bytes:
                raise MemoryError("checkpoint exceeds configured input byte limit")
            retained = db.execute("SELECT count(*) FROM operations").fetchone()[0]
            if retained != sequence - floor or retained > self._max_operations:
                raise ValueError("checkpoint retained history count disagrees")
            image = db.execute("SELECT image FROM checkpoints WHERE id=1").fetchone()[0]
            if (
                type(image) is not bytes
                or len(image) != size
                or hashlib.sha256(image).digest() != image_digest
            ):
                raise ValueError("checkpoint image checksum failed")
            self._engine = Engine.restore(
                image, budget=self._budget, max_bytes=self._max_snapshot_bytes
            )
            if self._engine.n != config["n"] or self._engine.version != saved_version:
                raise ValueError("native checkpoint universe/version disagrees")
        except (ValueError, TypeError, RuntimeError, struct.error) as error:
            raise RecoveryError("invalid committed checkpoint") from error
        self._floor, self._floor_version = floor, floor_version
        self._checkpoint_sequence, self._anchor = seq, anchor
        return bytes(tail)

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

    def _image_admission(self, fresh: Sequence[Request]) -> None:
        maximum = (self._max_snapshot_bytes - 40 - 8 * self._engine.n) // 8
        edges = self._engine.num_edges()
        if edges > maximum:
            raise CapacityError("graph exceeds configured checkpoint image capacity")
        if edges + sum(r.operation == "insert" for r in fresh) <= maximum:
            return
        # Only near the cap, simulate the bounded group's exact topology changes;
        # duplicates/no-ops must not be rejected by an inaccurate upper bound.
        states: dict[tuple[int, int], bool] = {}
        for request in fresh:
            key = (request.u, request.v)
            if request.u == request.v:
                continue
            prior = states[key] if key in states else self._engine.has_edge(*key)
            adding = request.operation == "insert"
            if prior != adding:
                edges += 1 if adding else -1
                states[key] = adding
            if edges > maximum:
                raise CapacityError("group would exceed checkpoint image capacity")

    def _checkpoint_record(self) -> _Checkpoint:
        db = self._db()
        control = db.execute(
            "SELECT metadata,sequence,version,digest,generation FROM control WHERE id=1"
        ).fetchone()
        version = self._engine.version
        if control != (
            self._metadata,
            self._count,
            version,
            self._tail,
            self._generation,
        ):
            raise RecoveryError("checkpoint control disagrees with published owner")
        floor = max(0, self._count - self._retention)
        anchor, floor_version = self._anchor, self._floor_version
        previous, recorded = self._anchor, self._floor_version
        sequence = self._floor
        for seq, adding, u, v, changed, current, digest in db.execute(
            "SELECT sequence,adding,u,v,changed,version,digest "
            "FROM operations ORDER BY sequence"
        ):
            try:
                # Keep every strict type/range/version check, but avoid six
                # Python helper calls per retained row at each checkpoint.
                if (
                    type(seq) is not int
                    or seq != sequence + 1
                    or type(adding) is not int
                    or not 0 <= adding <= 1
                    or type(u) is not int
                    or not 0 <= u < self._engine.n
                    or type(v) is not int
                    or not u <= v < self._engine.n
                    or type(changed) is not int
                    or not 0 <= changed <= 1
                    or type(current) is not int
                    or current != recorded + changed
                ):
                    raise ValueError("invalid checkpoint operation fields")
                expected = _digest(previous, seq, adding, u, v, bool(changed), current)
                if digest != expected:
                    raise ValueError("checkpoint operation checksum failed")
            except (ValueError, TypeError, struct.error) as error:
                raise RecoveryError("uncertified checkpoint history") from error
            previous, recorded, sequence = expected, current, seq
            if seq == floor:
                anchor, floor_version = expected, current
        if sequence != self._count or previous != self._tail or recorded != version:
            raise RecoveryError("checkpoint history tail disagrees")
        image = self._engine.snapshot(max_bytes=self._max_snapshot_bytes)
        image_digest = hashlib.sha256(image).digest()
        generation = self._generation + 1
        digest = _checkpoint_digest(
            self._metadata,
            self._count,
            version,
            floor,
            floor_version,
            generation,
            anchor,
            self._tail,
            image_digest,
        )
        return _Checkpoint(
            self._count,
            version,
            floor,
            floor_version,
            generation,
            anchor,
            self._tail,
            image,
            image_digest,
            digest,
        )

    def _persist_checkpoint(self, record: _Checkpoint) -> None:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT OR REPLACE INTO checkpoints VALUES(1,?,?,?,?,?,?,?,?,?,?)",
            (
                record.sequence,
                record.version,
                record.floor,
                record.floor_version,
                record.generation,
                record.anchor,
                record.tail,
                record.image,
                record.image_digest,
                record.digest,
            ),
        )
        updated = db.execute(
            "UPDATE control SET generation=? WHERE id=1 AND sequence=? AND version=? "
            "AND digest=? AND generation=?",
            (
                record.generation,
                record.sequence,
                record.version,
                record.tail,
                self._generation,
            ),
        )
        if updated.rowcount != 1:
            raise RecoveryError("checkpoint control publication precondition failed")
        db.execute("DELETE FROM operations WHERE sequence<=?", (record.floor,))
        db.execute("COMMIT")

    def _install_checkpoint(self, record: _Checkpoint) -> None:
        self._checkpoint_sequence = record.sequence
        self._floor, self._floor_version = record.floor, record.floor_version
        self._anchor, self._generation = record.anchor, record.generation

    def _checkpoint(self) -> dict[str, int]:
        if not self._interval:
            raise ValueError("checkpoint requires an explicitly enabled v2 store")
        if self._generation == _MAX:
            raise CapacityError("checkpoint generation exhausted")
        persisting = False
        try:
            record = self._checkpoint_record()
            result = {
                "checkpoint_sequence": record.sequence,
                "retired_floor": record.floor,
                "retained_operations": record.sequence - record.floor,
                "generation": record.generation,
            }
            persisting = True
            self._persist_checkpoint(record)
            self._install_checkpoint(record)
            return result
        except BaseException as error:
            self._failed = (
                persisting
                or self._engine.poisoned
                or not isinstance(error, MemoryError)
            )
            try:
                if self._db().in_transaction:
                    self._db().execute("ROLLBACK")
            except BaseException:
                self._failed = True
            raise

    def checkpoint(self) -> dict[str, int]:
        """Atomically publish an audited image/retired floor and bound retry history.

        This v2 maintenance transaction changes neither graph nor mutation version.
        A persistence/publication exception disables the owner; recovery resolves it.
        """
        with self._exclusive():
            return self._checkpoint()

    def backup(
        self, path: str | Path, *, max_bytes: int = 64 << 20, timeout: float = 30.0
    ) -> dict[str, int | str]:
        """Publish a bounded, self-contained snapshot at a fresh local path.

        Backup failure does not mutate the source. Publication failure may leave
        a complete destination; never overwrite it to retry. Restore independently
        with Durable to audit graph/matching/history. The timeout is checked between
        bounded SQLite steps, not an interrupt of filesystem I/O or a native audit.
        """
        from axiom.backup import copy

        _integer(max_bytes, 1 << 20, 1 << 30, "max_bytes")
        if type(timeout) not in (int, float) or not 0 < timeout <= 3600:
            raise ValueError("backup timeout must be finite and in (0, 3600]")
        destination = Path(path).absolute()
        deadline = time.monotonic() + timeout
        with self._exclusive():
            with self._publication_lock:
                try:
                    verified = self._engine.check()
                except BaseException:
                    self._failed = True
                    raise
                if not verified:
                    self._failed = True
                    raise UnavailableError("source graph/matching certificate failed")
                expected = (
                    1,
                    self._metadata,
                    self._count,
                    self._engine.version,
                    self._tail,
                ) + ((self._generation,) if self._interval else ())
                try:
                    control = (
                        self._db()
                        .execute("SELECT * FROM control WHERE id=1")
                        .fetchone()
                    )
                except sqlite3.Error:
                    self._failed = True
                    raise
                if control != expected:
                    self._failed = True
                    raise UnavailableError(
                        "source durable control/publication disagrees"
                    )
            return copy(self._db(), self._path, destination, max_bytes, deadline)

    def _retry(self, request: Request) -> Outcome:
        if request.sequence <= self._floor:
            raise ExpiredError("sequence is retired; it cannot be applied again")
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
            previous = self._anchor if request.sequence == self._floor + 1 else previous
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
            if self._interval and fresh:
                self._image_admission(fresh)
                if self._count - self._checkpoint_sequence >= self._interval:
                    self._checkpoint()
            if self._count - self._floor + len(fresh) > self._max_operations:
                raise CapacityError("bounded operation history is full")
            if not fresh:
                return tuple(outcomes[r.sequence] for r in requests)
            version = self._engine.version
            if version + len(fresh) > _MAX:
                raise CapacityError("durable mutation sequence exhausted")
            rows = []
            tail = self._tail
            persisting = False
            token = self._engine.begin()
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

    @property
    def _failed(self) -> bool:
        return self._is_failed

    @_failed.setter
    def _failed(self, value: bool) -> None:
        with self._publication_lock:
            self._is_failed = value

    @property
    def _closed(self) -> bool:
        return self._is_closed

    @_closed.setter
    def _closed(self, value: bool) -> None:
        with self._publication_lock:
            self._is_closed = value

    def _committed_partner(self, vertex: int) -> tuple[int, int | None]:
        # Native coupled reads retain the GIL, including across private writes.
        # Availability transitions/close serialize against the entire read.
        with self._publication_lock:
            if self._closed or self._failed:
                raise UnavailableError("store is closed or failed; close and recover")
            return self._engine.committed_partner(vertex)

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
                "checkpoint_interval": self._interval,
                "retain_operations": self._retention
                if self._interval
                else self._max_operations,
                "retired_floor": self._floor,
                "checkpoint_sequence": self._checkpoint_sequence,
                "checkpoint_generation": self._generation,
                "retained_operations": self._count - self._floor,
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

    def read_snapshot(
        self,
        vertices: Sequence[int],
        edges: Sequence[tuple[int, int]],
        *,
        expected_version: int | None = None,
    ) -> ReadSnapshot:
        """Read bounded partner and edge queries at one committed version.

        At most 4096 total queries are accepted. A supplied expected version is
        a stale-read guard, not a request for historical state. The immutable
        result preserves duplicates and input ordering in both answer tuples.
        """
        if type(vertices) not in (list, tuple) or type(edges) not in (list, tuple):
            raise ValueError("vertices and edges must be lists or tuples")
        if len(vertices) + len(edges) > MAX_READS:
            raise CapacityError("read snapshot exceeds 4096 total queries")
        if expected_version is not None:
            _integer(expected_version, 0, _MAX, "expected_version")
        for vertex in vertices:
            _integer(vertex, 0, self._engine.n - 1, "vertex")
        canonical_edges: list[tuple[int, int]] = []
        for edge in edges:
            if type(edge) not in (list, tuple) or len(edge) != 2:
                raise ValueError("each edge query must be a pair")
            u = _integer(edge[0], 0, self._engine.n - 1, "u")
            v = _integer(edge[1], 0, self._engine.n - 1, "v")
            canonical_edges.append((u, v))
        with self._exclusive():
            version = self._engine.version
            if expected_version is not None and expected_version != version:
                raise RuntimeError("stale read snapshot version")
            partners = tuple(self._engine.partner(vertex) for vertex in vertices)
            has_edges = tuple(self._engine.has_edge(u, v) for u, v in canonical_edges)
            return ReadSnapshot(version, partners, has_edges)

    def check(self) -> bool:
        """Run an explicit full native audit, not an ordinary-update scan."""
        with self._exclusive(), self._publication_lock:
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
