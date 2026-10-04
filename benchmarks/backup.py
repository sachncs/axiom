"""Measure paper-mode SQLite backup and exact restore from a fresh store."""

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

from axiom.durable import Durable, Request


def measure(
    source: Path,
    destination: Path,
    vertices: int = 32,
    updates: int = 8,
    *,
    mode: str = "basic",
) -> dict:
    """Commit real edge transitions, back up, restore, and compare graph state."""
    if (
        type(vertices) is not int
        or vertices < 8
        or vertices % 2
        or type(updates) is not int
        or not 2 <= updates <= 100_000
        or mode not in ("basic", "multilevel")
    ):
        raise ValueError("invalid paper backup envelope")
    restored_path = Path(str(destination) + ".restore")
    if any(path.exists() for path in (source, destination, restored_path)):
        raise ValueError("backup measurement requires fresh paths")
    started = time.perf_counter_ns()
    with Durable(source, n=vertices, mode=mode, max_batch=256) as store:
        construction_ns = time.perf_counter_ns() - started
        requests = []
        outcomes = []
        for first in range(1, updates + 1, 256):
            group = []
            for sequence in range(first, min(first + 256, updates + 1)):
                operation, edge = (
                    ("delete", (0, 1)),
                    ("insert", (0, 3)),
                    ("delete", (0, 3)),
                    ("insert", (0, 1)),
                )[(sequence - 1) % 4]
                group.append(Request(sequence, operation, *edge))
            result = store.apply(group)
            if any(not outcome.changed for outcome in result):
                raise RuntimeError("backup trace must contain real transitions")
            requests.extend(group)
            outcomes.extend(result)
        expected = (
            store.status(),
            store.partner(0),
            store.partner(1),
            store.partner(2),
        )
        backup_started = time.perf_counter_ns()
        manifest = store.backup(destination)
        backup_ns = time.perf_counter_ns() - backup_started
        if store.status() != expected[0]:
            raise RuntimeError("backup changed source state")
    clone_started = time.perf_counter_ns()
    shutil.copyfile(destination, restored_path)
    clone_ns = time.perf_counter_ns() - clone_started
    restore_started = time.perf_counter_ns()
    with Durable(restored_path, mode=mode) as restored:
        recovery_ns = time.perf_counter_ns() - restore_started
        actual = (
            restored.status(),
            restored.partner(0),
            restored.partner(1),
            restored.partner(2),
        )
        if actual != expected or not restored.check():
            raise RuntimeError("restored paper graph/matching differs from source")
        if restored.apply([requests[-1]]) != (outcomes[-1],):
            raise RuntimeError("backup did not preserve request retry result")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "SQLite backup/restore of paper Durable state; not power-loss qualification",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mode": mode,
        "vertices": vertices,
        "updates": updates,
        "construction_ns": construction_ns,
        "backup_ns": backup_ns,
        "restore_clone_ns": clone_ns,
        "restore_open_ns": recovery_ns,
        "exact_restore_passed": True,
        "retry_result_preserved": True,
        "source_status": expected[0],
        "manifest": manifest,
        "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
    }


def main() -> None:
    """Run paper-mode backup/restore and print its qualification report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=32000)
    parser.add_argument("--updates", type=int, default=40000)
    parser.add_argument("--mode", choices=("basic", "multilevel"), default="basic")
    args = parser.parse_args()
    print(
        json.dumps(
            measure(
                args.source,
                args.destination,
                args.vertices,
                args.updates,
                mode=args.mode,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
