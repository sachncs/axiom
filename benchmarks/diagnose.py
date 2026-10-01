"""Profile public update costs separately from headline performance measurements.

Run ``python benchmarks/diagnose.py --output benchmarks/results/diagnosis.json``.
Inclusive function times overlap; do not sum them as disjoint cost categories.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.performance import Churn, Dynamic, Shape


class Diagnosis:
    """Collect function-level evidence without changing production validation."""

    def measure(self, vertices: int, mode: str, updates: int, seed: int) -> dict:
        """Profile only public calls against a fresh deterministic sparse trace."""
        trace = Churn().prepare(Shape(vertices, "sparse", 4), seed, updates)
        engine = Dynamic(trace.graph(vertices), mode)
        timer = cProfile.Profile()
        timer.enable()
        for operation, left, right in trace.operations:
            engine.apply(operation, left, right)
        timer.disable()
        engine.verify()
        expected = set(trace.initial)
        for operation, left, right in trace.operations:
            if operation == "insert":
                expected.add((left, right))
            else:
                expected.remove((left, right))
        if set(engine.graph.edges()) != expected:
            raise AssertionError("profiled updates produced an unexpected graph")
        stats = pstats.Stats(timer)
        functions = []
        root = Path(__file__).resolve().parents[1]
        for (filename, line, name), values in stats.stats.items():
            path = Path(filename)
            if path.is_relative_to(root):
                filename = str(path.relative_to(root))
            primitive, calls, own, cumulative, callers = values
            functions.append(
                {
                    "file": filename,
                    "line": line,
                    "function": name,
                    "primitive": primitive,
                    "calls": calls,
                    "selfseconds": own,
                    "cumulativeseconds": cumulative,
                    "inclusivefraction": cumulative / stats.total_tt,
                    "callers": len(callers),
                }
            )
        functions.sort(key=lambda item: item["cumulativeseconds"], reverse=True)
        return {
            "vertices": vertices,
            "mode": mode,
            "updates": updates,
            "seed": seed,
            "digest": trace.digest,
            "seconds": stats.total_tt,
            "functions": functions,
            "notice": "Instrumented diagnostic, not throughput evidence; inclusive times overlap.",
        }

    def run(self, arguments: list[str] | None = None) -> None:
        """Profile selected modes sequentially and preserve the full function table."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--sizes", type=int, nargs="+", default=[128, 512])
        parser.add_argument(
            "--modes",
            nargs="+",
            choices=["basic", "multilevel"],
            default=["basic", "multilevel"],
        )
        parser.add_argument("--updates", type=int, default=256)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument(
            "--output", type=Path, default=Path("benchmarks/results/diagnosis.json")
        )
        args = parser.parse_args(arguments)
        if any(size < 2 for size in args.sizes) or args.updates < 1:
            parser.error("sizes >= 2 and updates >= 1 are required")
        results = []
        for vertices in args.sizes:
            for mode in args.modes:
                results.append(self.measure(vertices, mode, args.updates, args.seed))
                print(f"profiled {mode} n={vertices}", flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    Diagnosis().run()
