"""Measure a bounded owner backup and independent disaster restore.

Uses real ring/chord churn, native checkpoints plus an uncheckpointed tail,
then checks every expected edge and exact matching partners after restore.
This is not a power-cut or concurrent-overload qualification.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.durable import Durable, ExpiredError, Request
from benchmarks.durable import certificate


def measure(
    source: Path, destination: Path, vertices: int, updates: int = 40000
) -> dict:
    """Create checkpoint/tail state, backup, close source and restore exact state."""
    if vertices < 8 or not 32768 < updates <= 250000 or updates % 4:
        raise ValueError(
            "require n>=8 and a multiple of four updates in (32768,250000]"
        )
    recovery_path = Path(str(destination) + ".restore")
    if any(path.exists() for path in (source, destination, recovery_path)):
        raise ValueError("benchmark requires fresh source and destination paths")
    tick = time.perf_counter()
    with Durable(source, n=vertices, checkpoint_interval=32768) as store:
        construction = time.perf_counter() - tick
        for first in range(1, updates + 1, 256):
            requests = []
            for sequence in range(first, min(first + 256, updates + 1)):
                operation, edge = (
                    ("delete", (0, 1)),
                    ("insert", (0, 4)),
                    ("delete", (0, 4)),
                    ("insert", (0, 1)),
                )[(sequence - 1) % 4]
                requests.append(Request(sequence, operation, *edge))
            result = store.apply(requests)
            if any(not outcome.changed for outcome in result):
                raise RuntimeError("bootstrap contains non-real transitions")
        expected = certificate(store, set(), set(), vertices)
        status = store.status()
        tick = time.perf_counter()
        manifest = store.backup(destination)
        backup_seconds = time.perf_counter() - tick
        if store.status() != status:
            raise RuntimeError("backup changed source status")
    tick = time.perf_counter()
    shutil.copyfile(destination, recovery_path)
    clone_seconds = time.perf_counter() - tick
    tick = time.perf_counter()
    with Durable(recovery_path) as restored:
        recovery_seconds = time.perf_counter() - tick
        if restored.status() != status:
            # Runtime SQLite/native capacities can differ; compare logical state.
            for key in (
                "sequence",
                "version",
                "edges",
                "matching",
                "retired_floor",
                "checkpoint_sequence",
                "checkpoint_generation",
            ):
                if restored.status()[key] != status[key]:
                    raise RuntimeError("backup logical status disagrees")
        tick = time.perf_counter()
        if certificate(restored, set(), set(), vertices) != expected:
            raise RuntimeError("backup exact topology/partner recovery failed")
        audit_seconds = time.perf_counter() - tick
        if restored.apply([requests[-1]]) != (result[-1],):
            raise RuntimeError("backup did not preserve original retry result")
        try:
            restored.apply([Request(1, "delete", 0, 1)])
        except ExpiredError:
            pass
        else:
            raise RuntimeError("backup lost retry retirement")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "bounded owner backup + independent exact disaster restore; NOT power-cut/overload qualification",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": status["sqlite"],
        "vertices": vertices,
        "edges": 2 * vertices,
        "bootstrap_real_updates": updates,
        "construction_seconds": construction,
        "backup_seconds": backup_seconds,
        "restore_clone_seconds": clone_seconds,
        "restore_seconds": recovery_seconds,
        "independent_restore_audit_seconds": audit_seconds,
        "independent_exact_restore_passed": True,
        "retry_and_expiry_passed": True,
        "matching_digest": expected,
        "manifest": manifest,
        "source_status": status,
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "max_backup_bytes": 64 << 20,
    }


def main() -> None:
    """Print one installed-package backup/restore qualification record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=32000)
    parser.add_argument("--updates", type=int, default=40000)
    args = parser.parse_args()
    print(
        json.dumps(
            measure(args.source, args.destination, args.vertices, args.updates),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
