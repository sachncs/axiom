"""Class-based installed Linux resource exhaustion and exact recovery.

Requires a fresh dedicated mounted filesystem <=256 MiB. Address-space limits
are not cgroup/page-cache quotas or a production RSS SLA. No power-loss claim.
Only Python-required protocol names use underscore prefixes.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import platform
import resource
import shutil
import sqlite3
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


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

    def verify(self, owner) -> str:
        """Check every expected edge/partner, version, retry and native certificate."""
        from axiom.durable import Outcome, Request

        self.inspect()
        state = owner.status()
        if (
            state["sequence"] != self.sequence
            or state["version"] != self.sequence + 1
            or state["edges"] != 2 * self.vertices
            or state["matching"] != self.vertices // 2
            or not owner.check()
        ):
            raise RuntimeError("resource recovery control/certificate disagrees")
        digest = hashlib.sha256()
        for vertex in range(self.vertices):
            if owner.partner(vertex) != (self.sequence + 1, vertex ^ 1):
                raise RuntimeError("resource recovery exact matching differs")
            for offset in (1, 2):
                if owner.has_edge(vertex, (vertex + offset) % self.vertices) != (
                    self.sequence + 1,
                    True,
                ):
                    raise RuntimeError("resource recovery ring topology differs")
            digest.update((vertex ^ 1).to_bytes(4, "little"))
        request = Request(self.sequence, "insert", 0, 1)
        if owner.apply([request]) != (Outcome(self.sequence, True, self.sequence + 1),):
            raise RuntimeError("resource recovery original retry differs")
        return digest.hexdigest()


@dataclass
class Pressure(ABC):
    """Polymorphic contract for actual exhaustion and exact recovery drills."""

    volume: Volume
    audit: Audit

    @abstractmethod
    def apply(self) -> dict:
        """Exhaust a resource and certify resulting owner/recovery behavior."""
        raise NotImplementedError


class Memory(Pressure):
    """Exercise allocation failure before persistence, without restarting."""

    def apply(self) -> dict:
        """Consume owner-thread malloc arenas; reject image allocation atomically."""
        if sys.platform != "linux" or resource.getrlimit(resource.RLIMIT_AS) != (
            512 << 20,
            512 << 20,
        ):
            raise ValueError("memory pressure requires the enforced 512 MiB envelope")
        from axiom.durable import Durable

        with Durable(self.volume.path / "graph.db", budget=128 << 20) as owner:
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

    def apply(self) -> dict:
        """Keep disk full through failed maintenance and availability checks."""
        self.volume.inspect(False)
        from axiom.durable import Durable, UnavailableError
        from axiom.service import Service

        database = self.volume.path / "graph.db"
        service = Service(database, budget=128 << 20, queue_capacity=4096)
        try:
            written = self.volume.fill()
            try:
                service.checkpoint().result(30)
            except sqlite3.DatabaseError as error:
                if getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_FULL:
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
        with Durable(database, budget=128 << 20) as owner:
            digest = self.audit.verify(owner)
        return {"written": written, "digest": digest, "verified": True}


@dataclass
class Envelope:
    """Coordinate bounded installed-service, pressure and backup data-flow drills."""

    volume: Volume
    audit: Audit

    def run(self) -> dict:
        """Enforce worker limits before loading the engine and creating graph state."""
        capacity = self.volume.inspect()
        self.audit.inspect()
        limit = 512 << 20
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        from axiom.durable import Durable, Outcome, Request
        from axiom.service import Service

        database = self.volume.path / "graph.db"
        backup = self.volume.path / "backup.db"
        with Service(
            database, n=self.audit.vertices, budget=128 << 20, queue_capacity=4096
        ) as service:
            for first in range(1, self.audit.sequence + 1, 256):
                end = min(first + 256, self.audit.sequence + 1)
                receipts = [
                    service.submit(
                        Request(seq, "delete" if seq % 2 else "insert", 0, 1)
                    )
                    for seq in range(first, end)
                ]
                for seq, receipt in zip(range(first, end), receipts, strict=True):
                    if receipt.result(30) != Outcome(seq, True, seq + 1):
                        raise RuntimeError(
                            "resource envelope acknowledged a wrong update"
                        )
            state = service.status().result(30)
            if state["checkpoint_generation"] < 1 or not service.check().result(30):
                raise RuntimeError("resource envelope omitted maintenance/audit")
            manifest = service.backup(backup).result(30)
            metrics = service.metrics()

        results = {}
        for pressure in (
            Memory(self.volume, self.audit),
            Disk(self.volume, self.audit),
        ):
            results[type(pressure).__name__] = pressure.apply()
        restored = self.volume.path / "restored.db"
        shutil.copyfile(backup, restored)  # The backup master stays immutable.
        with Durable(restored, budget=128 << 20) as owner:
            digest = self.audit.verify(owner)
        if any(result["digest"] != digest for result in results.values()):
            raise RuntimeError("pressure/source/backup data-flow digests differ")
        return {
            "scope": "installed Linux resource exhaustion and exact recovery; NOT performance/power-loss qualification",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "vertices": self.audit.vertices,
            "sequence": self.audit.sequence,
            "limits": {
                "address": resource.getrlimit(resource.RLIMIT_AS),
                "filesystem": capacity,
            },
            "peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
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
        subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--directory",
                str(self.volume.path),
                "--vertices",
                str(self.audit.vertices),
                "--worker",
            ],
            check=True,
            timeout=180,
        )

    @classmethod
    def cli(cls) -> None:
        """Validate the supported envelope and choose launcher/worker behavior."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--directory", type=Path, required=True)
        parser.add_argument("--vertices", type=int, default=1000000)
        parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
        args = parser.parse_args()
        if args.vertices not in (256000, 1000000):
            parser.error("supported pressure stages are 256000 and 1000000 vertices")
        envelope = cls(Volume(args.directory), Audit(args.vertices))
        if args.worker:
            print(json.dumps(envelope.run(), indent=2))
        else:
            envelope.launch()


if __name__ == "__main__":
    Envelope.cli()
