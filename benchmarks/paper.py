"""Reproducible paper-coloring benchmarks.

Run ``python benchmarks/paper.py --sizes 2 8 32 --repeats 7``.
Pruning/construction sizes count collision gadgets; complete sizes count vertices.
Setup and certification are excluded from timings. Memory measurement uses a
separate execution so tracing does not distort the timing samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
import tracemalloc
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.graph import Adjacency
from axiom.paper_coloring import Fans, Paper, Partial, Pruning, Spoke
from axiom.types import Edge


@dataclass
class Workload:
    """Fresh coloring, fan, and matching state for one benchmark execution."""

    coloring: Partial
    fans: Fans
    pending: set[Edge]
    spokes: tuple[Spoke, ...]


@dataclass(frozen=True)
class Measurement:
    """Timing, peak-memory, graph-size, and certificate data for one scenario."""

    scenario: str
    size: int
    vertices: int
    edges: int
    repeats: int
    median: float
    minimum: float
    maximum: float
    deviation: float
    peak: int
    checksum: str


class Scenario(ABC):
    """A benchmark owns graph setup, timed work, and its certificate."""

    @abstractmethod
    def prepare(self, size: int) -> Workload:
        """Return a fresh, deterministic workload."""

    @abstractmethod
    def execute(self, workload: Workload) -> None:
        """Perform the operation being measured."""

    def verify(self, workload: Workload) -> str:
        """Validate coloring and fan state and return its stable digest."""
        workload.coloring.validate()
        workload.fans.validate()
        workload.fans.compatible(workload.coloring)
        certificate = {
            "colors": sorted(workload.coloring.items()),
            "fans": [(fan.vertices, fan.alpha, fan.beta) for fan in workload.fans],
        }
        return hashlib.sha256(json.dumps(certificate).encode()).hexdigest()

    def measure(self, size: int, repeats: int) -> Measurement:
        """Measure fresh deterministic samples, validating them outside timing."""
        if size < 1 or repeats < 1:
            raise ValueError("size and repeats must be positive")
        warmup = self.prepare(size)
        self.execute(warmup)
        expected = self.verify(warmup)
        samples = []
        for repetition in range(repeats):
            workload = self.prepare(size)
            start = time.perf_counter()
            self.execute(workload)
            samples.append(time.perf_counter() - start)
            if self.verify(workload) != expected:
                raise AssertionError(f"nondeterministic sample {repetition}")
        workload = self.prepare(size)
        tracemalloc.start()
        try:
            self.execute(workload)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        if self.verify(workload) != expected:
            raise AssertionError("memory sample differs from timing samples")
        return Measurement(
            type(self).__name__,
            size,
            workload.coloring.graph.n,
            workload.coloring.graph.num_edges(),
            repeats,
            statistics.median(samples),
            min(samples),
            max(samples),
            statistics.pstdev(samples),
            peak,
            expected,
        )


class Collision(Scenario):
    """Measure repeated collisions between disjoint pairs of Vizing fans."""

    def prepare(self, size: int) -> Workload:
        """Build independent collision gadgets with a fixed partial coloring."""
        graph = Adjacency(size * 8)
        assignments = []
        pending = set()
        for index in range(size):
            offset = index * 8
            for left, right in ((0, 1), (0, 4), (1, 5), (2, 3), (2, 4), (3, 6), (3, 7)):
                graph.add_edge(offset + left, offset + right)
            for edge, color in (
                ((0, 4), 1),
                ((1, 5), 0),
                ((2, 4), 2),
                ((3, 6), 0),
                ((3, 7), 1),
            ):
                assignments.append(((offset + edge[0], offset + edge[1]), color))
            pending.update({(offset, offset + 1), (offset + 2, offset + 3)})
        coloring = Partial(graph, 3)
        for edge, color in assignments:
            coloring.assign(edge, color)
        return Workload(coloring, Fans(), pending, Pruning.seed(coloring, pending))

    def execute(self, workload: Workload) -> None:
        """Prune the matching and require every gadget to produce a u-fan."""
        survivors = Pruning.prune(workload.coloring, workload.fans, workload.spokes)
        if survivors:
            raise AssertionError("collision fixture left surviving u-edges")

    def verify(self, workload: Workload) -> str:
        """Certify one surviving u-fan per collision gadget."""
        if len(workload.fans) != len(workload.pending) // 2:
            raise AssertionError("collision fixture lost fan progress")
        return super().verify(workload)


class Construction(Collision):
    """Measure matching seeding, fan pruning, and surviving-chain reduction."""

    def execute(self, workload: Workload) -> None:
        """Construct the matching's certified u-fan collection."""
        workload.fans = Pruning.construct(workload.coloring, workload.pending)


class Complete(Scenario):
    """Measure complete coloring for a deterministic graph family."""

    def __init__(self, family: str) -> None:
        """Select a supported graph family, rejecting unknown names."""
        if family not in {"sparse", "dense", "star", "bipartite"}:
            raise ValueError("unknown graph family")
        self.family = family

    def prepare(self, size: int) -> Workload:
        """Build an uncolored graph with the requested vertex count."""
        graph = Adjacency(size)
        for left in range(size):
            for right in range(left + 1, size):
                include = {
                    "sparse": (left * 17 + right * 31) % 11 < 2,
                    "dense": (left * 17 + right * 31) % 11 < 9,
                    "star": left == 0,
                    "bipartite": left < size // 2 <= right,
                }[self.family]
                if include:
                    graph.add_edge(left, right)
        delta = max((graph.degree(vertex) for vertex in range(size)), default=0)
        return Workload(Partial(graph, delta + 1), Fans(), set(graph.edges()), ())

    def execute(self, workload: Workload) -> None:
        """Run complete paper coloring and index the returned colors."""
        result = Paper.color(workload.coloring.graph, workload.coloring.palette - 1)
        workload.coloring.assignments = result
        workload.coloring.reindex()

    def verify(self, workload: Workload) -> str:
        """Require a proper coloring covering every graph edge."""
        if workload.coloring.edges() != set(workload.coloring.graph.edges()):
            raise AssertionError("benchmark returned an incomplete coloring")
        return super().verify(workload)


class Reduction(Scenario):
    """Measure activation of independent nontrivial Vizing chains."""

    def prepare(self, size: int) -> Workload:
        """Build gadgets whose source u-edges require alternating chain flips."""
        graph = Adjacency(size * 8)
        assignments = []
        pending = set()
        for index in range(size):
            offset = 8 * index
            for left, right in ((0, 1), (0, 2), (0, 3), (1, 4), (2, 5), (3, 7)):
                graph.add_edge(offset + left, offset + right)
            for edge, color in (
                ((1, 4), 0),
                ((0, 2), 1),
                ((2, 5), 0),
                ((0, 3), 2),
                ((3, 7), 0),
            ):
                assignments.append(((offset + edge[0], offset + edge[1]), color))
            pending.add((offset, offset + 1))
        coloring = Partial(graph, 3)
        for edge, color in assignments:
            coloring.assign(edge, color)
        return Workload(coloring, Fans(), pending, Pruning.seed(coloring, pending))

    def execute(self, workload: Workload) -> None:
        """Reduce every pending u-edge through its materialized Vizing chain."""
        progress = Pruning.reduce(workload.coloring, workload.fans, workload.spokes)
        if progress != len(workload.pending):
            raise AssertionError("chain reduction did not consume every u-edge")

    def verify(self, workload: Workload) -> str:
        """Certify a complete coloring and each gadget's required chain flip."""
        if workload.coloring.edges() != set(workload.coloring.graph.edges()):
            raise AssertionError("chain reduction left an incomplete coloring")
        for index in range(workload.coloring.graph.n // 8):
            offset = 8 * index
            if workload.coloring[(offset + 2, offset + 5)] != 1:
                raise AssertionError("chain reduction skipped its alternating flip")
        return super().verify(workload)


class Flip(Scenario):
    """Measure path-local alternating flips in a sparse coloring."""

    def prepare(self, size: int) -> Workload:
        """Place a four-edge colored path in the requested vertex universe."""
        if size < 2:
            raise ValueError("flip benchmark requires at least two vertices")
        length = min(4, size - 1)
        path = tuple(range(length + 1))
        graph = Adjacency(size)
        coloring = Partial(graph, 3)
        for index in range(length):
            edge = path[index], path[index + 1]
            graph.add_edge(*edge)
            coloring.assign(edge, 1 if index % 2 == 0 else 0)
        return Workload(coloring, Fans(), set(), ())

    def execute(self, workload: Workload) -> None:
        """Flip forward and backward eight times to restore the input coloring."""
        length = min(4, workload.coloring.graph.n - 1)
        path = list(range(length + 1))
        reverse = list(reversed(path))
        reverse_beta, reverse_gamma = (1, 0) if length % 2 else (0, 1)
        for _ in range(8):
            workload.coloring.flip(path, 0, 1)
            workload.coloring.flip(reverse, reverse_beta, reverse_gamma)


class ReindexedFlip(Flip):
    """Reference the former full-coloring reindex after every path flip."""

    def execute(self, workload: Workload) -> None:
        """Apply the same path recolorings, rebuilding all indexes each time."""
        length = min(4, workload.coloring.graph.n - 1)
        path = list(range(length + 1))
        reverse = list(reversed(path))
        for current in (path, reverse) * 8:
            edges = []
            for index in range(length):
                left, right = current[index], current[index + 1]
                edges.append((min(left, right), max(left, right)))
            for edge in edges:
                color = workload.coloring.assignments[edge]
                workload.coloring.assignments[edge] = 0 if color == 1 else 1
            workload.coloring.reindex()


class Benchmark:
    """Command-line runner for the paper-coloring benchmark scenarios."""

    def run(self, arguments: list[str] | None = None) -> int:
        """Parse workloads, run selected scenarios, and print JSON measurements."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--sizes", type=int, nargs="+", default=[2, 8, 32])
        parser.add_argument("--repeats", type=int, default=7)
        parser.add_argument(
            "--scenario",
            choices=[
                "all",
                "pruning",
                "construction",
                "reduction",
                "complete",
                "flip",
                "flip-reindex",
            ],
            default="all",
        )
        parser.add_argument(
            "--family",
            choices=["sparse", "dense", "star", "bipartite"],
            default="dense",
        )
        args = parser.parse_args(arguments)
        if args.repeats < 1 or any(size < 1 for size in args.sizes):
            parser.error("sizes and repeats must be positive")
        if args.scenario in {"flip", "flip-reindex"} and any(
            size < 2 for size in args.sizes
        ):
            parser.error("flip scenarios require at least two vertices")
        scenarios: dict[str, Scenario] = {
            "pruning": Collision(),
            "construction": Construction(),
            "reduction": Reduction(),
            "complete": Complete(args.family),
            "flip": Flip(),
            "flip-reindex": ReindexedFlip(),
        }
        selected = (
            scenarios.values() if args.scenario == "all" else [scenarios[args.scenario]]
        )
        results = [
            asdict(scenario.measure(size, args.repeats))
            for scenario in selected
            for size in args.sizes
        ]
        print(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "family": args.family,
                    "seconds": "wall clock; setup/certification excluded",
                    "memory": "peak traced bytes from a separate sample",
                    "results": results,
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(Benchmark().run())
