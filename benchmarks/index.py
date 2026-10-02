"""Fixed nondurable traces compare index memory/compute without arrival losses.

Use isolated installed-wheel processes, identical arguments and fresh repeats.
This is not a durable/service throughput or aggregate resource qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import sys
import time
from dataclasses import dataclass


@dataclass
class Trial:
    """Own a bounded fixed ring trace and its independent exact-state reference."""

    vertices: int = 8192
    width: int = 32
    updates: int = 10000
    budget: int = 32 << 20

    def __post_init__(self):
        """Reject unsafe/ambiguous workloads before importing or allocating graphs."""
        if (
            any(type(value) is not int for value in vars(self).values())
            or not 8 <= self.vertices <= 1000000
            or self.vertices % 2
            or self.width not in (2, 8, 32)
            or self.width >= self.vertices // 2
            or not 2 <= self.updates <= 200000
            or self.updates % 2
            or not 1 << 20 <= self.budget <= 1 << 30
        ):
            raise ValueError("invalid bounded fixed index trace")

    def run(self) -> dict:
        """Time real edits plus partner checks; certify topology outside timing."""
        from axiom.engine import Engine

        started = time.perf_counter_ns()
        engine = Engine(self.vertices, budget=self.budget)
        engine.ring(self.width)
        constructor = time.perf_counter_ns() - started
        started = time.perf_counter_ns()
        for sequence in range(1, self.updates + 1):
            vertex = 2 * (((sequence - 1) // 2) % (self.vertices // 2))
            changed = (
                engine.delete(vertex, vertex + 1)
                if sequence % 2
                else engine.insert(vertex, vertex + 1)
            )
            if (
                not changed
                or engine.version != sequence + 1
                or engine.partner(vertex) != (None if sequence % 2 else vertex + 1)
            ):
                raise RuntimeError("fixed trace edit/query disagrees with reference")
        elapsed = (time.perf_counter_ns() - started) / 1e9
        if (
            engine.num_edges() != self.width * self.vertices
            or engine.size() != self.vertices // 2
            or not engine.check()
        ):
            raise RuntimeError("fixed trace final control/certificate differs")
        digest = hashlib.sha256()
        for vertex in range(self.vertices):
            if engine.partner(vertex) != vertex ^ 1:
                raise RuntimeError("fixed trace exact partners differ")
            digest.update((vertex ^ 1).to_bytes(4, "little"))
            for distance in range(1, self.width + 1):
                if not engine.has_edge(vertex, (vertex + distance) % self.vertices):
                    raise RuntimeError("fixed trace exact ring topology differs")
        image = engine.snapshot()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "scope": "fixed nondurable real edits plus partner checks; NOT service/durability qualification",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "vertices": self.vertices,
            "width": self.width,
            "updates": self.updates,
            "budget": self.budget,
            "constructor": constructor / 1e9,
            "seconds": elapsed,
            "rate": self.updates / elapsed,
            "memory": engine.memory(),
            "rss": rss if sys.platform == "darwin" else rss * 1024,
            "checkpoint": hashlib.sha256(image).hexdigest(),
            "matching": digest.hexdigest(),
            "verified": True,
        }

    @classmethod
    def cli(cls):
        """Run one isolated trace; repeat outside the process for fresh RSS peaks."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--vertices", type=int, default=8192)
        parser.add_argument("--width", type=int, default=32)
        parser.add_argument("--updates", type=int, default=10000)
        parser.add_argument("--budget", type=int, default=32 << 20)
        print(json.dumps(cls(**vars(parser.parse_args())).run(), indent=2))


if __name__ == "__main__":
    Trial.cli()
