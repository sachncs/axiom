"""Durable SQLite ownership for the paper Basic and Multilevel matchers.

The database stores a bounded, hash-chained operation history and the selected
paper mode. Recovery replays that history through the same deterministic
``Matcher`` implementation. There is deliberately no native-matcher database
reader, compatibility mode, or state-image codec in this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import threading
import time
import traceback
import warnings
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Literal
from uuid import UUID

from axiom.backup import copy as copy_backup
from axiom.capacity import JournalCapacityError
from axiom.core import Matcher
from axiom.identifier import Identifier
from axiom.storage import Packed


class BusyError(RuntimeError):
    """Reject an operation while the single durable owner is occupied."""


class CapacityError(RuntimeError):
    """Reject work before mutation when a configured resource bound is reached."""


class RecoveryError(RuntimeError):
    """Refuse to serve an unsupported or uncertified persistent database."""


class UnavailableError(RuntimeError):
    """Require close and deterministic recovery after uncertain persistence."""


class ExpiredError(ValueError):
    """Reject a sequence that is outside the retained operation history."""


@dataclass(frozen=True)
class Request:
    """One operation in a contiguous, single sequenced request stream."""

    sequence: int
    operation: Literal["insert", "delete"]
    u: int
    v: int


@dataclass(frozen=True)
class ExternalRequest:
    """One sequenced edge update addressed by stable external identifiers."""

    sequence: int
    operation: Literal["insert", "delete"]
    u: str | int | UUID
    v: str | int | UUID

    def normalize(self) -> ExternalRequest:
        """Validate this request and canonicalize its undirected edge order."""
        if (
            type(self) is not ExternalRequest
            or type(self.operation) is not str
            or self.operation not in ("insert", "delete")
        ):
            raise ValueError("require a typed external insert/delete Request")
        _integer(self.sequence, 1, _MAX, "sequence")
        left = Identifier.encode(self.u)
        right = Identifier.encode(self.v)
        if right < left:
            return ExternalRequest(self.sequence, self.operation, self.v, self.u)
        return self


@dataclass(frozen=True)
class Outcome:
    """A durable request result and the graph version it produced."""

    sequence: int
    changed: bool
    version: int


@dataclass(frozen=True)
class ReadSnapshot:
    """Aligned partner and edge answers from one committed graph version."""

    version: int
    partners: tuple[int | None, ...]
    has_edges: tuple[bool, ...]


@dataclass(frozen=True)
class ExternalSnapshot:
    """Version-coherent snapshot whose partner answers use external IDs."""

    version: int
    partners: tuple[str | int | UUID | None, ...]
    has_edges: tuple[bool, ...]


@dataclass(frozen=True)
class HistoryRecord:
    """One immutable hash-chained operation record."""

    sequence: int
    operation: Literal["insert", "delete"]
    u: int
    v: int
    changed: bool
    version: int
    digest: bytes


@dataclass(frozen=True)
class HistoryPage:
    """A bounded, contiguous history page with a verifiable left boundary."""

    latest_sequence: int
    previous_digest: bytes
    records: tuple[HistoryRecord, ...]
    has_more: bool


MAX_READS = 4096
MAX_OPERATIONS = 1_000_000
MAX_BATCH = 4096
# Start with moderate journal reuse, then split further only when a paper
# component reports that its bounded undo journal is full. The Durable lock
# and one SQLite transaction preserve caller-group atomicity across retries.
PAPER_CHUNK = 8
_FORMAT = "axiom-paper-sqlite-replay-v2"
_LEGACY_FORMAT = "axiom-paper-sqlite-replay-v1"
_IDENTIFIER_FORMAT = "typed-external-id-v1"
_BACKENDS = {"basic": "paper-basic-v1", "multilevel": "paper-multilevel-v1"}
_RECORD = struct.Struct("<QBII?Q")
_IDENTITY_VERTEX = struct.Struct("<Q")
_MAX = (1 << 63) - 1


def _integer(value: object, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _digest(
    previous: bytes,
    sequence: int,
    adding: int,
    left: int,
    right: int,
    changed: bool,
    version: int,
) -> bytes:
    record = _RECORD.pack(sequence, adding, left, right, changed, version)
    return hashlib.sha256(previous + record).digest()


class Durable:
    """Commit paper matcher batches to SQLite before acknowledging the caller.

    Only ``basic`` and ``multilevel`` are valid modes. Each database records its
    mode and complete bounded operation history. A mode mismatch, old database
    format, malformed history, or nondeterministic replay fails closed. Updates
    are private under a Matcher batch journal until the SQLite FULL-WAL commit;
    reads serialize on the same owner lock and therefore observe committed state.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        n: int | None = None,
        mode: str = "basic",
        width: int | None = None,
        budget: int = 1 << 30,
        max_batch: int | None = None,
        max_operations: int | None = None,
        max_database_bytes: int = 64 << 20,
    ) -> None:
        """Open or create a mode-bound paper store under explicit hard limits."""
        if os.name != "posix":
            raise ValueError("durable ownership currently requires POSIX locks")
        if type(mode) is not str or mode not in _BACKENDS:
            raise ValueError("mode must be 'basic' or 'multilevel'")
        if width is not None:
            _integer(width, 0, 0xFFFFFFFF, "width")
        _integer(budget, 1, _MAX, "budget")
        if n is not None:
            _integer(n, 0, 0xFFFFFFFF, "n")
        if max_batch is not None:
            _integer(max_batch, 1, MAX_BATCH, "max_batch")
        if max_operations is not None:
            _integer(max_operations, 1, MAX_OPERATIONS, "max_operations")
        _integer(max_database_bytes, 1 << 20, 1 << 30, "max_database_bytes")

        self._path = Path(path).absolute()
        if self._path.is_symlink() or not self._path.parent.is_dir():
            raise ValueError("require a non-symlink file in an existing directory")
        self._mode = mode
        self._budget = budget
        self._requested_n = n
        self._requested_batch = max_batch
        self._requested_operations = max_operations
        self._max_batch = 256 if max_batch is None else max_batch
        self._max_operations = (
            MAX_OPERATIONS if max_operations is None else max_operations
        )
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None
        self._lock_fd = -1
        self._closed = False
        self._failed = False
        self._count = 0
        self._version = 0
        self._base_version = 0
        self._n = 0
        self._width = 0
        self._tail = bytes(32)
        self._metadata = ""
        self._matcher: Matcher

        try:
            self._acquire_owner()
            self._connection = sqlite3.connect(
                self._path, isolation_level=None, timeout=0, check_same_thread=False
            )
            self._configure(max_database_bytes)
            self._recover(n, width)
            directory = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            self._release()
            raise

    def _acquire_owner(self) -> None:
        # Import only when taking the POSIX owner lock. Durable.__init__ rejects
        # other platforms before reaching this method, while importing axiom's
        # algorithm and storage APIs remains portable.
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
        database = self._db()
        if database.execute("PRAGMA journal_mode=WAL").fetchone() != ("wal",):
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
            database.execute(f"PRAGMA {setting}")
        for name, expected in (
            ("synchronous", 2),
            ("fullfsync", 1),
            ("checkpoint_fullfsync", 1),
            ("wal_autocheckpoint", 256),
        ):
            if database.execute(f"PRAGMA {name}").fetchone() != (expected,):
                raise RecoveryError(f"SQLite rejected required setting: {name}")
        page_size = database.execute("PRAGMA page_size").fetchone()[0]
        pages = maximum // page_size
        if database.execute(f"PRAGMA max_page_count={pages}").fetchone() != (pages,):
            raise CapacityError("database exceeds configured page limit")
        if database.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RecoveryError("SQLite structural integrity check failed")

    def _new_matcher(self, n: int, width: int) -> Matcher:
        graph = Packed(n, budget=self._budget)
        if width:
            graph.ring(width)
        return Matcher(n, mode=self._mode, graph=graph)

    def _replay_operations(
        self, n: int, width: int, metadata: str
    ) -> tuple[Matcher, int, int, int, bytes]:
        """Reconstruct one exact operation prefix in bounded atomic slices."""
        chunk_size = PAPER_CHUNK
        while True:
            # A prior bounded replay may have crossed several successful
            # slices before its next slice exceeded journal capacity. Discard
            # that incomplete private matcher before allocating a fresh graph;
            # retaining both million-vertex graphs can itself exhaust the
            # worker limit and prevent deterministic recovery.
            object.__setattr__(self, "_matcher", None)
            matcher = self._new_matcher(n, width)
            if not isinstance(matcher.graph, Packed):
                raise RecoveryError("paper replay requires packed graph storage")
            self._matcher = matcher
            base_version = matcher.graph.version
            expected_version = base_version
            expected_sequence = 0
            expected_tail = hashlib.sha256(metadata.encode()).digest()
            rows = self._db().execute(
                "SELECT sequence,adding,u,v,changed,version,digest "
                "FROM operations ORDER BY sequence"
            )
            try:
                while group := tuple(islice(rows, chunk_size)):
                    with matcher.batch(max_operations=len(group)):
                        for row in group:
                            (
                                seq,
                                adding,
                                left,
                                right,
                                changed,
                                current,
                                record_digest,
                            ) = row
                            try:
                                _integer(
                                    seq,
                                    expected_sequence + 1,
                                    expected_sequence + 1,
                                    "sequence",
                                )
                                _integer(adding, 0, 1, "operation")
                                _integer(left, 0, n - 1, "left vertex")
                                _integer(right, left, n - 1, "right vertex")
                                _integer(changed, 0, 1, "changed")
                                _integer(current, 0, _MAX, "version")
                                if current != expected_version + changed:
                                    raise ValueError("version progression disagrees")
                                expected = _digest(
                                    expected_tail,
                                    seq,
                                    adding,
                                    left,
                                    right,
                                    bool(changed),
                                    current,
                                )
                                if record_digest != expected:
                                    raise ValueError("operation checksum disagrees")
                                actual = self._transition(bool(adding), left, right)
                                if actual != bool(changed):
                                    raise ValueError(
                                        "paper replay disagrees with committed outcome"
                                    )
                            except (
                                TypeError,
                                ValueError,
                                RuntimeError,
                                struct.error,
                            ) as error:
                                raise RecoveryError(
                                    "invalid committed paper operation history"
                                ) from error
                            expected_sequence, expected_version = seq, current
                            expected_tail = expected
                return (
                    matcher,
                    base_version,
                    expected_sequence,
                    expected_version,
                    expected_tail,
                )
            except JournalCapacityError as capacity_error:
                self._clear_error_frames(capacity_error)
                if chunk_size == 1:
                    object.__setattr__(self, "_matcher", None)
                    del matcher
                    raise
                object.__setattr__(self, "_matcher", None)
                del matcher
                chunk_size = max(1, chunk_size // 2)

    def _recover(self, requested: int | None, width: int | None) -> None:
        database = self._db()
        tables = database.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        if not tables:
            if requested is None:
                raise ValueError("n is required to initialize an empty database")
            initial_width = 2 if width is None else width
            self._n, self._width = requested, initial_width
            self._matcher = self._new_matcher(requested, initial_width)
            assert isinstance(self._matcher.graph, Packed)
            self._version = self._matcher.graph.version
            self._base_version = self._version
            config = {
                "format": _FORMAT,
                "backend": _BACKENDS[self._mode],
                "mode": self._mode,
                "n": requested,
                "width": initial_width,
                "max_batch": self._max_batch,
                "max_operations": self._max_operations,
                "identifier_codec": _IDENTIFIER_FORMAT,
            }
            self._metadata = json.dumps(config, sort_keys=True, separators=(",", ":"))
            self._tail = hashlib.sha256(self._metadata.encode()).digest()
            database.execute("BEGIN IMMEDIATE")
            try:
                database.execute(
                    "CREATE TABLE control (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "metadata TEXT NOT NULL, sequence INTEGER NOT NULL, "
                    "version INTEGER NOT NULL, digest BLOB NOT NULL)"
                )
                database.execute(
                    "CREATE TABLE operations (sequence INTEGER PRIMARY KEY, "
                    "adding INTEGER NOT NULL, u INTEGER NOT NULL, v INTEGER NOT NULL, "
                    "changed INTEGER NOT NULL, version INTEGER NOT NULL, "
                    "digest BLOB NOT NULL)"
                )
                database.execute(
                    "CREATE TABLE identifiers (encoded BLOB PRIMARY KEY, "
                    "vertex INTEGER NOT NULL UNIQUE, digest BLOB NOT NULL)"
                )
                database.execute(
                    "CREATE TABLE identity_control ("
                    "id INTEGER PRIMARY KEY CHECK(id=1), next_vertex INTEGER NOT NULL)"
                )
                database.execute("INSERT INTO identity_control VALUES(1, 0)")
                database.execute(
                    "INSERT INTO control VALUES(1, ?, 0, ?, ?)",
                    (self._metadata, self._version, self._tail),
                )
                database.execute("COMMIT")
            except BaseException:
                if database.in_transaction:
                    database.execute("ROLLBACK")
                raise
            return

        legacy = tables == [("control",), ("operations",)]
        current = tables == [
            ("control",),
            ("identifiers",),
            ("identity_control",),
            ("operations",),
        ]
        if not legacy and not current:
            raise RecoveryError("unsupported database format; no compatibility reader")
        row = database.execute(
            "SELECT metadata,sequence,version,digest FROM control WHERE id=1"
        ).fetchone()
        if (
            row is None
            or database.execute("SELECT count(*) FROM control").fetchone()[0] != 1
        ):
            raise RecoveryError("invalid durable control row")
        metadata, sequence, version, tail = row
        try:
            config = json.loads(metadata)
            if type(config) is dict and config.get("mode") != self._mode:
                raise RecoveryError(
                    f"stored matcher mode {config.get('mode')!r} does not match "
                    f"requested mode {self._mode!r}"
                )
            if (
                type(config) is not dict
                or config.get("format") != (_LEGACY_FORMAT if legacy else _FORMAT)
                or config.get("mode") != self._mode
                or config.get("backend") != _BACKENDS[self._mode]
                or set(config)
                != (
                    {
                        "format",
                        "backend",
                        "mode",
                        "n",
                        "width",
                        "max_batch",
                        "max_operations",
                    }
                    if legacy
                    else {
                        "format",
                        "backend",
                        "mode",
                        "n",
                        "width",
                        "max_batch",
                        "max_operations",
                        "identifier_codec",
                    }
                )
                or (not legacy and config.get("identifier_codec") != _IDENTIFIER_FORMAT)
            ):
                raise ValueError("unsupported format or mode")
            n = _integer(config["n"], 0, 0xFFFFFFFF, "stored n")
            saved_width = _integer(config["width"], 0, 0xFFFFFFFF, "stored width")
            saved_batch = _integer(config["max_batch"], 1, MAX_BATCH, "stored batch")
            saved_limit = _integer(
                config["max_operations"], 1, MAX_OPERATIONS, "stored operation limit"
            )
            _integer(sequence, 0, saved_limit, "stored sequence")
            _integer(version, 0, _MAX, "stored version")
            if requested is not None and requested != n:
                raise ValueError("vertex universe differs from stored configuration")
            if width is not None and width != saved_width:
                raise ValueError("width differs from stored configuration")
            if (
                self._requested_batch is not None
                and saved_batch != self._requested_batch
            ):
                raise ValueError("batch limit differs from stored configuration")
            if (
                self._requested_operations is not None
                and saved_limit != self._requested_operations
            ):
                raise ValueError("operation limit differs from stored configuration")
        except (TypeError, ValueError, KeyError) as error:
            raise RecoveryError("invalid durable metadata") from error

        self._max_batch = saved_batch
        self._max_operations = saved_limit
        self._n, self._width = n, saved_width
        self._metadata = metadata
        (
            self._matcher,
            self._base_version,
            expected_sequence,
            expected_version,
            expected_tail,
        ) = self._replay_operations(n, saved_width, metadata)

        if (
            expected_sequence != sequence
            or expected_version != version
            or expected_tail != tail
            or database.execute("SELECT count(*) FROM operations").fetchone()[0]
            != sequence
            or not self._audit()
        ):
            raise RecoveryError("paper recovery disagrees with durable control state")
        self._count, self._version, self._tail = sequence, version, tail
        if legacy:
            self._upgrade_legacy(config)
        else:
            self._validate_identifiers()

    def _upgrade_legacy(self, config: dict[str, object]) -> None:
        """Upgrade a verified v1 operation log and re-root its digest chain."""
        database = self._db()
        upgraded = dict(config)
        upgraded["format"] = _FORMAT
        upgraded["identifier_codec"] = _IDENTIFIER_FORMAT
        metadata = json.dumps(upgraded, sort_keys=True, separators=(",", ":"))
        tail = hashlib.sha256(metadata.encode()).digest()
        database.execute("BEGIN IMMEDIATE")
        try:
            database.execute(
                "CREATE TABLE identifiers (encoded BLOB PRIMARY KEY, "
                "vertex INTEGER NOT NULL UNIQUE, digest BLOB NOT NULL)"
            )
            database.execute(
                "CREATE TABLE identity_control (id INTEGER PRIMARY KEY CHECK(id=1), "
                "next_vertex INTEGER NOT NULL)"
            )
            database.execute("INSERT INTO identity_control VALUES(1, 0)")
            database.execute("ALTER TABLE operations RENAME TO operations_v1")
            database.execute(
                "CREATE TABLE operations (sequence INTEGER PRIMARY KEY, "
                "adding INTEGER NOT NULL, u INTEGER NOT NULL, v INTEGER NOT NULL, "
                "changed INTEGER NOT NULL, version INTEGER NOT NULL, "
                "digest BLOB NOT NULL)"
            )
            # V1 addressed vertices by integer slot. Preserve every slot ever
            # referenced in retained history before allocating new typed IDs.
            used = database.execute(
                "SELECT u FROM operations_v1 UNION SELECT v FROM operations_v1"
            ).fetchall()
            next_vertex = 0
            for (vertex,) in used:
                encoded = Identifier.encode(vertex)
                database.execute(
                    "INSERT INTO identifiers VALUES(?, ?, ?)",
                    (encoded, vertex, self._identity_digest(encoded, vertex)),
                )
                next_vertex = max(next_vertex, vertex + 1)
            database.execute(
                "UPDATE identity_control SET next_vertex=? WHERE id=1",
                (next_vertex,),
            )
            rows = database.execute(
                "SELECT sequence,adding,u,v,changed,version FROM operations_v1 "
                "ORDER BY sequence"
            )
            for sequence, adding, left, right, changed, version in rows:
                tail = _digest(
                    tail, sequence, adding, left, right, bool(changed), version
                )
                database.execute(
                    "INSERT INTO operations VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (sequence, adding, left, right, changed, version, tail),
                )
            database.execute("DROP TABLE operations_v1")
            changed = database.execute(
                "UPDATE control SET metadata=?,digest=? WHERE id=1 AND sequence=? "
                "AND version=?",
                (metadata, tail, self._count, self._version),
            )
            if changed.rowcount != 1:
                raise RecoveryError("legacy control changed during upgrade")
            database.execute("COMMIT")
        except BaseException:
            if database.in_transaction:
                database.execute("ROLLBACK")
            raise
        self._metadata, self._tail = metadata, tail

    @staticmethod
    def _identity_digest(encoded: bytes, vertex: int) -> bytes:
        """Bind a typed external ID to one monotonic internal vertex slot."""
        return hashlib.sha256(
            b"axiom-identifier-v1" + encoded + _IDENTITY_VERTEX.pack(vertex)
        ).digest()

    def _validate_identifiers(self) -> None:
        """Audit the monotonic ID allocation and every persisted mapping."""
        database = self._db()
        control = database.execute(
            "SELECT next_vertex FROM identity_control WHERE id=1"
        ).fetchone()
        if (
            control is None
            or database.execute("SELECT count(*) FROM identity_control").fetchone()[0]
            != 1
        ):
            raise RecoveryError("invalid identifier allocation control")
        try:
            next_vertex = _integer(control[0], 0, self._n, "next identifier vertex")
        except ValueError as error:
            raise RecoveryError("invalid next identifier vertex") from error
        previous = -1
        for encoded, vertex, digest in database.execute(
            "SELECT encoded,vertex,digest FROM identifiers ORDER BY vertex"
        ):
            try:
                _integer(vertex, previous + 1, self._n - 1, "identifier vertex")
                if type(encoded) is not bytes or type(digest) is not bytes:
                    raise ValueError("identifier row types disagree")
                decoded = Identifier.decode(encoded)
                if Identifier.encode(decoded) != encoded:
                    raise ValueError("identifier encoding is not canonical")
                if digest != self._identity_digest(encoded, vertex):
                    raise ValueError("identifier mapping digest disagrees")
            except (TypeError, ValueError, struct.error) as error:
                raise RecoveryError("invalid durable identifier mapping") from error
            previous = vertex
        if previous >= next_vertex:
            raise RecoveryError("identifier allocation cursor disagrees with mappings")

    def _resolve_identifier(self, value: str | int | UUID) -> int:
        """Resolve one immutable mapping while the Durable lock is held."""
        encoded = Identifier.encode(value)
        row = (
            self._db()
            .execute(
                "SELECT vertex,digest FROM identifiers WHERE encoded=?", (encoded,)
            )
            .fetchone()
        )
        if row is None:
            raise KeyError("external identifier is not registered")
        vertex, digest = row
        try:
            _integer(vertex, 0, self._n - 1, "identifier vertex")
        except ValueError as error:
            raise RecoveryError("identifier vertex is outside the graph") from error
        if digest != self._identity_digest(encoded, vertex):
            raise RecoveryError("identifier mapping digest disagrees")
        if type(vertex) is not int:
            raise RecoveryError("identifier vertex is not an integer")
        return vertex

    def register_identifier(self, value: str | int | UUID) -> int:
        """Durably allocate the next never-reused fixed-universe vertex slot.

        Registration is idempotent for an existing ID. Slots are assigned in
        registration order and are not exposed by external update/query APIs.
        The fixed internal universe remains bounded by ``n``.
        """
        encoded = Identifier.encode(value)
        with self._exclusive():
            database = self._db()
            database.execute("BEGIN IMMEDIATE")
            try:
                existing = database.execute(
                    "SELECT vertex,digest FROM identifiers WHERE encoded=?",
                    (encoded,),
                ).fetchone()
                if existing is not None:
                    vertex, digest = existing
                    if (
                        type(vertex) is not int
                        or digest != self._identity_digest(encoded, vertex)
                        or not 0 <= vertex < self._n
                    ):
                        raise RecoveryError("identifier mapping digest disagrees")
                    database.execute("COMMIT")
                    return vertex

                row = database.execute(
                    "SELECT next_vertex FROM identity_control WHERE id=1"
                ).fetchone()
                if row is None:
                    raise RecoveryError("identifier allocation control is missing")
                vertex = _integer(row[0], 0, self._n, "next identifier vertex")
                if vertex >= self._n:
                    raise CapacityError(
                        "fixed vertex universe has no free identifier slots"
                    )
                database.execute(
                    "INSERT INTO identifiers VALUES(?, ?, ?)",
                    (encoded, vertex, self._identity_digest(encoded, vertex)),
                )
                changed = database.execute(
                    "UPDATE identity_control SET next_vertex=? "
                    "WHERE id=1 AND next_vertex=?",
                    (vertex + 1, vertex),
                )
                if changed.rowcount != 1:
                    raise RecoveryError("identifier allocation cursor changed")
                database.execute("COMMIT")
                return vertex
            except BaseException:
                if database.in_transaction:
                    database.execute("ROLLBACK")
                raise

    def resolve_identifier(self, value: str | int | UUID) -> int:
        """Return the permanent internal slot for one registered external ID."""
        with self._exclusive():
            return self._resolve_identifier(value)

    def external_identifier(self, vertex: int) -> str | int | UUID | None:
        """Return the external ID for a slot, or None when it is unregistered."""
        with self._exclusive():
            _integer(vertex, 0, self._n - 1, "vertex")
            return self._external_identifier(vertex)

    def _external_identifier(self, vertex: int) -> str | int | UUID | None:
        """Return a reverse mapping with the Durable lock already held."""
        row = (
            self._db()
            .execute("SELECT encoded,digest FROM identifiers WHERE vertex=?", (vertex,))
            .fetchone()
        )
        if row is None:
            return None
        encoded, digest = row
        if type(encoded) is not bytes or digest != self._identity_digest(
            encoded, vertex
        ):
            raise RecoveryError("identifier mapping digest disagrees")
        try:
            return Identifier.decode(encoded)
        except (TypeError, ValueError) as error:
            raise RecoveryError("identifier mapping is malformed") from error

    def apply_external(
        self, requests: Sequence[ExternalRequest]
    ) -> tuple[Outcome, ...]:
        """Resolve stable IDs and durably apply their bounded edge update group."""
        if type(requests) not in (list, tuple) or len(requests) > self._max_batch:
            raise CapacityError("require a list/tuple no larger than max_batch")
        normalized: list[Request] = []
        for request in requests:
            if (
                type(request) is not ExternalRequest
                or type(request.operation) is not str
                or request.operation not in ("insert", "delete")
            ):
                raise ValueError("require typed external insert/delete requests")
            _integer(request.sequence, 1, _MAX, "sequence")
            left = self.resolve_identifier(request.u)
            right = self.resolve_identifier(request.v)
            normalized.append(
                Request(
                    request.sequence,
                    request.operation,
                    min(left, right),
                    max(left, right),
                )
            )
        return self.apply(normalized)

    def partner_external(
        self, value: str | int | UUID
    ) -> tuple[int, str | int | UUID | None]:
        """Return a version-coherent partner using external identity values."""
        with self._exclusive():
            vertex = self._resolve_identifier(value)
            partner = self._matcher.partner(vertex)
            external = None if partner is None else self._external_identifier(partner)
            if partner is not None and external is None:
                raise RecoveryError("matched partner has no registered external ID")
            return self._version, external

    def has_edge_external(
        self, left: str | int | UUID, right: str | int | UUID
    ) -> tuple[int, bool]:
        """Query topology by external IDs at the committed graph version."""
        with self._exclusive():
            u = self._resolve_identifier(left)
            v = self._resolve_identifier(right)
            return self._version, self._matcher.graph.has_edge(u, v)

    def read_snapshot_external(
        self,
        vertices: Sequence[str | int | UUID],
        edges: Sequence[tuple[str | int | UUID, str | int | UUID]],
        *,
        expected_version: int | None = None,
    ) -> ExternalSnapshot:
        """Resolve and answer a bounded external-ID snapshot under one lock."""
        if type(vertices) not in (list, tuple) or type(edges) not in (list, tuple):
            raise ValueError("vertices and edges must be lists or tuples")
        if len(vertices) + len(edges) > MAX_READS:
            raise ValueError("read snapshot exceeds 4096 total queries")
        if expected_version is not None:
            _integer(expected_version, 0, _MAX, "expected_version")
        with self._exclusive():
            if expected_version is not None and expected_version != self._version:
                raise RuntimeError("stale snapshot version")
            resolved_vertices = tuple(
                self._resolve_identifier(value) for value in vertices
            )
            resolved_edges = tuple(
                (
                    self._resolve_identifier(left),
                    self._resolve_identifier(right),
                )
                for left, right in edges
            )
            partners = tuple(
                self._matcher.partner(vertex) for vertex in resolved_vertices
            )
            externalpartners = tuple(
                None if partner is None else self._external_identifier(partner)
                for partner in partners
            )
            if any(
                partner is not None and external is None
                for partner, external in zip(partners, externalpartners, strict=True)
            ):
                raise RecoveryError("matched partner has no registered external ID")
            return ExternalSnapshot(
                self._version,
                externalpartners,
                tuple(
                    self._matcher.graph.has_edge(left, right)
                    for left, right in resolved_edges
                ),
            )

    def _transition(self, adding: bool, left: int, right: int) -> bool:
        existed = self._matcher.graph.has_edge(left, right)
        if adding:
            self._matcher.insert(left, right)
            return left != right and not existed
        self._matcher.delete(left, right)
        return left != right and existed

    @staticmethod
    def _clear_error_frames(error: BaseException) -> None:
        """Release locals across a chained failure before memory-bound replay."""
        pending = [error]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            address = id(current)
            if address in seen:
                continue
            seen.add(address)
            traceback.clear_frames(current.__traceback__)
            if current.__cause__ is not None:
                pending.append(current.__cause__)
            if current.__context__ is not None:
                pending.append(current.__context__)

    def _restore_committed_matcher(self) -> None:
        """Rebuild the private matcher after a multi-journal group aborts.

        Durable callers and queued service reads cannot observe the owner's
        matcher while its lock is held. Replaying the previously committed
        prefix is therefore a safe failure-path alternative to retaining every
        sub-batch undo journal until the outer SQLite transaction completes.
        """
        # There is no published reader of this owner while its lock is held.
        # The active matcher may contain successful in-memory sub-slices from
        # an uncommitted outer group, so replay is the source of truth. Release
        # it before allocating the replacement to keep recovery within the
        # same memory envelope as steady-state construction. If replay fails,
        # the caller marks this owner failed and requires a fresh open.
        object.__setattr__(self, "_matcher", None)
        (
            candidate,
            base_version,
            expected_sequence,
            expected_version,
            expected_tail,
        ) = self._replay_operations(self._n, self._width, self._metadata)
        control = (
            self._db()
            .execute("SELECT sequence,version,digest FROM control WHERE id=1")
            .fetchone()
        )
        if (
            control != (expected_sequence, expected_version, expected_tail)
            or expected_sequence != self._count
            or expected_version != self._version
            or base_version != self._base_version
            or expected_tail != self._tail
            or not self._audit()
        ):
            raise RecoveryError("committed state failed rollback audit")

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        if not self._lock.acquire(blocking=False):
            raise BusyError("durable owner is busy; retry later")
        try:
            if self._closed or self._failed:
                raise UnavailableError("store is closed or failed; close and recover")
            yield
        finally:
            self._lock.release()

    def _validate(self, requests: Sequence[Request]) -> tuple[Request, ...]:
        if type(requests) not in (list, tuple) or len(requests) > self._max_batch:
            raise CapacityError("require a list/tuple no larger than max_batch")
        result: list[Request] = []
        for request in requests:
            if (
                type(request) is not Request
                or type(request.operation) is not str
                or request.operation not in ("insert", "delete")
            ):
                raise ValueError("require typed insert/delete requests")
            _integer(request.sequence, 1, _MAX, "sequence")
            _integer(request.u, 0, self._matcher.n - 1, "u")
            _integer(request.v, 0, self._matcher.n - 1, "v")
            result.append(
                Request(
                    request.sequence,
                    request.operation,
                    min(request.u, request.v),
                    max(request.u, request.v),
                )
            )
        return tuple(result)

    def apply(self, requests: Sequence[Request]) -> tuple[Outcome, ...]:
        """Durably publish one contiguous bounded update group atomically."""
        with self._exclusive():
            requests = self._validate(requests)
            plans: dict[int, Request] = {}
            outcomes: dict[int, Outcome] = {}
            next_sequence = self._count + 1
            for request in requests:
                previous = plans.get(request.sequence)
                if previous is not None:
                    if previous != request:
                        raise ValueError("conflicting payload for duplicate sequence")
                elif request.sequence <= self._count:
                    outcomes[request.sequence] = self._retry(request)
                    plans[request.sequence] = request
                elif request.sequence == next_sequence:
                    plans[request.sequence] = request
                    next_sequence += 1
                else:
                    raise ValueError("new operation sequences must be contiguous")

            fresh = tuple(
                request for seq, request in plans.items() if seq > self._count
            )
            if self._count + len(fresh) > self._max_operations:
                raise CapacityError("bounded operation history is full")
            if not fresh:
                return tuple(outcomes[request.sequence] for request in requests)
            if self._version + len(fresh) > _MAX:
                raise CapacityError("graph version exhausted")

            rows: list[tuple[int, int, int, int, int, int, bytes]] = []
            tail = self._tail
            version = self._version
            persistence_started = False

            def persist() -> None:
                nonlocal persistence_started
                persistence_started = True
                self._persist(rows)

            try:
                chunk_size = PAPER_CHUNK
                while True:
                    rows.clear()
                    tail = self._tail
                    version = self._version
                    for request in fresh:
                        outcomes.pop(request.sequence, None)
                    try:
                        chunks = tuple(
                            fresh[offset : offset + chunk_size]
                            for offset in range(0, len(fresh), chunk_size)
                        )
                        for index, chunk in enumerate(chunks):
                            final = index + 1 == len(chunks)
                            with self._matcher.batch(
                                max_operations=len(chunk),
                                before_publish=persist if final else None,
                            ):
                                for request in chunk:
                                    adding = int(request.operation == "insert")
                                    changed = self._transition(
                                        bool(adding), request.u, request.v
                                    )
                                    version += int(changed)
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
                        break
                    except JournalCapacityError as capacity_error:
                        self._clear_error_frames(capacity_error)
                        if chunk_size == 1:
                            raise
                        self._restore_committed_matcher()
                        chunk_size = max(1, chunk_size // 2)
                self._count += len(fresh)
                self._version = version
                self._tail = tail
                return tuple(outcomes[request.sequence] for request in requests)
            except BaseException as group_error:
                try:
                    if self._db().in_transaction:
                        self._db().execute("ROLLBACK")
                except BaseException:
                    persistence_started = True
                self._failed = persistence_started
                if not persistence_started:
                    try:
                        self._clear_error_frames(group_error)
                        self._restore_committed_matcher()
                    except BaseException as recovery_error:
                        self._failed = True
                        raise UnavailableError(
                            "aborted group could not restore committed paper state"
                        ) from recovery_error
                raise

    def _persist(self, rows: list[tuple[int, int, int, int, int, int, bytes]]) -> None:
        """Commit one operation page and control tail in a single SQLite txn."""
        database = self._db()
        database.execute("BEGIN IMMEDIATE")
        try:
            database.executemany(
                "INSERT INTO operations VALUES(?, ?, ?, ?, ?, ?, ?)", rows
            )
            last = rows[-1]
            changed = database.execute(
                "UPDATE control SET sequence=?,version=?,digest=? "
                "WHERE id=1 AND sequence=? AND version=? AND digest=?",
                (
                    last[0],
                    last[5],
                    last[6],
                    self._count,
                    self._version,
                    self._tail,
                ),
            )
            if changed.rowcount != 1:
                raise RecoveryError("durable control precondition failed")
            database.execute("COMMIT")
        except BaseException:
            if database.in_transaction:
                database.execute("ROLLBACK")
            raise

    def _retry(self, request: Request) -> Outcome:
        try:
            row = (
                self._db()
                .execute(
                    "SELECT adding,u,v,changed,version,digest "
                    "FROM operations WHERE sequence=?",
                    (request.sequence,),
                )
                .fetchone()
            )
            if row is None:
                raise RecoveryError("durable outcome disappeared")
            adding, left, right, changed, version, digest = row
            if (adding, left, right) != (
                int(request.operation == "insert"),
                request.u,
                request.v,
            ):
                raise ValueError("retry payload differs from committed operation")
            previous = self._tail_before(request.sequence)
            if digest != _digest(
                previous, request.sequence, adding, left, right, bool(changed), version
            ):
                raise RecoveryError("retry outcome checksum failed")
            return Outcome(request.sequence, bool(changed), version)
        except (
            sqlite3.Error,
            RecoveryError,
            ValueError,
            TypeError,
            struct.error,
        ) as error:
            if isinstance(error, ValueError) and "retry payload" in str(error):
                raise
            self._failed = True
            raise RecoveryError("retained retry could not be verified") from error

    def _tail_before(self, sequence: int) -> bytes:
        if sequence == 1:
            return hashlib.sha256(self._metadata.encode()).digest()
        row = (
            self._db()
            .execute("SELECT digest FROM operations WHERE sequence=?", (sequence - 1,))
            .fetchone()
        )
        if row is None or type(row[0]) is not bytes or len(row[0]) != 32:
            raise RecoveryError("retry history boundary is missing")
        return row[0]

    def partner(self, vertex: int) -> tuple[int, int | None]:
        """Return the current committed graph version and partner."""
        with self._exclusive():
            _integer(vertex, 0, self._matcher.n - 1, "vertex")
            return self._version, self._matcher.partner(vertex)

    def status(self) -> dict[str, int | str]:
        """Return bounded owner, graph, mode, and SQLite settings."""
        with self._exclusive():
            return {
                "version": self._version,
                "sequence": self._count,
                "vertices": self._matcher.n,
                "edges": self._matcher.graph.num_edges(),
                "matching": len(self._matcher.matched_edges),
                "graph_bytes": self._matcher.graph.memory()["allocated"]
                if isinstance(self._matcher.graph, Packed)
                else 0,
                "mode": self._mode,
                "sqlite": sqlite3.sqlite_version,
                "synchronous": "FULL",
                "fullfsync": 1,
                "max_operations": self._max_operations,
                "max_batch": self._max_batch,
                "history_operations": self._count,
            }

    def page(
        self, start: int = 0, limit: int = 1024, version: int | None = None
    ) -> tuple[int, list[tuple[int, int]], int | None]:
        """Return a version-checked matching page and next vertex cursor."""
        with self._exclusive():
            _integer(start, 0, self._matcher.n, "start")
            _integer(limit, 1, MAX_READS, "limit")
            if version is not None and version != self._version:
                raise RuntimeError("stale matching page version")
            stop = min(self._matcher.n, start + MAX_READS)
            matching: list[tuple[int, int]] = []
            for left in range(start, stop):
                right = self._matcher.partner(left)
                if right is not None and left < right:
                    matching.append((left, right))
                    if len(matching) == limit:
                        return (
                            self._version,
                            matching,
                            left + 1 if left + 1 < self._matcher.n else None,
                        )
            return self._version, matching, stop if stop < self._matcher.n else None

    def has_edge(self, u: int, v: int) -> tuple[int, bool]:
        """Return edge membership with the committed logical version."""
        with self._exclusive():
            _integer(u, 0, self._matcher.n - 1, "u")
            _integer(v, 0, self._matcher.n - 1, "v")
            return self._version, self._matcher.graph.has_edge(u, v)

    def read_snapshot(
        self,
        vertices: Sequence[int],
        edges: Sequence[tuple[int, int]],
        *,
        expected_version: int | None = None,
    ) -> ReadSnapshot:
        """Read bounded partner and edge queries from one owner version."""
        if type(vertices) not in (list, tuple) or type(edges) not in (list, tuple):
            raise ValueError("vertices and edges must be lists or tuples")
        if len(vertices) + len(edges) > MAX_READS:
            raise CapacityError("read snapshot exceeds 4096 total queries")
        with self._exclusive():
            for vertex in vertices:
                _integer(vertex, 0, self._matcher.n - 1, "vertex")
            canonical_edges: list[tuple[int, int]] = []
            for edge in edges:
                if type(edge) not in (list, tuple) or len(edge) != 2:
                    raise ValueError("each edge query must be a pair")
                _integer(edge[0], 0, self._matcher.n - 1, "u")
                _integer(edge[1], 0, self._matcher.n - 1, "v")
                canonical_edges.append((edge[0], edge[1]))
            if expected_version is not None:
                _integer(expected_version, 0, _MAX, "expected_version")
                if expected_version != self._version:
                    raise RuntimeError("stale read snapshot version")
            return ReadSnapshot(
                self._version,
                tuple(self._matcher.partner(vertex) for vertex in vertices),
                tuple(self._matcher.graph.has_edge(u, v) for u, v in canonical_edges),
            )

    def history(self, start: int | None = None, limit: int = 256) -> HistoryPage:
        """Return a hash-verified contiguous page from retained full history."""
        _integer(limit, 1, MAX_READS, "limit")
        with self._exclusive():
            first = 1 if start is None else _integer(start, 1, _MAX, "start")
            if first > self._count + 1:
                raise ValueError("history start is beyond next operation")
            boundary = (
                hashlib.sha256(self._metadata.encode()).digest()
                if first == 1
                else self._tail_before(first)
            )
            if first == self._count + 1:
                return HistoryPage(self._count, boundary, (), False)
            rows = (
                self._db()
                .execute(
                    "SELECT sequence,adding,u,v,changed,version,digest FROM operations "
                    "WHERE sequence>=? ORDER BY sequence LIMIT ?",
                    (first, limit + 1),
                )
                .fetchall()
            )
            previous = boundary
            records: list[HistoryRecord] = []
            expected_sequence = first
            previous_version = (
                self._base_version
                if first == 1
                else self._version
                if first > self._count
                else 0
            )
            if first > 1:
                prior = (
                    self._db()
                    .execute(
                        "SELECT version FROM operations WHERE sequence=?", (first - 1,)
                    )
                    .fetchone()
                )
                if prior is None:
                    raise RecoveryError("history page boundary disappeared")
                previous_version = prior[0]
            for seq, adding, left, right, changed, current, digest in rows[:limit]:
                if (
                    seq != expected_sequence
                    or current != previous_version + changed
                    or digest
                    != _digest(
                        previous, seq, adding, left, right, bool(changed), current
                    )
                ):
                    self._failed = True
                    raise RecoveryError("history page failed hash-chain validation")
                records.append(
                    HistoryRecord(
                        seq,
                        "insert" if adding else "delete",
                        left,
                        right,
                        bool(changed),
                        current,
                        digest,
                    )
                )
                previous, previous_version = digest, current
                expected_sequence += 1
            return HistoryPage(self._count, boundary, tuple(records), len(rows) > limit)

    def checkpoint(self) -> dict[str, int]:
        """Bound SQLite WAL maintenance without snapshotting paper algorithm state."""
        with self._exclusive():
            try:
                busy, log_pages, checkpointed = (
                    self._db().execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                )
                return {
                    "busy": busy,
                    "wal_pages": log_pages,
                    "checkpointed_pages": checkpointed,
                }
            except sqlite3.Error as error:
                self._failed = True
                raise RecoveryError("SQLite WAL maintenance failed") from error

    def backup(
        self, path: str | Path, *, max_bytes: int = 64 << 20, timeout: float = 30.0
    ) -> dict[str, int | str]:
        """Publish a bounded, self-contained copy of the committed database."""
        _integer(max_bytes, 1 << 20, 1 << 30, "max_bytes")
        if type(timeout) not in (int, float) or not 0 < timeout <= 3600:
            raise ValueError("timeout must be finite and in (0, 3600]")
        with self._exclusive():
            if not self._audit():
                self._failed = True
                raise UnavailableError("paper matcher audit failed before backup")
            return copy_backup(
                self._db(),
                self._path,
                Path(path).absolute(),
                max_bytes,
                time.monotonic() + timeout,
            )

    def check(self) -> bool:
        """Run a complete explicit graph/matching certificate audit."""
        with self._exclusive():
            try:
                result = self._audit()
            except BaseException:
                self._failed = True
                raise
            if not result:
                self._failed = True
            return result

    def _audit(self) -> bool:
        graph = self._matcher.graph
        graph_check = getattr(graph, "check", None)
        if callable(graph_check) and not graph_check():
            return False
        return self._matcher.audit()

    def _release(self) -> None:
        self._closed = True
        connection, self._connection = self._connection, None
        try:
            if connection is not None:
                connection.close()
        finally:
            if self._lock_fd >= 0:
                os.close(self._lock_fd)
                self._lock_fd = -1

    def close(self) -> None:
        """Release the SQLite connection and exclusive owner lock."""
        if not self._lock.acquire(blocking=False):
            raise BusyError("cannot close an active durable owner")
        try:
            self._release()
        finally:
            self._lock.release()

    def __enter__(self) -> Durable:
        """Return this live owner for use in a with statement."""
        return self

    def __exit__(self, *args: object) -> None:
        """Close the owner when leaving a with statement."""
        self.close()

    def __del__(self) -> None:
        """Best-effort release when explicit close was omitted."""
        try:
            if hasattr(self, "_lock") and not self._closed:
                warnings.warn(
                    "unclosed durable owner; releasing its process lock",
                    ResourceWarning,
                    stacklevel=2,
                )
                self.close()
        except BaseException:
            pass
