"""Measure public matcher updates with deterministic, controlled graph workloads.

Throughput, latency, queries, and traced memory are measured in separate passes.
Run ``python benchmarks/performance.py --output benchmarks/results/pilot``.
Every case runs in an isolated subprocess, sequentially, with a wall-time cap.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import resource
import statistics
import subprocess
import sys
import time
import tracemalloc
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.matching import greedy, is_maximal_matching, partners
from axiom.types import Edge


class Bag:
    """A deterministic mutable edge pool with constant-time random selection."""

    def __init__(self, edges: tuple[Edge, ...] = ()) -> None:
        """Index an ordered collection of distinct canonical edges."""
        self.values = list(edges)
        self.index = {edge: index for index, edge in enumerate(edges)}

    def add(self, edge: Edge) -> None:
        """Add an absent edge to the sampling pool."""
        if edge in self.index:
            raise ValueError("edge already present in pool")
        self.index[edge] = len(self.values)
        self.values.append(edge)

    def remove(self, edge: Edge) -> None:
        """Remove an edge by swapping the final entry into its position."""
        index = self.index.pop(edge)
        last = self.values.pop()
        if index < len(self.values):
            self.values[index] = last
            self.index[last] = index


@dataclass(frozen=True)
class Shape:
    """Graph domain and initial average-degree target for one workload."""

    vertices: int
    family: str
    degree: int

    @property
    def capacity(self) -> int:
        """Return the number of edges permitted by this graph family."""
        if self.family == "star":
            return self.vertices - 1
        if self.family == "bipartite":
            return (self.vertices // 2) * (self.vertices - self.vertices // 2)
        return self.vertices * (self.vertices - 1) // 2

    def draw(self, rng: random.Random, hot: bool = False) -> Edge:
        """Draw a canonical edge, optionally concentrating updates at vertex zero."""
        if self.family == "star" or hot:
            start = self.vertices // 2 if self.family == "bipartite" else 1
            return 0, rng.randrange(start, self.vertices)
        if self.family == "bipartite":
            return rng.randrange(self.vertices // 2), rng.randrange(
                self.vertices // 2, self.vertices
            )
        left = rng.randrange(self.vertices)
        right = rng.randrange(self.vertices - 1)
        right += right >= left
        return min(left, right), max(left, right)

    def absent(self, rng: random.Random, pool: Bag, hot: bool = False) -> Edge:
        """Draw an absent edge, using a deterministic scan near saturation."""
        attempts = 0
        while attempts < 64:
            attempts += 1
            edge = self.draw(rng, hot)
            if edge not in pool.index:
                return edge
        for left in range(self.vertices):
            for right in range(left + 1, self.vertices):
                eligible = (self.family != "star" or left == 0) and (
                    self.family != "bipartite" or left < self.vertices // 2 <= right
                )
                if eligible and (left, right) not in pool.index:
                    return left, right
        raise ValueError("graph domain has no absent edges")

    def initial(self, seed: int) -> tuple[Edge, ...]:
        """Build a seeded graph with room for both insertions and deletions."""
        rng = random.Random(seed)
        target = min(self.vertices * self.degree // 2, self.capacity // 2)
        pool = Bag()
        while len(pool.values) < target:
            pool.add(self.absent(rng, pool))
        return tuple(sorted(pool.values))


@dataclass(frozen=True)
class Trace:
    """Immutable initial graph and valid prepared updates, shared across algorithms."""

    initial: tuple[Edge, ...]
    operations: tuple[tuple[str, int, int], ...]
    digest: str

    def graph(self, vertices: int) -> Adjacency:
        """Materialize a fresh initial graph outside update timing."""
        graph = Adjacency(vertices)
        for edge in self.initial:
            graph.add_edge(*edge)
        return graph


class Workload(ABC):
    """A workload defines update order without observing an algorithm's matching."""

    @abstractmethod
    def generate(
        self, shape: Shape, pool: Bag, rng: random.Random, count: int
    ) -> list[tuple[str, int, int]]:
        """Prepare operations against the mutable graph pool."""

    def prepare(self, shape: Shape, seed: int, count: int) -> Trace:
        """Generate and independently validate a reproducible update trace."""
        if shape.vertices < 2 or count < 1 or shape.degree < 1:
            raise ValueError("vertices >= 2, degree >= 1 and updates >= 1 are required")
        initial = shape.initial(seed)
        operations = self.generate(
            shape, Bag(initial), random.Random(seed + 1009), count
        )
        live = set(initial)
        for operation, left, right in operations:
            edge = left, right
            present = edge in live
            if operation == "insert":
                if present and not isinstance(self, Duplicate):
                    raise AssertionError("real insertion trace contains a no-op")
                live.add(edge)
            elif operation == "delete":
                if not present and not isinstance(self, Absent):
                    raise AssertionError("real deletion trace contains a no-op")
                live.discard(edge)
            else:
                raise AssertionError("unknown opcode")
        payload = json.dumps(
            (shape.vertices, initial, operations), separators=(",", ":")
        )
        return Trace(
            initial, tuple(operations), hashlib.sha256(payload.encode()).hexdigest()
        )


class Growth(Workload):
    """Insert absent edges until the requested length or domain capacity is reached."""

    def generate(
        self, shape: Shape, pool: Bag, rng: random.Random, count: int
    ) -> list[tuple[str, int, int]]:
        """Produce a finite insertion-only growth trace."""
        operations = []
        limit = min(count, shape.capacity - len(pool.values))
        while len(operations) < limit:
            edge = shape.absent(rng, pool)
            pool.add(edge)
            operations.append(("insert", *edge))
        return operations


class Drain(Workload):
    """Delete present edges without replenishment until the graph empties."""

    def generate(
        self, shape: Shape, pool: Bag, rng: random.Random, count: int
    ) -> list[tuple[str, int, int]]:
        """Produce a finite deletion-only draining trace."""
        operations = []
        limit = min(count, len(pool.values))
        while len(operations) < limit:
            edge = rng.choice(pool.values)
            pool.remove(edge)
            operations.append(("delete", *edge))
        return operations


class Churn(Workload):
    """Alternate real deletions and insertions while retaining the initial density."""

    width = 1
    hot = False

    def generate(
        self, shape: Shape, pool: Bag, rng: random.Random, count: int
    ) -> list[tuple[str, int, int]]:
        """Prepare balanced updates, optionally in bursts or around a hotspot."""
        operations = []
        for index in range(count):
            deleting = (index // self.width) % 2 == 0
            deleting = bool(pool.values) and (
                deleting or len(pool.values) == shape.capacity
            )
            if deleting:
                candidates = (
                    [edge for edge in pool.values if 0 in edge] if self.hot else []
                )
                edge = rng.choice(candidates or pool.values)
                pool.remove(edge)
                operation = "delete"
            else:
                edge = shape.absent(rng, pool, self.hot)
                pool.add(edge)
                operation = "insert"
            operations.append((operation, *edge))
        return operations


class Burst(Churn):
    """Alternate batches of sixteen real deletions and insertions."""

    width = 16


class Hotspot(Churn):
    """Concentrate balanced churn at vertex zero where the domain permits it."""

    hot = True


class Duplicate(Workload):
    """Measure duplicate insert calls without counting them as real updates."""

    def generate(
        self, shape: Shape, pool: Bag, rng: random.Random, count: int
    ) -> list[tuple[str, int, int]]:
        """Select edges already present in the unchanged initial graph."""
        return [("insert", *rng.choice(pool.values)) for index in range(count)]


class Absent(Workload):
    """Measure absent-edge delete calls independently of real deletion throughput."""

    def generate(
        self, shape: Shape, pool: Bag, rng: random.Random, count: int
    ) -> list[tuple[str, int, int]]:
        """Select absent edges without mutating the initial graph."""
        return [("delete", *shape.absent(rng, pool)) for index in range(count)]


class Engine(ABC):
    """Shared measured interface for dynamic algorithms and recomputation."""

    @abstractmethod
    def apply(self, operation: str, left: int, right: int) -> None:
        """Perform one public update, including normal validation and maintenance."""

    @abstractmethod
    def snapshot(self) -> dict[str, int]:
        """Return diagnostic counters outside operation timing."""

    def verify(self) -> None:
        """Require existing, canonical, disjoint matching edges and maximality."""
        seen: set[int] = set()
        for left, right in self.matching:
            if (
                not 0 <= left < right < self.graph.n
                or not self.graph.has_edge(left, right)
                or left in seen
                or right in seen
            ):
                raise AssertionError("matching is not proper")
            seen.update((left, right))
        if not is_maximal_matching(self.graph, self.matching):
            raise AssertionError("matching is not maximal")


class Dynamic(Engine):
    """Benchmark the unchanged public Matcher API and its normal validation."""

    def __init__(self, graph: Adjacency, mode: str) -> None:
        """Construct a fresh matcher on the prepared initial graph."""
        self.matcher = Matcher(graph.n, graph=graph, mode=mode)
        self.graph = graph

    @property
    def matching(self) -> set[Edge]:
        """Expose the current authoritative matching for untimed classification."""
        return self.matcher.matched_edges

    def apply(self, operation: str, left: int, right: int) -> None:
        """Dispatch the prepared operation to the public update API."""
        if operation == "insert":
            self.matcher.insert(left, right)
        else:
            self.matcher.delete(left, right)

    def snapshot(self) -> dict[str, int]:
        """Read cumulative rebuild and rematching counters."""
        return self.matcher.stats()

    def verify(self) -> None:
        """Require matching maximality and an internally valid active hierarchy."""
        super().verify()
        if self.matcher.multi is not None and not self.matcher.multi.check():
            raise AssertionError("hierarchy is invalid")


class Recompute(Engine):
    """Reference baseline rebuilding a greedy maximal matching after every real update."""

    def __init__(self, graph: Adjacency, mode: str = "recompute") -> None:
        """Build the initial greedy matching and its partner map."""
        self.graph = graph
        self.matching = greedy(graph)
        self.mapping = partners(self.matching)
        self.rebuilds = 0

    def apply(self, operation: str, left: int, right: int) -> None:
        """Apply a real graph mutation and recompute matching and query indexes."""
        present = self.graph.has_edge(left, right)
        if (operation == "insert") == present:
            return
        if operation == "insert":
            self.graph.add_edge(left, right)
        else:
            self.graph.remove_edge(left, right)
        self.matching = greedy(self.graph)
        self.mapping = partners(self.matching)
        self.rebuilds += 1

    def snapshot(self) -> dict[str, int]:
        """Report full recomputations without pretending they are Axiom phases."""
        return {
            "phase_rebuilds": self.rebuilds,
            "subphase_rebuilds": 0,
            "rematch_u_scans": 0,
            "rematch_a_scans": 0,
            "rematch_b_scans": 0,
        }


@dataclass(frozen=True)
class Configuration:
    """Reproducible parameters shared by every measurement pass of a case."""

    vertices: int
    family: str
    degree: int
    workload: str
    mode: str
    seed: int
    updates: int
    repeats: int = 5


class Runner:
    """Run throughput, diagnostic latency, query, and memory passes independently."""

    workloads: dict[str, type[Workload]] = {
        "growth": Growth,
        "drain": Drain,
        "churn": Churn,
        "burst": Burst,
        "hotspot": Hotspot,
        "duplicate": Duplicate,
        "absent": Absent,
    }

    @staticmethod
    def summarize(values: list[int]) -> dict[str, float | int]:
        """Summarize observed latencies using nearest-rank empirical quantiles."""
        if not values:
            return {"count": 0}
        ordered = sorted(values)
        return {
            "count": len(values),
            "median": statistics.median(ordered),
            "p95": ordered[math.ceil(0.95 * len(ordered)) - 1],
            "p99": ordered[math.ceil(0.99 * len(ordered)) - 1],
            "maximum": ordered[-1],
            "total": sum(ordered),
        }

    def run(self, config: Configuration) -> dict:
        """Execute a case with fresh state for every pass and verify identical output."""
        shape = Shape(config.vertices, config.family, config.degree)
        trace = self.workloads[config.workload]().prepare(
            shape, config.seed, config.updates
        )
        if not trace.operations:
            raise ValueError("workload contains no measurable updates")
        factory = Recompute if config.mode == "recompute" else Dynamic
        expected = set(trace.initial)
        for operation, left, right in trace.operations:
            if operation == "insert":
                expected.add((left, right))
            else:
                expected.discard((left, right))
        times = []
        initialization = []
        certificate = None
        counts = {"insert": 0, "delete": 0}
        for item in trace.operations:
            counts[item[0]] += 1
        last = None
        for repetition in range(config.repeats + 1):
            graph = trace.graph(config.vertices)
            start = time.perf_counter_ns()
            engine = factory(graph, config.mode)
            initialized = time.perf_counter_ns() - start
            before = engine.snapshot()
            start = time.perf_counter_ns()
            for operation, left, right in trace.operations:
                engine.apply(operation, left, right)
            elapsed = time.perf_counter_ns() - start
            engine.verify()
            if set(graph.edges()) != expected:
                raise AssertionError("update trace produced an unexpected graph")
            current = sorted(engine.matching)
            if certificate is not None and current != certificate:
                raise AssertionError("repeated measurements changed the matching")
            certificate = current
            if repetition:
                times.append(elapsed)
                initialization.append(initialized)
            last = {
                key: engine.snapshot().get(key, 0) - before.get(key, 0)
                for key in (
                    "phase_rebuilds",
                    "subphase_rebuilds",
                    "rematch_u_scans",
                    "rematch_b_scans",
                    "rematch_a_scans",
                )
            }

        # Classification/counter snapshots never lie inside the timed call interval.
        engine = factory(trace.graph(config.vertices), config.mode)
        latency: dict[str, list[int]] = {}
        samples = []
        for index, (operation, left, right) in enumerate(trace.operations):
            matched = (left, right) in engine.matching
            present = engine.graph.has_edge(left, right)
            before = engine.snapshot()
            start = time.perf_counter_ns()
            engine.apply(operation, left, right)
            elapsed = time.perf_counter_ns() - start
            after = engine.snapshot()
            phase = after["phase_rebuilds"] > before["phase_rebuilds"]
            subphase = after["subphase_rebuilds"] > before["subphase_rebuilds"]
            real = (operation == "insert") != present
            label = operation if real else "noop-" + operation
            boundary = (
                "recompute"
                if phase and config.mode == "recompute"
                else "phase"
                if phase
                else "subphase"
                if subphase
                else "ordinary"
            )
            for category in (label, boundary):
                latency.setdefault(category, []).append(elapsed)
            if operation == "delete" and real:
                latency.setdefault(
                    "matched-delete" if matched else "unmatched-delete", []
                ).append(elapsed)
            samples.append(
                {
                    "index": index,
                    "operation": operation,
                    "real": real,
                    "matched": matched,
                    "nanoseconds": elapsed,
                    "boundary": boundary,
                    "scans": sum(
                        after.get(key, 0) - before.get(key, 0)
                        for key in (
                            "rematch_u_scans",
                            "rematch_a_scans",
                            "rematch_b_scans",
                        )
                    ),
                }
            )
        engine.verify()
        if (
            set(engine.graph.edges()) != expected
            or sorted(engine.matching) != certificate
        ):
            raise AssertionError("latency pass differs from throughput pass")

        queries = {}
        if isinstance(engine, Dynamic):
            matcher = engine.matcher
            for name in ("partner", "size", "matching", "stats", "maximal"):
                values = []
                query = getattr(matcher, name)
                for index in range(256):
                    start = time.perf_counter_ns()
                    if name == "partner":
                        query(index % config.vertices)
                    else:
                        query()
                    values.append(time.perf_counter_ns() - start)
                queries[name] = self.summarize(values)

        tracemalloc.start()
        try:
            engine = factory(trace.graph(config.vertices), config.mode)
            retained, constructionpeak = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            for operation, left, right in trace.operations:
                engine.apply(operation, left, right)
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        engine.verify()
        if (
            set(engine.graph.edges()) != expected
            or sorted(engine.matching) != certificate
        ):
            raise AssertionError("memory pass differs from throughput pass")
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss *= 1 if sys.platform == "darwin" else 1024
        graph = trace.graph(config.vertices)
        median = statistics.median(times)
        noop = config.workload in {"duplicate", "absent"}
        return {
            "status": "ok",
            "configuration": asdict(config),
            "digest": trace.digest,
            "initialedges": len(trace.initial),
            "finaledges": len(expected),
            "maximumdegree": max(graph.degree(vertex) for vertex in range(graph.n)),
            "operations": len(trace.operations),
            "counts": counts,
            "noop": noop,
            "throughput": len(trace.operations) * 1e9 / median,
            "realrate": 0 if noop else len(trace.operations) * 1e9 / median,
            "initialization": self.summarize(initialization),
            "batches": times,
            "latency": {key: self.summarize(values) for key, values in latency.items()},
            "samples": samples,
            "queries": queries,
            "counters": last,
            "memory": {
                "initial": retained,
                "constructionpeak": constructionpeak,
                "current": current,
                "peak": peak,
                "transient": peak - retained,
                "rss": rss,
            },
            "certificate": hashlib.sha256(json.dumps(certificate).encode()).hexdigest(),
        }


class Suite:
    """Sequential, bounded subprocess runner preserving successes and failures."""

    def run(self, arguments: list[str] | None = None) -> int:
        """Run selected configurations and save raw JSON and flattened CSV."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument(
            "--output", type=Path, default=Path("benchmarks/results/pilot")
        )
        parser.add_argument("--sizes", type=int, nargs="+", default=[32, 128, 512])
        parser.add_argument(
            "--profiles",
            nargs="+",
            default=["sparse4", "sparse16", "dense", "star", "bipartite"],
        )
        parser.add_argument(
            "--workloads",
            nargs="+",
            choices=list(Runner.workloads),
            default=list(Runner.workloads),
        )
        parser.add_argument(
            "--modes",
            nargs="+",
            choices=["basic", "multilevel", "recompute"],
            default=["basic", "multilevel", "recompute"],
        )
        parser.add_argument("--seeds", type=int, nargs="+", default=[7, 19, 41])
        parser.add_argument("--updates", type=int, default=128)
        parser.add_argument("--repeats", type=int, default=5)
        parser.add_argument("--timeout", type=float, default=60)
        parser.add_argument("--case", help=argparse.SUPPRESS)
        args = parser.parse_args(arguments)
        if args.case:
            config = Configuration(**json.loads(args.case))
            try:
                result = Runner().run(config)
            except Exception as error:
                result = {
                    "status": "error",
                    "configuration": asdict(config),
                    "error": f"{type(error).__name__}: {error}",
                }
            print(json.dumps(result))
            return 0
        if (
            any(size < 2 for size in args.sizes)
            or args.updates < 1
            or args.repeats < 1
            or args.timeout <= 0
        ):
            parser.error("sizes >= 2; updates, repeats and timeout must be positive")
        profiles = {
            "sparse4": ("sparse", 4),
            "sparse16": ("sparse", 16),
            "dense": ("dense", 0),
            "star": ("star", 2),
            "bipartite": ("bipartite", 16),
        }
        if any(profile not in profiles for profile in args.profiles):
            parser.error("unsupported profile")
        args.output.mkdir(parents=True, exist_ok=True)
        metadata = {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "dirty": bool(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], text=True
                ).strip()
            ),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "hardware": subprocess.check_output(
                [
                    "sysctl",
                    "-n",
                    "machdep.cpu.brand_string",
                    "hw.memsize",
                    "hw.logicalcpu",
                ],
                text=True,
            ).splitlines()
            if sys.platform == "darwin"
            else [platform.machine()],
            "clock": vars(time.get_clock_info("perf_counter")),
            "arguments": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()
            },
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": {
                str(
                    path.relative_to(Path(__file__).resolve().parents[1])
                ): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [
                    Path(__file__).resolve(),
                    *sorted(
                        (Path(__file__).resolve().parents[1] / "axiom").glob("*.py")
                    ),
                ]
            },
        }
        (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
        configurations = []
        for size in args.sizes:
            for profile in args.profiles:
                family, degree = profiles[profile]
                degree = degree or max(2, size // 2)
                for workload in args.workloads:
                    for seed in args.seeds:
                        for mode in args.modes:
                            configurations.append(
                                Configuration(
                                    size,
                                    family,
                                    degree,
                                    workload,
                                    mode,
                                    seed,
                                    args.updates,
                                    args.repeats,
                                )
                            )
        results = []
        with (args.output / "results.jsonl").open("w") as output:
            for index, config in enumerate(configurations):
                start = time.perf_counter()
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--case",
                    json.dumps(asdict(config)),
                ]
                try:
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=args.timeout,
                        check=True,
                    )
                    result = json.loads(completed.stdout)
                except subprocess.TimeoutExpired:
                    result = {
                        "status": "timeout",
                        "configuration": asdict(config),
                        "error": f"case exceeded {args.timeout:g} seconds",
                    }
                except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
                    result = {
                        "status": "error",
                        "configuration": asdict(config),
                        "error": str(error),
                    }
                result["wallseconds"] = time.perf_counter() - start
                output.write(json.dumps(result) + "\n")
                output.flush()
                results.append(result)
                print(
                    f"{index + 1}/{len(configurations)} {config.mode} n={config.vertices} {config.family}/{config.degree} {config.workload} seed={config.seed}: {result['status']}",
                    flush=True,
                )
        with (args.output / "summary.csv").open("w", newline="") as output:
            columns = [
                *asdict(configurations[0]),
                "status",
                "operations",
                "initialedges",
                "finaledges",
                "maximumdegree",
                "throughput",
                "realrate",
                "wallseconds",
                "error",
            ]
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            for result in results:
                writer.writerow(
                    {
                        **result["configuration"],
                        **{
                            key: result.get(key)
                            for key in columns
                            if key not in result["configuration"]
                        },
                    }
                )
        with (args.output / "latency.csv").open("w", newline="") as output:
            columns = [
                *asdict(configurations[0]),
                "index",
                "operation",
                "real",
                "matched",
                "nanoseconds",
                "boundary",
                "scans",
            ]
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            for result in results:
                for sample in result.get("samples", []):
                    writer.writerow({**result["configuration"], **sample})
        return 0


if __name__ == "__main__":
    raise SystemExit(Suite().run())
