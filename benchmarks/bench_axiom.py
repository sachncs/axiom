"""Lightweight benchmark for Axiom update throughput.

This is an engineering utility, not part of the paper's baseline algorithm.
Run with::

    python benchmarks/bench_axiom.py --n 200 --updates 5000 --mode basic
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from axiom.core import Matcher
from axiom.simulation import random_updates


def bench(n: int, mode: str, updates: int, seed: int) -> dict[str, float]:
    algo = Matcher(n, mode=mode)
    rng = random.Random(seed)
    seq = list(random_updates(n, updates, rng))

    start = time.perf_counter()
    for op, u, v in seq:
        if op == "insert":
            algo.insert(u, v)
        else:
            algo.delete(u, v)
    elapsed = time.perf_counter() - start

    assert algo.maximal()
    stats = algo.stats()

    return {
        "n": n,
        "mode": mode,
        "updates": updates,
        "elapsed_sec": elapsed,
        "updates_per_sec": updates / elapsed if elapsed > 0 else float("inf"),
        "matching_size": stats["matching_size"],
        "is_maximal": algo.maximal(),
        "phase_rebuilds": stats["phase_rebuilds"],
        "subphase_rebuilds": stats["subphase_rebuilds"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Axiom throughput benchmark")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--mode", choices=["basic", "tiered"], default="basic")
    parser.add_argument("--updates", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    result = bench(args.n, args.mode, args.updates, args.seed)
    for k, v in result.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
