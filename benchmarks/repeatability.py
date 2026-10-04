"""Repeat durable paper workloads in fresh processes and summarize spread.

This is diagnostic qualification tooling, not a benchmark threshold gate. Every
sample gets its own interpreter process and SQLite database so peak RSS and
recovery measurements do not accumulate across repeats.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any


class Repeatability:
    """Run deterministic durable workloads and verify identical-seed results."""

    def __init__(
        self,
        output: Path,
        *,
        vertices: int,
        pairs: int,
        batch: int,
        seeds: list[int],
        repeats: int,
        modes: list[str],
        workload: str,
        hub_degree: int,
    ) -> None:
        """Validate the complete sample plan before creating any output."""
        if (
            type(vertices) is not int
            or vertices < 8
            or type(pairs) is not int
            or not 1 <= pairs <= 32768
            or type(batch) is not int
            or not 2 <= batch <= 4096
            or batch % 2
            or type(repeats) is not int
            or not 2 <= repeats <= 20
            or not seeds
            or any(type(seed) is not int or seed < 0 for seed in seeds)
            or len(set(seeds)) != len(seeds)
            or not modes
            or any(mode not in ("basic", "multilevel") for mode in modes)
            or len(set(modes)) != len(modes)
            or workload
            not in (
                "uniform",
                "hub-churn",
                "power-law-churn",
                "power-law-burst-churn",
            )
            or type(hub_degree) is not int
            or (workload != "hub-churn" and hub_degree != 0)
            or (
                workload == "hub-churn"
                and not 1 <= hub_degree <= min(vertices - 6, 262144)
            )
        ):
            raise ValueError("invalid repeatability workload envelope")
        self.output = output
        self.vertices = vertices
        self.pairs = pairs
        self.batch = batch
        self.seeds = list(seeds)
        self.repeats = repeats
        self.modes = list(modes)
        self.workload = workload
        self.hub_degree = hub_degree
        self.script = Path(__file__).with_name("durable.py")

    def paths(self) -> list[tuple[str, int, int, Path, Path]]:
        """Return stable raw-result/database paths for the full run matrix."""
        result = []
        for mode in self.modes:
            for seed in self.seeds:
                for repetition in range(1, self.repeats + 1):
                    stem = f"{self.workload}-{mode}-seed-{seed}-run-{repetition}"
                    result.append(
                        (
                            mode,
                            seed,
                            repetition,
                            self.output / f"{stem}.json",
                            self.output / "databases" / f"{stem}.db",
                        )
                    )
        return result

    def preflight(self) -> list[tuple[str, int, int, Path, Path]]:
        """Reject all output collisions before launching any expensive sample."""
        paths = self.paths()
        occupied = [
            str(path)
            for _, _, _, result, database in paths
            for path in (
                result,
                database,
                Path(str(database) + "-wal"),
                Path(str(database) + "-shm"),
                Path(str(database) + "-journal"),
            )
            if path.exists()
        ]
        summary = self.output / "summary.json"
        if summary.exists():
            occupied.append(str(summary))
        if occupied:
            raise FileExistsError(
                "repeat output paths already exist: " + ", ".join(occupied)
            )
        return paths

    def sample(self, mode: str, seed: int, database: Path) -> dict[str, Any]:
        """Run one isolated benchmark process and validate its JSON contract."""
        command = [
            sys.executable,
            str(self.script),
            "--database",
            str(database),
            "--vertices",
            str(self.vertices),
            "--pairs",
            str(self.pairs),
            "--batch",
            str(self.batch),
            "--seed",
            str(seed),
            "--mode",
            mode,
            "--workload",
            self.workload,
            "--hub-degree",
            str(self.hub_degree),
        ]
        child = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        try:
            value = json.loads(child.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("durable benchmark emitted invalid JSON") from error
        required = (
            "paper_mode",
            "seed",
            "workload",
            "workload_metadata",
            "trace_digest",
            "matching_digest",
            "real_acknowledged_updates_per_second",
            "acknowledged_latency",
            "batch_commit_publication_latency",
            "process_peak_rss_bytes",
            "recovery_seconds",
            "independent_audit_passed",
            "exact_recovery_passed",
        )
        if (
            type(value) is not dict
            or any(key not in value for key in required)
            or value["paper_mode"] != mode
            or value["seed"] != seed
            or value["workload"] != self.workload
            or type(value["workload_metadata"]) is not dict
            or (
                self.workload == "power-law-burst-churn"
                and (
                    value["workload_metadata"].get("burst_period_pairs") != 16
                    or value["workload_metadata"].get("burst_hot_pairs_per_period")
                    != 12
                    or type(value["workload_metadata"].get("burst_hot_pool_pairs"))
                    is not int
                )
            )
            or (
                self.workload in ("power-law-churn", "power-law-burst-churn")
                and (
                    value["workload_metadata"].get("endpoint_distribution")
                    != "truncated-pareto-integer-rank"
                    or value["workload_metadata"].get("powerlaw_exponent") != 2.5
                    or type(
                        value["workload_metadata"].get(
                            "powerlaw_top_decile_endpoint_share"
                        )
                    )
                    not in (int, float)
                    or not 0
                    <= value["workload_metadata"]["powerlaw_top_decile_endpoint_share"]
                    <= 1
                )
            )
            or value["independent_audit_passed"] is not True
            or value["exact_recovery_passed"] is not True
        ):
            raise RuntimeError("durable benchmark result failed its output contract")
        return value

    def summarize(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        """Summarize repeat spread while enforcing same-seed determinism."""
        modes = {}
        for mode in self.modes:
            selected = [sample for sample in samples if sample["paper_mode"] == mode]
            traces: dict[int, set[tuple[str, str]]] = {}
            for sample in selected:
                traces.setdefault(sample["seed"], set()).add(
                    (sample["trace_digest"], sample["matching_digest"])
                )
            if any(len(digests) != 1 for digests in traces.values()):
                raise RuntimeError(
                    f"same-seed deterministic digests disagree in mode {mode}"
                )
            environments = {
                (sample["python"], sample["platform"], sample["sqlite"])
                for sample in selected
            }
            if len(environments) != 1:
                raise RuntimeError(
                    f"benchmark environment changed during {mode} repeats"
                )
            environment = next(iter(environments))
            workloadmetadata: dict[int, set[str]] = {}
            for sample in selected:
                workloadmetadata.setdefault(sample["seed"], set()).add(
                    json.dumps(sample["workload_metadata"], sort_keys=True)
                )
            if any(len(values) != 1 for values in workloadmetadata.values()):
                raise RuntimeError(
                    f"workload metadata changed during {mode} same-seed repeats"
                )

            def spread(values: list[float]) -> dict[str, float]:
                return {
                    "median": statistics.median(values),
                    "minimum": min(values),
                    "maximum": max(values),
                }

            percentiles = {}
            for field in ("p50_ns", "p95_ns", "p99_ns", "p999_ns"):
                observed = [
                    sample["acknowledged_latency"][field]
                    for sample in selected
                    if sample["acknowledged_latency"][field] is not None
                ]
                if observed:
                    percentiles[field] = spread(observed)
            commit = {}
            for field in ("p50_ns", "p95_ns", "p99_ns", "p999_ns"):
                observed = [
                    sample["batch_commit_publication_latency"][field]
                    for sample in selected
                    if sample["batch_commit_publication_latency"][field] is not None
                ]
                if observed:
                    commit[field] = spread(observed)
            queries = {}
            for field in ("p50_ns", "p95_ns", "p99_ns", "p999_ns"):
                observed = [
                    sample["partner_query_latency"][field]
                    for sample in selected
                    if sample["partner_query_latency"][field] is not None
                ]
                if observed:
                    queries[field] = spread(observed)
            modes[mode] = {
                "sample_count": len(selected),
                "workload_metadata_by_seed": {
                    str(seed): json.loads(next(iter(values)))
                    for seed, values in sorted(workloadmetadata.items())
                },
                "environment": {
                    "python": environment[0],
                    "platform": environment[1],
                    "sqlite": environment[2],
                },
                "throughput_updates_per_second": spread(
                    [
                        sample["real_acknowledged_updates_per_second"]
                        for sample in selected
                    ]
                ),
                "acknowledgment_latency": percentiles,
                "batch_commit_latency": commit,
                "partner_query_latency": queries,
                "process_peak_rss_bytes": spread(
                    [sample["process_peak_rss_bytes"] for sample in selected]
                ),
                "recovery_seconds": spread(
                    [sample["recovery_seconds"] for sample in selected]
                ),
                "same_seed_digests_verified": {
                    str(seed): next(iter(digests))
                    for seed, digests in sorted(traces.items())
                },
            }
        return {
            "scope": "fresh-process durable repeatability diagnostics; not a qualification threshold",
            "vertices": self.vertices,
            "pairs": self.pairs,
            "batch": self.batch,
            "workload": self.workload,
            "workload_metadata_by_seed": next(iter(modes.values()))[
                "workload_metadata_by_seed"
            ]
            if modes
            else {},
            "hub_degree": self.hub_degree,
            "seeds": self.seeds,
            "repeats_per_seed": self.repeats,
            "modes": modes,
        }

    def run(self) -> dict[str, Any]:
        """Execute all samples sequentially, preserve raw JSON, and write summary."""
        paths = self.preflight()
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "databases").mkdir(exist_ok=True)
        samples = []
        for mode, seed, repetition, result_path, database in paths:
            result = self.sample(mode, seed, database)
            result["repeat"] = repetition
            result_path.write_text(json.dumps(result, indent=2) + "\n")
            samples.append(result)
        summary = self.summarize(samples)
        (self.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary


def main() -> None:
    """Run fresh-process repeats for the selected deterministic workload."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=32_000)
    parser.add_argument("--pairs", type=int, default=512)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--seeds", type=int, nargs="+", default=[599, 600, 601])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--mode", choices=("basic", "multilevel", "both"), default="both"
    )
    parser.add_argument(
        "--workload",
        choices=("uniform", "hub-churn", "power-law-churn", "power-law-burst-churn"),
        default="uniform",
    )
    parser.add_argument("--hub-degree", type=int)
    args = parser.parse_args()
    modes = ["basic", "multilevel"] if args.mode == "both" else [args.mode]
    hub_degree = args.hub_degree
    if hub_degree is None:
        hub_degree = 65536 if args.workload == "hub-churn" else 0
    summary = Repeatability(
        args.output,
        vertices=args.vertices,
        pairs=args.pairs,
        batch=args.batch,
        seeds=args.seeds,
        repeats=args.repeats,
        modes=modes,
        workload=args.workload,
        hub_degree=hub_degree,
    ).run()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
