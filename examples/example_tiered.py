"""Minimal example: tiered mode on a random graph."""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from axiom import Matcher
from axiom.simulation import random_updates


def main() -> None:
    n = 20
    algo = Matcher(n, mode="tiered")
    rng = random.Random(7)
    updates = list(random_updates(n, 100, rng))
    for op, u, v in updates:
        if op == "insert":
            algo.insert(u, v)
        else:
            algo.delete(u, v)
        assert algo.maximal()

    print("Matching size:", algo.size())
    print("Stats:", algo.stats())


if __name__ == "__main__":
    main()
