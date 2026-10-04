"""Class-based installed Linux resource exhaustion and exact recovery.

Requires a fresh dedicated mounted filesystem <=256 MiB. Address-space limits
are not cgroup/page-cache quotas or a production RSS SLA. No power-loss claim.
Only Python-required protocol names use underscore prefixes.
"""

from __future__ import annotations

import argparse
import errno
import gc
import hashlib
import json
import os
import platform
import resource
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

SQLITEFULL = 13
RESOURCE_HISTORY_LIMIT = 1_000_000
RESOURCE_BATCH = 256
RESOURCE_AUDIT_TIMEOUT = 180
QUERY_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500, 1000)


class QueryWorker:
    """Run one bounded partner read at a time and retain fixed-size metrics."""

    def __init__(self, service: Any, vertices: int, timeout: float = 30):
        """Bind the installed service and bounded vertex domain for the worker."""
        self.service = service
        self.vertices = vertices
        self.timeout = timeout
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.run, name="partner-query-load")
        self.error: BaseException | None = None
        self.count = 0
        self.total = 0
        self.version = 0
        self.minimum: int | None = None
        self.maximum = 0
        self.buckets = [0] * (len(QUERY_BUCKETS) + 1)

    def start(self) -> None:
        """Start the background load before durable updates begin."""
        self.thread.start()

    def run(self) -> None:
        """Issue sequentially numbered partner reads until asked to stop."""
        try:
            while not self.stopping.is_set():
                vertex = self.count % self.vertices
                started = time.perf_counter_ns()
                read = self.service.partner(vertex).result(self.timeout)
                elapsed = time.perf_counter_ns() - started
                if (
                    type(read) is not tuple
                    or len(read) != 2
                    or type(read[0]) is not int
                    or read[0] < self.version
                    or (
                        read[1] is not None
                        and (
                            type(read[1]) is not int or not 0 <= read[1] < self.vertices
                        )
                    )
                ):
                    raise RuntimeError("partner query returned an invalid vertex")
                self.version = read[0]
                self.count += 1
                self.total += elapsed
                self.minimum = (
                    elapsed if self.minimum is None else min(self.minimum, elapsed)
                )
                self.maximum = max(self.maximum, elapsed)
                milliseconds = elapsed / 1_000_000
                bucket = next(
                    (
                        index
                        for index, limit in enumerate(QUERY_BUCKETS)
                        if milliseconds <= limit
                    ),
                    len(QUERY_BUCKETS),
                )
                self.buckets[bucket] += 1
        except BaseException as error:
            self.error = error
            self.stopping.set()

    def check(self) -> None:
        """Fail promptly if the query worker has encountered an error."""
        if self.error is not None:
            raise RuntimeError("partner-query load failed") from self.error

    def stop(self) -> dict[str, object]:
        """Stop and drain the one outstanding read, then return bounded metrics."""
        self.stopping.set()
        self.thread.join(self.timeout + 5)
        if self.thread.is_alive():
            raise RuntimeError("partner-query worker did not stop")
        self.check()
        if self.count == 0:
            raise RuntimeError("partner-query worker completed no reads")
        minimum = self.minimum if self.minimum is not None else 0
        return {
            "count": self.count,
            "latency_ms": {
                "minimum": minimum / 1_000_000,
                "mean": self.total / self.count / 1_000_000,
                "maximum": self.maximum / 1_000_000,
                "p50_upper_bound": self.percentile(0.50),
                "p95_upper_bound": self.percentile(0.95),
                "p99_upper_bound": self.percentile(0.99),
                "p999_upper_bound": self.percentile(0.999),
                "buckets_ms_upper_bounds": (*QUERY_BUCKETS, None),
                "bucket_counts": tuple(self.buckets),
            },
        }

    def percentile(self, quantile: float) -> float | None:
        """Return the fixed-histogram upper bound for a requested quantile."""
        target = max(1, int(self.count * quantile + 0.999999))
        observed = 0
        for index, count in enumerate(self.buckets):
            observed += count
            if observed >= target:
                return QUERY_BUCKETS[index] if index < len(QUERY_BUCKETS) else None
        return None


@dataclass
class Volume:
    """Own one dedicated small filesystem and its exclusive pressure file."""

    path: Path
    ballast: Path | None = None

    def inspect(self, fresh: bool = True) -> int:
        """Reject symlinks, host directories, large and previously used volumes."""
        if sys.platform != "linux":
            raise ValueError("resource envelope requires Linux")
        if (
            self.path.is_symlink()
            or not self.path.is_dir()
            or self.path.resolve() != self.path.absolute()
        ):
            raise ValueError("require an explicit non-symlink mount path")
        if self.path.stat().st_dev == self.path.parent.stat().st_dev:
            raise ValueError("require a dedicated mounted filesystem")
        space = os.statvfs(self.path)
        capacity = space.f_blocks * space.f_frsize
        if not 64 << 20 <= capacity <= 256 << 20:
            raise ValueError("require a filesystem between 64 and 256 MiB")
        if fresh and any(entry.name != "lost+found" for entry in self.path.iterdir()):
            raise ValueError("resource volume must be fresh")
        return capacity

    def fill(self) -> int:
        """Count bounded writes until genuine ENOSPC; never overwrite a file."""
        self.inspect(False)
        written = 0
        target = self.path / "ballast"
        with target.open("xb", buffering=0) as output:
            self.ballast = target
            block = bytes(1 << 16)
            while True:
                try:
                    count = output.write(block)
                except OSError as error:
                    if error.errno != errno.ENOSPC:
                        raise
                    break
                if count is None or count == 0:
                    raise RuntimeError("ballast write made no progress")
                written += count
            try:
                os.fsync(output.fileno())
            except OSError as error:
                if error.errno != errno.ENOSPC:
                    raise
        return written

    def release(self) -> None:
        """Remove only owned ballast; all graph/retry/backup files remain."""
        if self.ballast is not None:
            self.ballast.unlink(missing_ok=True)
            self.ballast = None


@dataclass
class Audit:
    """Independent exact reference for balanced churn on the degree-four ring."""

    vertices: int
    sequence: int = 40000
    partner_reference: tuple[int, ...] | None = None

    def inspect(self) -> None:
        """Reject an invalid reference before it can drive mutation or verification."""
        if (
            type(self.vertices) is not int
            or not 8 <= self.vertices <= 1000000
            or self.vertices % 2
            or type(self.sequence) is not int
            or not 2 <= self.sequence <= 40000
            or self.sequence % 2
        ):
            raise ValueError("require bounded even vertices and balanced even churn")
        if self.partner_reference is not None and (
            type(self.partner_reference) is not tuple
            or len(self.partner_reference) != self.vertices
            or any(
                type(partner) is not int or not 0 <= partner < self.vertices
                for partner in self.partner_reference
            )
        ):
            raise ValueError("partner reference must cover the vertex universe")

    def verify(
        self, owner: Any, sequence: int | None = None, retry: bool = True
    ) -> str:
        """Check exact topology, proper/maximal matching and an optional retry."""
        from axiom.durable import MAX_READS, Outcome, Request

        started = time.perf_counter()
        if self.vertices >= 100000:
            print(
                f"resource audit=start sequence={sequence or self.sequence}",
                flush=True,
            )
        self.inspect()
        state = owner.status()
        expected_sequence = self.sequence if sequence is None else sequence
        if type(expected_sequence) is not int or expected_sequence not in (
            self.sequence,
            self.sequence + 1,
        ):
            raise ValueError("resource verification sequence is outside one probe")
        if retry and expected_sequence != self.sequence:
            raise ValueError("probe verification cannot replay the baseline request")
        if (
            state["sequence"] != expected_sequence
            or state["version"] != self.sequence + 1
            or state["edges"] != 2 * self.vertices
            or state["matching"] != self.vertices // 2
            or not owner.check()
        ):
            raise RuntimeError("resource recovery control/certificate disagrees")
        version = self.sequence + 1
        digest = hashlib.sha256()
        partners = array("i", [-1]) * self.vertices
        batch_size = MAX_READS // 4
        for start in range(0, self.vertices, batch_size):
            stop = min(self.vertices, start + batch_size)
            snapshot = owner.read_snapshot(
                tuple(range(start, stop)), (), expected_version=version
            )
            if snapshot.version != version or len(snapshot.partners) != stop - start:
                raise RuntimeError("resource recovery partner version differs")
            for offset, partner in enumerate(snapshot.partners):
                if partner is not None and (
                    type(partner) is not int or not 0 <= partner < self.vertices
                ):
                    raise RuntimeError("resource recovery matching is not proper")
                partners[start + offset] = -1 if partner is None else partner
        matched = 0
        for vertex, partner in enumerate(partners):
            if (
                self.partner_reference is not None
                and (None if partner < 0 else partner) != self.partner_reference[vertex]
            ):
                raise RuntimeError("resource recovery exact matching differs")
            if partner >= 0:
                if partner == vertex or partners[partner] != vertex:
                    raise RuntimeError("resource recovery matching is not proper")
                matched += vertex < partner
            digest.update(
                (partner if partner >= 0 else 0xFFFFFFFF).to_bytes(4, "little")
            )
        if matched != self.vertices // 2:
            raise RuntimeError("resource recovery perfect matching differs")
        for start in range(0, self.vertices, batch_size):
            stop = min(self.vertices, start + batch_size)
            edges = []
            for vertex in range(start, stop):
                partner = partners[vertex]
                if partner >= 0:
                    edges.append((vertex, partner))
                for offset in (1, 2):
                    neighbor = (vertex + offset) % self.vertices
                    edges.append((vertex, neighbor))
            snapshot = owner.read_snapshot((), tuple(edges), expected_version=version)
            if snapshot.version != version or len(snapshot.has_edges) != len(edges):
                raise RuntimeError("resource recovery topology version differs")
            edge_index = 0
            for vertex in range(start, stop):
                partner = partners[vertex]
                if partner >= 0:
                    if not snapshot.has_edges[edge_index]:
                        raise RuntimeError("resource recovery matching is not proper")
                    edge_index += 1
                for offset in (1, 2):
                    neighbor = (vertex + offset) % self.vertices
                    if not snapshot.has_edges[edge_index]:
                        raise RuntimeError("resource recovery ring topology differs")
                    edge_index += 1
                    if partners[vertex] < 0 and partners[neighbor] < 0:
                        raise RuntimeError("resource recovery matching is not maximal")
        if retry:
            operation, left, right = self.operation(self.sequence)
            request = Request(self.sequence, operation, left, right)
            expected = (Outcome(self.sequence, True, self.sequence + 1),)
            if owner.apply([request]) != expected:
                raise RuntimeError("resource recovery original retry differs")
            conflicting_operation: Literal["insert", "delete"] = (
                "delete" if operation == "insert" else "insert"
            )
            try:
                owner.apply(
                    [Request(self.sequence, conflicting_operation, left, right)]
                )
            except ValueError as error:
                if "retry payload differs" not in str(error):
                    raise
            else:
                raise RuntimeError("conflicting retry payload was accepted")
        if self.vertices >= 100000:
            print(
                f"resource audit=complete sequence={expected_sequence} "
                f"seconds={time.perf_counter() - started:.3f}",
                flush=True,
            )
        return digest.hexdigest()

    def operation(self, sequence: int) -> tuple[Literal["insert", "delete"], int, int]:
        """Describe a real balanced edit after reference validation."""
        if type(sequence) is not int or not 1 <= sequence <= self.sequence:
            raise ValueError("operation sequence outside resource reference")
        return "delete" if sequence % 2 else "insert", 0, 1


class Cycle(Audit):
    """Grow/drain every antipodal chord, then run the balanced pressure prefix."""

    def inspect(self) -> None:
        """Require a complete even cycle and an optional bounded balanced tail."""
        if (
            type(self.vertices) is not int
            or not 8 <= self.vertices <= 1000000
            or self.vertices % 2
            or type(self.sequence) is not int
            or not 0 <= self.sequence - self.vertices <= 40000
            or (self.sequence != self.vertices and self.sequence - self.vertices < 2)
            or self.sequence % 2
        ):
            raise ValueError(
                "require a complete growth/drain cycle and optional balanced tail"
            )

    def operation(self, sequence: int) -> tuple[Literal["insert", "delete"], int, int]:
        """Every admitted chord edit changes density; tail retries retain identity."""
        if type(sequence) is not int or not 1 <= sequence <= self.sequence:
            raise ValueError("operation sequence outside resource reference")
        if sequence > self.vertices:
            return super().operation(sequence)
        half = self.vertices // 2
        vertex = (sequence - 1) % half
        return "insert" if sequence <= half else "delete", vertex, vertex + half


@dataclass
class Pressure(ABC):
    """Polymorphic contract for actual exhaustion and exact recovery drills."""

    volume: Volume
    audit: Audit
    mode: str = "basic"

    @abstractmethod
    def apply(self) -> dict[str, object]:
        """Exhaust a resource and certify resulting owner/recovery behavior."""
        raise NotImplementedError


@dataclass
class Maintenance:
    """Certify committed history, SQLite checkpoint state and paper invariants."""

    audit: Audit

    def verify(self, service: Any) -> dict[str, int | str]:
        """Require the exact acknowledged prefix and a completed WAL checkpoint."""
        state = cast(dict[str, int | str], service.status().result(30))
        checkpoint = cast(dict[str, int], service.checkpoint().result(30))
        expected = {
            "sequence": self.audit.sequence,
            "history_operations": self.audit.sequence,
            "version": self.audit.sequence + 1,
            "vertices": self.audit.vertices,
            "edges": 2 * self.audit.vertices,
            "matching": self.audit.vertices // 2,
            "max_operations": RESOURCE_HISTORY_LIMIT,
        }
        if any(
            type(state.get(key)) is not int or state[key] != value
            for key, value in expected.items()
        ):
            raise RuntimeError(
                "resource maintenance status differs from acknowledged graph"
            )
        busy = checkpoint.get("busy")
        wal_pages = checkpoint.get("wal_pages")
        checkpointed_pages = checkpoint.get("checkpointed_pages")
        if (
            type(busy) is not int
            or type(wal_pages) is not int
            or type(checkpointed_pages) is not int
            or busy != 0
            or wal_pages < 0
            or checkpointed_pages != wal_pages
        ):
            raise RuntimeError("resource maintenance WAL checkpoint is incomplete")
        if not service.check().result(RESOURCE_AUDIT_TIMEOUT):
            raise RuntimeError("resource maintenance graph audit failed")
        return state


class Memory(Pressure):
    """Exercise durable update failure under allocator pressure and recover."""

    @staticmethod
    def requests(request: Any, vertices: int) -> tuple[Any, ...]:
        """Create a bounded deterministic group of absent out-of-ring edges."""
        count = 4096
        if type(vertices) is not int or vertices < 4 * count + 2:
            raise ValueError("memory workload requires at least 16,386 vertices")
        return tuple(
            request(sequence + 3, "insert", 4 * sequence + 2, 4 * sequence + 5)
            for sequence in range(count)
        )

    def apply(self) -> dict[str, object]:
        """Reject a large durable update atomically under real allocator pressure."""
        if sys.platform != "linux" or resource.getrlimit(resource.RLIMIT_AS) != (
            512 << 20,
            512 << 20,
        ):
            raise ValueError("memory pressure requires the enforced 512 MiB envelope")
        from axiom.capacity import JournalCapacityError
        from axiom.durable import Durable, Request, UnavailableError

        pressure_audit = Audit(self.audit.vertices, 2)
        pressure_database = self.volume.path / "memory-update.db"
        with Durable(
            pressure_database,
            n=self.audit.vertices,
            mode=self.mode,
            budget=128 << 20,
            max_batch=4096,
            max_operations=8192,
        ) as owner:
            owner.apply([Request(1, "delete", 0, 1), Request(2, "insert", 0, 1)])
            baseline = pressure_audit.verify(owner)
            before = owner.status()
            requests = self.requests(Request, self.audit.vertices)
            chunks = []
            while True:
                try:
                    chunks.append(bytearray(1 << 16))
                except MemoryError:
                    break
            allocated = len(chunks) << 16
            # Keep only one 64 KiB chunk free so the varied update must allocate
            # its journal, graph deltas, and persistence rows under real pressure.
            del chunks[-1:]
            failure = ""
            try:
                try:
                    owner.apply(requests)
                except JournalCapacityError as error:
                    raise RuntimeError(
                        "bounded Matcher journal capacity was not the memory limit"
                    ) from error
                except UnavailableError as error:
                    failure = type(error).__name__
                except MemoryError:
                    failure = "MemoryError"
                else:
                    raise RuntimeError(
                        "real memory pressure did not reject the durable update group"
                    )
            finally:
                chunks.clear()
        # A failed reconstruction can leave cyclic partially-built Matcher
        # state unreachable but not yet reclaimed. Release the owner and collect
        # it before reopening under the same process address-space ceiling.
        del owner
        gc.collect()
        with Durable(pressure_database, mode=self.mode, budget=128 << 20) as recovered:
            if recovered.status() != before:
                raise RuntimeError("pre-persistence OOM changed durable status")
            if pressure_audit.verify(recovered) != baseline:
                raise RuntimeError("pre-persistence OOM changed exact matching state")
        return {
            "allocated": allocated,
            "failure": failure,
            "failed_group": len(requests),
            "pressure_digest": baseline,
            "rollback_verified": True,
            "verified": True,
        }


class Disk(Pressure):
    """Require fail-stop at the SQLite barrier and exact recovery after ENOSPC."""

    def apply(self) -> dict[str, object]:
        """Qualify physical-full WAL checkpoint and update commits independently."""
        self.volume.inspect(False)
        from axiom.durable import Durable, RecoveryError, Request, UnavailableError
        from axiom.service import Service

        checkpoint_audit = Audit(256, 256)
        checkpoint_database = self.volume.path / "checkpoint-full.db"
        service = Service(
            checkpoint_database,
            n=checkpoint_audit.vertices,
            mode=self.mode,
            budget=128 << 20,
            queue_capacity=4096,
            max_batch=256,
            max_operations=8192,
        )
        try:
            requests = tuple(
                Request(sequence, "delete" if sequence % 2 else "insert", 0, 1)
                for sequence in range(1, 257)
            )
            outcomes = service.submit_batch(requests).result(30)
            if len(outcomes) != len(requests) or not all(
                outcome.changed for outcome in outcomes
            ):
                raise RuntimeError("checkpoint pressure setup did not change edges")
            wal = checkpoint_database.with_name(checkpoint_database.name + "-wal")
            with checkpoint_database.open("rb") as source:
                header = source.read(100)
            if header[:16] != b"SQLite format 3\x00":
                raise RuntimeError("checkpoint pressure database header is invalid")
            page_size = int.from_bytes(header[16:18], "big")
            page_size = 65536 if page_size == 1 else page_size
            database_pages = checkpoint_database.stat().st_size // page_size
            wal_size = wal.stat().st_size if wal.is_file() else 0
            frame_size = page_size + 24
            if wal_size <= 32 or (wal_size - 32) % frame_size:
                raise RuntimeError("checkpoint pressure setup did not retain WAL pages")
            transaction_pages = 0
            growth_commits = []
            with wal.open("rb") as log:
                log.seek(32)
                while frame := log.read(frame_size):
                    if len(frame) != frame_size:
                        raise RuntimeError("checkpoint pressure WAL frame is truncated")
                    page = int.from_bytes(frame[:4], "big")
                    committed_pages = int.from_bytes(frame[4:8], "big")
                    transaction_pages = max(transaction_pages, page)
                    if committed_pages:
                        growth_commits.append(
                            committed_pages > database_pages
                            and transaction_pages > database_pages
                        )
                        transaction_pages = 0
            if not growth_commits or not growth_commits[-1]:
                raise RuntimeError(
                    "checkpoint pressure WAL lacks a committed database-growth frame"
                )
            with sqlite3.connect(checkpoint_database) as verifier:
                integrity = verifier.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise RuntimeError("checkpoint pressure WAL failed SQLite integrity")
            written = self.volume.fill()
            checkpoint_failed = False
            try:
                checkpoint = service.checkpoint().result(30)
            except RecoveryError as error:
                cause = error.__cause__
                if (
                    not isinstance(cause, sqlite3.Error)
                    or getattr(cause, "sqlite_errorcode", None) != SQLITEFULL
                ):
                    raise
                checkpoint_failed = True
            if checkpoint_failed:
                if service.metrics()["state"] != "failed":
                    raise RuntimeError(
                        "failed checkpoint did not fail-stop the service"
                    )
                try:
                    service.partner(0).result(5)
                except UnavailableError:
                    pass
                else:
                    raise RuntimeError("failed persistence owner served a query")
            else:
                if (
                    type(checkpoint) is not dict
                    or set(checkpoint) != {"busy", "wal_pages", "checkpointed_pages"}
                    or any(type(value) is not int for value in checkpoint.values())
                    or checkpoint["busy"] not in (0, 1)
                    or checkpoint["wal_pages"] < 0
                    or checkpoint["checkpointed_pages"] < 0
                    or checkpoint["checkpointed_pages"] > checkpoint["wal_pages"]
                ):
                    raise RuntimeError("full-volume checkpoint result is invalid")
                if service.metrics()["state"] != "open":
                    raise RuntimeError(
                        "successful checkpoint changed service availability"
                    )
                status = service.status().result(5)
                status_version = status.get("version")
                if type(status_version) is not int:
                    raise RuntimeError("service returned an invalid logical version")
                live_partners = [-1] * checkpoint_audit.vertices
                page_start = 0
                matching_count = 0
                while True:
                    version, edges, following = service.page(
                        page_start, 256, status_version
                    ).result(5)
                    if version != status_version:
                        raise RuntimeError(
                            "successful checkpoint changed matching-page version"
                        )
                    for left, right in edges:
                        if (
                            not 0 <= left < right < checkpoint_audit.vertices
                            or live_partners[left] != -1
                            or live_partners[right] != -1
                        ):
                            raise RuntimeError(
                                "successful checkpoint returned an invalid matching"
                            )
                        live_partners[left], live_partners[right] = right, left
                        matching_count += 1
                    if following is None:
                        break
                    if type(following) is not int or following <= page_start:
                        raise RuntimeError(
                            "successful checkpoint matching cursor did not advance"
                        )
                    page_start = following
                if matching_count != checkpoint_audit.vertices // 2:
                    raise RuntimeError(
                        "successful checkpoint returned an incomplete matching page"
                    )
                partner = live_partners[0]
                first_read = service.partner(0).result(5)
                second_read = (
                    service.partner(partner).result(5) if partner >= 0 else None
                )
                if (
                    partner < 0
                    or first_read != (status_version, partner)
                    or second_read != (status_version, 0)
                ):
                    raise RuntimeError("successful checkpoint corrupted matching reads")
        finally:
            self.volume.release()
            service.close(30)
        with Durable(checkpoint_database, mode=self.mode, budget=128 << 20) as owner:
            checkpoint_digest = checkpoint_audit.verify(owner)
            history = owner.history(1, 256)
            if history.latest_sequence != 256 or history.has_more:
                raise RuntimeError("checkpoint recovery history boundary differs")
            if len(history.records) != 256 or any(
                record.sequence != request.sequence
                or record.operation != request.operation
                or record.u != request.u
                or record.v != request.v
                or not record.changed
                or record.version != request.sequence + 1
                for request, record in zip(requests, history.records, strict=True)
            ):
                raise RuntimeError("checkpoint recovery history is not exact")

        update_audit = Audit(self.audit.vertices, 2)
        update_database = self.volume.path / "disk-update.db"
        with Durable(
            update_database, n=self.audit.vertices, mode=self.mode, budget=128 << 20
        ) as owner:
            owner.apply(
                [
                    Request(1, "delete", 0, 1),
                    Request(2, "insert", 0, 1),
                ]
            )
            update_digest = update_audit.verify(owner)

        update = self.update(update_database, update_digest, update_audit)
        return {
            "digest": update["digest"],
            "checkpoint": {
                "written": written,
                "failed": checkpoint_failed,
                "result": checkpoint if not checkpoint_failed else None,
                "complete": (
                    not checkpoint_failed
                    and checkpoint["busy"] == 0
                    and checkpoint["checkpointed_pages"] == checkpoint["wal_pages"]
                ),
                "digest": checkpoint_digest,
                "verified": True,
            },
            "update": update,
        }

    def update(
        self, database: Path, digest: str, audit: Audit | None = None
    ) -> dict[str, object]:
        """Retry and certify one full-volume durable no-op across reopen."""
        from axiom.durable import Durable, Outcome, Request, UnavailableError
        from axiom.service import Service

        reference = self.audit if audit is None else audit
        request = Request(reference.sequence + 1, "insert", 0, 1)
        service = Service(
            database, mode=self.mode, budget=128 << 20, queue_capacity=4096
        )
        try:
            update_written = self.volume.fill()
            try:
                result = service.submit(request).result(30)
            except sqlite3.DatabaseError as error:
                if getattr(error, "sqlite_errorcode", None) != SQLITEFULL:
                    raise
                if service.metrics()["state"] != "failed":
                    raise RuntimeError("full update commit did not fail-stop service")
                for read in (
                    lambda: service.partner(0),
                    lambda: service.has_edge(0, 1),
                ):
                    try:
                        read().result(5)
                    except UnavailableError:
                        continue
                    raise RuntimeError("uncertain failed commit served a read")
            else:
                if result != Outcome(request.sequence, False, reference.sequence + 1):
                    raise RuntimeError("full-volume update acknowledgment differs")
        finally:
            self.volume.release()
            service.close(30)

        with Durable(database, mode=self.mode, budget=128 << 20) as owner:
            state = owner.status()
            if state["sequence"] not in (reference.sequence, request.sequence):
                raise RuntimeError("full-volume update recovered an unknown prefix")
            outcome = owner.apply([request])
            expected = Outcome(request.sequence, False, reference.sequence + 1)
            if outcome != (expected,):
                raise RuntimeError("full-volume original update retry differs")
            recovered = reference.verify(owner, sequence=request.sequence, retry=False)
            if recovered != digest:
                raise RuntimeError("full-volume update changed exact matching")
        with Durable(database, mode=self.mode, budget=128 << 20) as owner:
            if (
                reference.verify(owner, sequence=request.sequence, retry=False)
                != digest
            ):
                raise RuntimeError("full-volume retry prefix changed after reopen")
        return {
            "update_written": update_written,
            "update_sequence": request.sequence,
            "update_outcome": "acknowledged-or-retried-exactly",
            "digest": digest,
            "verified": True,
        }


@dataclass
class Envelope:
    """Coordinate bounded installed-service, pressure and backup data-flow drills."""

    volume: Volume
    audit: Audit
    mode: str = "basic"

    def update(self, service: Any) -> tuple[float, dict[str, object]]:
        """Qualify durable updates while a bounded partner-read thread is active."""
        from axiom.durable import Outcome, Request

        worker = QueryWorker(service, self.audit.vertices)
        worker.start()
        updates_started = time.perf_counter()
        update_seconds = 0.0
        try:
            for first in range(1, self.audit.sequence + 1, RESOURCE_BATCH):
                end = min(first + RESOURCE_BATCH, self.audit.sequence + 1)
                receipts = [
                    service.submit(Request(seq, *self.audit.operation(seq)))
                    for seq in range(first, end)
                ]
                for seq, receipt in zip(range(first, end), receipts, strict=True):
                    if receipt.result(30) != Outcome(seq, True, seq + 1):
                        raise RuntimeError(
                            "resource envelope acknowledged a wrong update"
                        )
                worker.check()
                crossed_progress_mark = (end - 1) // 100000 > (first - 1) // 100000
                if crossed_progress_mark or end == self.audit.sequence + 1:
                    metrics = service.metrics()
                    print(
                        f"resource updates={end - 1} "
                        f"update_seconds={time.perf_counter() - updates_started:.3f} "
                        f"query_count={worker.count} "
                        f"groups={metrics['groups']} "
                        f"largest_group={metrics['largest_group']}",
                        flush=True,
                    )
            update_seconds = time.perf_counter() - updates_started
        finally:
            queries = worker.stop()
        return update_seconds, queries

    def run(self) -> dict[str, object]:
        """Enforce worker limits before loading the engine and creating graph state."""
        capacity = self.volume.inspect()
        self.audit.inspect()
        if self.mode not in ("basic", "multilevel"):
            raise ValueError("mode must be 'basic' or 'multilevel'")
        limit = 512 << 20
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        from axiom.durable import Durable
        from axiom.service import Service

        database = self.volume.path / "graph.db"
        backup = self.volume.path / "backup.db"
        started = time.perf_counter()
        print("resource phase=service-updates-start", flush=True)
        with Service(
            database,
            n=self.audit.vertices,
            mode=self.mode,
            budget=128 << 20,
            max_batch=RESOURCE_BATCH,
            queue_capacity=4096,
        ) as service:
            updates_started = time.perf_counter()
            print(
                f"resource phase=service-ready "
                f"initialization_seconds={updates_started - started:.3f}",
                flush=True,
            )
            update_seconds, queries = self.update(service)
            print(
                f"resource phase=service-updates-complete "
                f"seconds={update_seconds} query_count={queries['count']}",
                flush=True,
            )
            state = Maintenance(self.audit).verify(service)
            print("resource phase=backup-start", flush=True)
            manifest = service.backup(backup, timeout=180).result(190)
            print(
                f"resource phase=backup-complete "
                f"seconds={time.perf_counter() - started:.3f}",
                flush=True,
            )
            metrics = service.metrics()

        # Service.close drains work and closes the Durable owner, but the
        # Service object still retains its Matcher until it is released. The
        # pressure phases reopen/replay the graph and must not overlap that
        # million-vertex in-memory state.
        del service
        gc.collect()

        working = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        results = {}
        for pressure in (
            Memory(self.volume, self.audit, self.mode),
            Disk(self.volume, self.audit, self.mode),
        ):
            print(f"resource phase={type(pressure).__name__}-start", flush=True)
            results[type(pressure).__name__] = pressure.apply()
            print(
                f"resource phase={type(pressure).__name__}-complete "
                f"seconds={time.perf_counter() - started:.3f}",
                flush=True,
            )
        restored = self.volume.path / "restored.db"
        shutil.copyfile(backup, restored)  # The backup master stays immutable.
        with Durable(restored, mode=self.mode, budget=128 << 20) as owner:
            digest = self.audit.verify(owner)
        if any(
            "digest" in result and result["digest"] != digest
            for result in results.values()
        ):
            raise RuntimeError("pressure/source/backup data-flow digests differ")
        return {
            "scope": "installed Linux resource exhaustion and exact recovery; NOT performance/power-loss qualification",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "vertices": self.audit.vertices,
            "paper_mode": self.mode,
            "sequence": self.audit.sequence,
            "update_seconds": update_seconds,
            "updates_per_second": self.audit.sequence / update_seconds,
            "cycle": self.audit.vertices if isinstance(self.audit, Cycle) else 0,
            "limits": {
                "address": resource.getrlimit(resource.RLIMIT_AS),
                "filesystem": capacity,
            },
            "peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "working": working,
            "state": state,
            "metrics": metrics,
            "partner_queries": queries,
            "backup": manifest["bytes"],
            "digest": digest,
            "pressure": results,
            "verified": True,
        }

    def launch(self) -> None:
        """Isolate irreversible address-space limits from the caller, with a deadline."""
        self.volume.inspect()
        self.audit.inspect()
        if self.mode not in ("basic", "multilevel"):
            raise ValueError("mode must be 'basic' or 'multilevel'")
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "--directory",
            str(self.volume.path),
            "--vertices",
            str(self.audit.vertices),
            "--mode",
            self.mode,
            "--worker",
        ]
        if isinstance(self.audit, Cycle):
            command.append("--growth")
        subprocess.run(
            command,
            check=True,
            timeout=450 if isinstance(self.audit, Cycle) else 180,
        )

    @classmethod
    def cli(cls) -> None:
        """Validate the supported envelope and choose launcher/worker behavior."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--directory", type=Path, required=True)
        parser.add_argument("--vertices", type=int, default=1000000)
        parser.add_argument(
            "--growth", action="store_true", help="include a full growth/drain cycle"
        )
        parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
        parser.add_argument("--mode", choices=("basic", "multilevel"), default="basic")
        args = parser.parse_args()
        if args.vertices not in (256000, 1000000):
            parser.error("supported pressure stages are 256000 and 1000000 vertices")
        audit = (
            Cycle(
                args.vertices,
                min(args.vertices + 40000, RESOURCE_HISTORY_LIMIT),
            )
            if args.growth
            else Audit(args.vertices)
        )
        envelope = cls(Volume(args.directory), audit, args.mode)
        if args.worker:
            print(json.dumps(envelope.run(), indent=2))
        else:
            envelope.launch()


if __name__ == "__main__":
    Envelope.cli()
