"""Minimal example: basic mode on a path graph."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from axiom import Matcher


def main() -> None:
    n = 10
    algo = Matcher(n, mode="basic")

    # Build a path
    for i in range(n - 1):
        algo.insert(i, i + 1)

    print("Matching size:", algo.size())
    print("Is maximal:", algo.maximal())
    print("Stats:", algo.stats())


if __name__ == "__main__":
    main()
