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
import time
from abc import ABC, abstractmethod
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

SQLITEFULL = 13
RESOURCE_HISTORY_LIMIT = 1_000_000
RESOURCE_BATCH = 512


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
        if not service.check().result(30):
            raise RuntimeError("resource maintenance graph audit failed")
        return state


class Memory(Pressure):
    """Exercise allocation failure before persistence, without restarting."""

    def apply(self) -> dict[str, object]:
        """Consume owner-thread malloc arenas; reject image allocation atomically."""
        if sys.platform != "linux" or resource.getrlimit(resource.RLIMIT_AS) != (
            512 << 20,
            512 << 20,
        ):
            raise ValueError("memory pressure requires the enforced 512 MiB envelope")
        from axiom.durable import Durable

        with Durable(
            self.volume.path / "graph.db", mode=self.mode, budget=128 << 20
        ) as owner:
            expected = self.audit.verify(owner)
            generation = owner.status()["checkpoint_generation"]
            chunks = []
            while True:
                try:
                    chunks.append(bytearray(1 << 20))
                except MemoryError:
                    break
            allocated = len(chunks) << 20
            # Keep 4 MiB for error handling; both supported images exceed this.
            del chunks[-4:]
            try:
                try:
                    owner.checkpoint()
                except MemoryError:
                    pass
                else:
                    raise RuntimeError("real memory pressure did not reject checkpoint")
            finally:
                chunks.clear()
            if (
                owner.status()["checkpoint_generation"] != generation
                or self.audit.verify(owner) != expected
            ):
                raise RuntimeError("pre-persistence OOM changed acknowledged state")
            owner.checkpoint()
            return {"allocated": allocated, "digest": expected, "verified": True}


class Disk(Pressure):
    """Require fail-stop at the SQLite barrier and exact recovery after ENOSPC."""

    def apply(self) -> dict[str, object]:
        """Qualify physical-full checkpoint and update commits independently."""
        self.volume.inspect(False)
        from axiom.durable import Durable, Request, UnavailableError
        from axiom.service import Service

        database = self.volume.path / "graph.db"
        service = Service(
            database, mode=self.mode, budget=128 << 20, queue_capacity=4096
        )
        try:
            written = self.volume.fill()
            try:
                service.checkpoint().result(30)
            except sqlite3.DatabaseError as error:
                if getattr(error, "sqlite_errorcode", None) != SQLITEFULL:
                    raise
            else:
                raise RuntimeError("full filesystem did not reject checkpoint")
            if service.metrics()["state"] != "failed":
                raise RuntimeError("persistence exhaustion did not fail-stop service")
            try:
                service.partner(0)
            except UnavailableError:
                pass
            else:
                raise RuntimeError("failed persistence owner served a query")
        finally:
            self.volume.release()
            service.close(30)
        with Durable(database, mode=self.mode, budget=128 << 20) as owner:
            digest = self.audit.verify(owner)

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
        return {"written": written, "digest": digest, "update": update}

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

    def run(self) -> dict[str, object]:
        """Enforce worker limits before loading the engine and creating graph state."""
        capacity = self.volume.inspect()
        self.audit.inspect()
        if self.mode not in ("basic", "multilevel"):
            raise ValueError("mode must be 'basic' or 'multilevel'")
        limit = 512 << 20
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        from axiom.durable import Durable, Outcome, Request
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
                crossed_progress_mark = (end - 1) // 100000 > (first - 1) // 100000
                if crossed_progress_mark or end == self.audit.sequence + 1:
                    metrics = service.metrics()
                    print(
                        f"resource updates={end - 1} "
                        f"update_seconds={time.perf_counter() - updates_started:.3f} "
                        f"total_seconds={time.perf_counter() - started:.3f} "
                        f"groups={metrics['groups']} "
                        f"largest_group={metrics['largest_group']}",
                        flush=True,
                    )
            print(
                f"resource phase=service-updates-complete "
                f"seconds={time.perf_counter() - updates_started:.3f}",
                flush=True,
            )
            state = Maintenance(self.audit).verify(service)
            print("resource phase=backup-start", flush=True)
            manifest = service.backup(backup).result(30)
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
        if any(result["digest"] != digest for result in results.values()):
            raise RuntimeError("pressure/source/backup data-flow digests differ")
        return {
            "scope": "installed Linux resource exhaustion and exact recovery; NOT performance/power-loss qualification",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "vertices": self.audit.vertices,
            "paper_mode": self.mode,
            "sequence": self.audit.sequence,
            "cycle": self.audit.vertices if isinstance(self.audit, Cycle) else 0,
            "limits": {
                "address": resource.getrlimit(resource.RLIMIT_AS),
                "filesystem": capacity,
            },
            "peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "working": working,
            "state": state,
            "metrics": metrics,
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
            timeout=300 if isinstance(self.audit, Cycle) else 180,
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
