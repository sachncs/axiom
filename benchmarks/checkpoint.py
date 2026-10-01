"""Measure exact native checkpoint images/restoration, not durable compaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.engine import Engine


def measure(vertices: int, pairs: int = 2048, seed: int = 599) -> dict:
    """Create real churn and independently compare original/restored public state."""
    if vertices < 8 or not 1 <= pairs <= min(vertices, 8192):
        raise ValueError("require n>=8 and 1<=pairs<=min(n,8192)")
    engine = Engine(vertices)
    engine.ring(2)
    rng = random.Random(seed)
    removed, extra = set(), set()
    for _ in range(pairs):
        while True:
            u = rng.randrange(vertices)
            edge = tuple(sorted((u, (u + rng.randrange(1, 3)) % vertices)))
            if edge not in removed:
                break
        if not engine.delete(*edge):
            raise RuntimeError("expected real ring deletion")
        removed.add(edge)
        while True:
            u, v = sorted(rng.sample(range(vertices), 2))
            if 2 < v - u < vertices - 2 and (u, v) not in extra:
                break
        if not engine.insert(u, v):
            raise RuntimeError("expected real non-ring insertion")
        extra.add((u, v))
    tick = time.perf_counter()
    data = engine.snapshot()
    encoding = time.perf_counter() - tick
    tick = time.perf_counter()
    restored = Engine.restore(data)
    restoration = time.perf_counter() - tick
    tick = time.perf_counter()
    if (
        not engine.check()
        or not restored.check()
        or engine.version != restored.version
        or engine.version != 1 + 2 * pairs
        or engine.num_edges() != restored.num_edges()
        or engine.num_edges() != 2 * vertices
        or engine.size() != restored.size()
    ):
        raise RuntimeError("checkpoint count/version/native audit failed")
    matching = hashlib.sha256()
    count = 0
    for u in range(vertices):
        partner = engine.partner(u)
        if partner != restored.partner(u) or engine.degree(u) != restored.degree(u):
            raise RuntimeError("checkpoint changed exact public partner/degree state")
        matching.update(
            (0xFFFFFFFF if partner is None else partner).to_bytes(4, "little")
        )
        if partner is not None:
            if restored.partner(partner) != u or not restored.has_edge(u, partner):
                raise RuntimeError("independent proper matching failed")
        for distance in (1, 2):
            a, b = sorted((u, (u + distance) % vertices))
            if (a, b) not in removed:
                if not restored.has_edge(a, b) or (
                    restored.partner(a) is None and restored.partner(b) is None
                ):
                    raise RuntimeError("independent ring topology/maximality failed")
                count += 1
    for u, v in extra:
        if not restored.has_edge(u, v) or (
            restored.partner(u) is None and restored.partner(v) is None
        ):
            raise RuntimeError("independent inserted topology/maximality failed")
        count += 1
    if count != restored.num_edges():
        raise RuntimeError("independent exact topology count failed")
    if restored.snapshot() != data:
        raise RuntimeError("restored image changed adjacency order or logical state")
    audit = time.perf_counter() - tick
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "scope": "native audited checkpoint encode/restore; NO durable checkpoint publication or history compaction",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "vertices": vertices,
        "edges": 2 * vertices,
        "pairs": pairs,
        "seed": seed,
        "image_bytes": len(data),
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "matching_sha256": matching.hexdigest(),
        "version": restored.version,
        "encoding_seconds": encoding,
        "restoration_seconds": restoration,
        "independent_audit_seconds": audit,
        "exact_restoration_passed": True,
        "source_native_bytes": engine.memory()["allocated"],
        "restored_native_bytes": restored.memory()["allocated"],
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
    }


def main() -> None:
    """Print a fresh-process bounded native checkpoint measurement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertices", type=int, default=32000)
    parser.add_argument("--pairs", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=599)
    args = parser.parse_args()
    print(json.dumps(measure(args.vertices, args.pairs, args.seed), indent=2))


if __name__ == "__main__":
    main()
