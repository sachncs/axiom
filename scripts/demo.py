"""Minimal demo of the Axiom algorithm.

Usage::

    python scripts/demo.py [--n N] [--mode {basic,tiered,multilevel}]

Example::

    python scripts/demo.py --n 10 --mode basic
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from axiom.core import Matcher  # noqa: E402
from axiom.simulation import random_updates  # noqa: E402


def run_demo(n: int, mode: str, num_updates: int, seed: int = 42) -> int:
    """Run a demo sequence of random insertions and deletions.

    Args:
        n: Number of vertices.
        mode: ``"basic"`` or ``"tiered"`` (or deprecated ``"multilevel"``).
        num_updates: Total number of update operations.
        seed: Random seed for reproducibility.

    Returns:
        0 on success, 1 on failure.
    """
    print(f"=== Axiom Demo: n={n}, mode={mode}, updates={num_updates} ===\n")

    algo = Matcher(n, mode=mode)
    rng = random.Random(seed)
    updates = list(random_updates(n, num_updates, rng))

    start = time.perf_counter()
    for op, u, v in updates:
        if op == "insert":
            algo.insert(u, v)
        else:
            algo.delete(u, v)

        if not algo.maximal():
            print(f"ERROR: Matching is not maximal at step {op} ({u},{v})!")
            return 1

    elapsed = time.perf_counter() - start
    stats = algo.stats()

    print(f"Completed {num_updates} updates in {elapsed:.3f}s")
    print(f"Final graph edges: {stats['m']}")
    print(f"Matching size: {stats['matching_size']}")
    print(f"Rebuilds triggered: {stats.get('phase_rebuilds', 0)}")
    print(f"Maximal: {algo.maximal()}")
    print("\nDemo finished successfully.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Axiom Demo")
    parser.add_argument("--n", type=int, default=20, help="Number of vertices")
    parser.add_argument(
        "--mode",
        choices=["basic", "tiered", "multilevel"],
        default="basic",
        help="Algorithm mode (basic = single-level, tiered = multi-level)",
    )
    parser.add_argument(
        "--updates", type=int, default=200, help="Number of update operations"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()
    return run_demo(args.n, args.mode, args.updates, args.seed)


if __name__ == "__main__":
    sys.exit(main())
