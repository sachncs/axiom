"""Publish controlled update measurements without pooling incompatible workloads.

Run ``python benchmarks/report.py benchmarks/results/pilot --output benchmarks/results/report``.
Charts require the optional ``benchmark`` dependencies; measurements do not.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from benchmarks.performance import Runner


class Report:
    """Aggregate seed replicates while preserving case failures and raw samples."""

    def __init__(self, directories: list[Path]) -> None:
        """Load completed case records and their environment provenance."""
        self.metadata = [
            json.loads((path / "metadata.json").read_text()) for path in directories
        ]
        self.results = [
            json.loads(line)
            for path in directories
            for line in (path / "results.jsonl").read_text().splitlines()
        ]
        self.groups: dict[tuple, list[dict]] = defaultdict(list)
        digests: dict[tuple, set[str]] = defaultdict(set)
        identities = set()
        for result in self.results:
            config = result["configuration"]
            identity = tuple(sorted(config.items()))
            if identity in identities:
                raise ValueError("duplicate configuration across input directories")
            identities.add(identity)
            if result["status"] != "ok":
                continue
            key = tuple(
                config[name]
                for name in (
                    "vertices",
                    "family",
                    "degree",
                    "workload",
                    "mode",
                    "updates",
                    "repeats",
                )
            )
            self.groups[key].append(result)
            tracekey = tuple(
                config[name]
                for name in (
                    "vertices",
                    "family",
                    "degree",
                    "workload",
                    "seed",
                    "updates",
                )
            )
            digests[tracekey].add(result["digest"])
        if any(len(values) != 1 for values in digests.values()):
            raise ValueError("algorithms did not replay identical traces")

    def aggregate(self) -> list[dict]:
        """Summarize median seed rates and pooled diagnostic latency quantiles."""
        rows = []
        for key, results in sorted(self.groups.items()):
            samples = [sample for result in results for sample in result["samples"]]
            rates = [result["throughput"] for result in results]
            row = dict(
                zip(
                    (
                        "vertices",
                        "family",
                        "degree",
                        "workload",
                        "mode",
                        "requested",
                        "repeats",
                    ),
                    key,
                    strict=True,
                )
            )
            row.update(
                {
                    "seeds": len(results),
                    "operations": results[0]["operations"],
                    "initialedges": results[0]["initialedges"],
                    "maximumdegree": max(result["maximumdegree"] for result in results),
                    "rate": statistics.median(rates),
                    "ratemin": min(rates),
                    "ratemax": max(rates),
                    "initializationms": statistics.median(
                        result["initialization"]["median"] for result in results
                    )
                    / 1e6,
                    "peakmib": statistics.median(
                        result["memory"]["peak"] for result in results
                    )
                    / 2**20,
                    "rssmib": statistics.median(
                        result["memory"]["rss"] for result in results
                    )
                    / 2**20,
                    "phases": sum(
                        result["counters"]["phase_rebuilds"] for result in results
                    )
                    if key[4] != "recompute"
                    else 0,
                    "subphases": sum(
                        result["counters"]["subphase_rebuilds"] for result in results
                    ),
                }
            )
            for operation in ("insert", "delete"):
                summary = Runner.summarize(
                    [
                        sample["nanoseconds"]
                        for sample in samples
                        if sample["operation"] == operation and sample["real"]
                    ]
                )
                for statistic in ("count", "median", "p95", "p99", "maximum"):
                    value = summary.get(statistic)
                    row[operation + statistic] = (
                        value if statistic == "count" or value is None else value / 1e6
                    )
            rows.append(row)
        return rows

    def charts(self, output: Path, rows: list[dict]) -> None:
        """Draw size scaling, latency distributions, and rebuild-boundary comparisons."""
        plt.rcParams.update(
            {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}
        )
        colors = {"basic": "#1968aa", "multilevel": "#c54e22", "recompute": "#29804d"}
        figure, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
        for axis, workload in zip(axes, ("growth", "drain", "churn"), strict=True):
            for mode, color in colors.items():
                selected = sorted(
                    [
                        row
                        for row in rows
                        if row["family"] == "sparse"
                        and row["degree"] == 4
                        and row["workload"] == workload
                        and row["mode"] == mode
                        and row["requested"] == 32
                    ],
                    key=lambda row: row["vertices"],
                )
                if selected:
                    axis.plot(
                        [row["vertices"] for row in selected],
                        [row["rate"] for row in selected],
                        "o-",
                        label=mode,
                        color=color,
                    )
                    axis.fill_between(
                        [row["vertices"] for row in selected],
                        [row["ratemin"] for row in selected],
                        [row["ratemax"] for row in selected],
                        color=color,
                        alpha=0.12,
                    )
            axis.set(
                xscale="log",
                yscale="log",
                xlabel="vertices",
                ylabel="real updates / second",
                title=workload,
            )
            axis.grid(alpha=0.2)
        axes[0].legend()
        figure.suptitle(
            "Sparse degree-target 4 · median seed rate · shaded observed seed range"
        )
        figure.savefig(output / "throughput.png", dpi=160)
        plt.close(figure)

        figure, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
        for axis, operation in zip(axes, ("insert", "delete"), strict=True):
            for mode, color in colors.items():
                values = sorted(
                    [
                        sample["nanoseconds"] / 1e6
                        for result in self.results
                        if result["status"] == "ok"
                        and result["configuration"]["vertices"] == 32
                        and result["configuration"]["family"] == "sparse"
                        and result["configuration"]["degree"] == 4
                        and result["configuration"]["workload"] == "churn"
                        and result["configuration"]["mode"] == mode
                        and result["configuration"]["updates"] >= 8192
                        for sample in result["samples"]
                        if sample["operation"] == operation
                    ]
                )
                if values:
                    axis.plot(
                        values,
                        [(index + 1) / len(values) for index in range(len(values))],
                        label=f"{mode} (n={len(values):,})",
                        color=color,
                    )
            axis.set(
                xscale="log",
                xlabel="call latency (ms)",
                ylabel="empirical cumulative probability",
                title=operation,
            )
            axis.legend()
            axis.grid(alpha=0.2)
        figure.suptitle(
            "Long sparse churn at 32 vertices · diagnostic pass, not batch throughput"
        )
        figure.savefig(output / "latency.png", dpi=160)
        plt.close(figure)

        figure, axis = plt.subplots(figsize=(9, 4), layout="constrained")
        labels, quantiles = [], []
        for mode in ("basic", "multilevel"):
            for boundary in ("ordinary", "subphase", "phase"):
                values = [
                    sample["nanoseconds"]
                    for result in self.results
                    if result["status"] == "ok"
                    and result["configuration"]["vertices"] == 32
                    and result["configuration"]["workload"] == "churn"
                    and result["configuration"]["family"] == "sparse"
                    and result["configuration"]["degree"] == 4
                    and result["configuration"]["updates"] >= 8192
                    and result["configuration"]["mode"] == mode
                    for sample in result["samples"]
                    if sample["boundary"] == boundary
                ]
                if values:
                    labels.append(f"{mode}\n{boundary}\n{len(values):,} calls")
                    quantiles.append(Runner.summarize(values)["p99"] / 1e6)
        axis.bar(
            labels, quantiles, color=[colors[label.splitlines()[0]] for label in labels]
        )
        axis.set(
            ylabel="empirical p99 latency (ms)",
            title="Rebuild boundaries · long sparse churn at 32 vertices",
        )
        axis.grid(axis="y", alpha=0.2)
        figure.savefig(output / "boundaries.png", dpi=160)
        plt.close(figure)

    def publish(self, output: Path) -> None:
        """Write aggregates, charts, and an answer-focused report with limitations."""
        output.mkdir(parents=True, exist_ok=True)
        rows = self.aggregate()
        if not rows:
            raise ValueError("no successful measurements")
        with (output / "aggregate.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.charts(output, rows)
        successful = sum(result["status"] == "ok" for result in self.results)
        lines = [
            "# Axiom dynamic-update performance",
            "",
            f"{successful:,}/{len(self.results):,} cases completed and passed correctness checks. Rates are machine- and workload-specific, not universal algorithmic bounds.",
            "",
            "## Environment",
            "",
        ]
        for metadata in self.metadata:
            args = metadata["arguments"]
            lines.append(
                f"- {metadata['started']}: Python {metadata['python']}, {metadata['platform']}; hardware {', '.join(metadata.get('hardware', [metadata['processor']]))}; commit `{metadata['commit']}`; dirty={metadata['dirty']}; sizes={args['sizes']}, updates={args['updates']}, repetitions={args['repeats']}, timeout={args['timeout']}s."
            )
        lines += [
            "",
            "Hardware entries above are CPU model, installed memory in bytes, and logical CPU count on macOS. Source SHA-256 hashes are recorded in each metadata file.",
            "",
            "## Real insertion, deletion, and mixed-update rates",
            "",
            "Median of the successful seed-specific batch rates, each based on fresh-state timed repetitions after one untimed warmup (normally three seeds and five repetitions). Min–max is observed seed variation, not a confidence interval. The table shows successful seed counts; blank/missing configurations are not zero throughput.",
            "",
            "| Vertices | Shape / degree target | Workload | Mode | Calls/trace | Seeds | Updates/s | Seed min–max | Init ms | Traced update peak MiB |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: |",
        ]
        for row in rows:
            if row["requested"] == 32 and row["workload"] in {
                "growth",
                "drain",
                "churn",
            }:
                lines.append(
                    f"| {row['vertices']} | {row['family']} / {row['degree']} | {row['workload']} | {row['mode']} | {row['operations']} | {row['seeds']} | {row['rate']:,.0f} | {row['ratemin']:,.0f}–{row['ratemax']:,.0f} | {row['initializationms']:.2f} | {row['peakmib']:.2f} |"
                )
        lines += [
            "",
            "![Throughput versus size](throughput.png)",
            "",
            "Growth means absent-edge insertions; drain means present-edge deletions. Both are finite, density-changing traces, not stationary rates. Churn alternates real deletion and insertion. Other workloads, no-ops, initial edge counts and maximum degrees are in `aggregate.csv`; no-op rates must not be compared with real-update rates.",
            "",
            "### No-op call rates (not real updates)",
            "",
            "Sparse degree-target 4, requested trace length 32. These calls leave the graph unchanged; they are excluded from real-update throughput.",
            "",
            "| Vertices | Mode | No-op workload | Successful seeds | Calls/s |",
            "| ---: | --- | --- | ---: | ---: |",
        ]
        for row in rows:
            if (
                row["requested"] == 32
                and row["family"] == "sparse"
                and row["degree"] == 4
                and row["workload"] in {"duplicate", "absent"}
            ):
                lines.append(
                    f"| {row['vertices']} | {row['mode']} | {row['workload']} | {row['seeds']} | {row['rate']:,.0f} |"
                )
        lines += [
            "",
            "## Long traces and tail latency",
            "",
            "Latencies are instrumented in a separate pass; counters and classification are read outside each timed call. Quantiles pool calls across seeds for one size, shape, mode, and trace length only. p99 is an empirical sample statistic, not a guaranteed tail bound; fewer than 10,000 samples per operation is explicitly preliminary. Phase categories count a call with both phase and subphase rebuilds as phase.",
            "",
            "| Vertices | Mode | Requested calls | Seeds | Updates/s | Insert samples | Insert median / p99 / max ms | Delete samples | Delete median / p99 / max ms | Phases / subphases |",
            "| ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |",
        ]
        for row in rows:
            if row["requested"] > 32 and row["workload"] == "churn":
                lines.append(
                    f"| {row['vertices']} | {row['mode']} | {row['requested']} | {row['seeds']} | {row['rate']:,.0f} | {row['insertcount']} | {row['insertmedian']:.3f} / {row['insertp99']:.3f} / {row['insertmaximum']:.3f} | {row['deletecount']} | {row['deletemedian']:.3f} / {row['deletep99']:.3f} / {row['deletemaximum']:.3f} | {row['phases']} / {row['subphases']} |"
                )
        lines += [
            "",
            "![Latency distributions](latency.png)",
            "",
            "![Boundary latency](boundaries.png)",
            "",
            "## Queries and deletion diagnostics",
            "",
        ]
        lines += [
            "Deletion diagnostics below use long 32-vertex sparse degree-target 4 churn traces only. Categories observe the matching immediately before deletion; scans are summed rematching-counter deltas.",
            "",
            "| Mode | Deletion category | Calls | Median ms | p99 ms | Scans |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for mode in ("basic", "multilevel"):
            for matched in (True, False):
                samples = [
                    sample
                    for result in self.results
                    if result["status"] == "ok"
                    and result["configuration"]["vertices"] == 32
                    and result["configuration"]["family"] == "sparse"
                    and result["configuration"]["degree"] == 4
                    and result["configuration"]["workload"] == "churn"
                    and result["configuration"]["updates"] >= 8192
                    and result["configuration"]["mode"] == mode
                    for sample in result["samples"]
                    if sample["operation"] == "delete" and sample["matched"] == matched
                ]
                summary = Runner.summarize(
                    [sample["nanoseconds"] for sample in samples]
                )
                if samples:
                    lines.append(
                        f"| {mode} | {'matched' if matched else 'unmatched'} | {len(samples):,} | {summary['median'] / 1e6:.3f} | {summary['p99'] / 1e6:.3f} | {sum(sample['scans'] for sample in samples):,} |"
                    )
        lines.append("")
        for mode in ("basic", "multilevel"):
            selected = [
                result
                for result in self.results
                if result["status"] == "ok"
                and result["configuration"]["vertices"] == 128
                and result["configuration"]["family"] == "sparse"
                and result["configuration"]["degree"] == 4
                and result["configuration"]["workload"] == "churn"
                and result["configuration"]["updates"] == 32
                and result["configuration"]["mode"] == mode
            ]
            if selected:
                text = "; ".join(
                    f"{query} {statistics.median(result['queries'][query]['median'] for result in selected) / 1e3:.2f} µs"
                    for query in selected[0]["queries"]
                )
                lines.append(
                    f"- {mode}, 128-vertex sparse final graph, median query latency: {text}. Each query has 256 calls per seed; clock and dispatch overhead matter for sub-microsecond calls."
                )
        lines += [
            "",
            "Matched/unmatched deletion samples, scan deltas, and individual boundary labels are retained in `latency.csv` and raw JSON. They are observations, not causal attribution: the same call may pay validation, snapshots, scans, and rebuild work.",
            "",
            "## Failures and time limits",
            "",
            "A timeout covers the entire case, including initialization, warmup, all throughput repetitions, instrumented latency, and traced memory. It does not establish that one update exceeded the timeout. Failed/timeout cases do not contribute rates.",
            "",
        ]
        failures: dict[tuple, int] = defaultdict(int)
        for result in self.results:
            if result["status"] != "ok":
                config = result["configuration"]
                failures[
                    (
                        config["vertices"],
                        config["family"],
                        config["mode"],
                        result["status"],
                        result["error"],
                    )
                ] += 1
        if failures:
            lines += [
                "| Vertices | Shape | Mode | Status | Cases | Reason |",
                "| ---: | --- | --- | --- | ---: | --- |",
            ]
            for key, count in sorted(failures.items()):
                lines.append(
                    f"| {key[0]} | {key[1]} | {key[2]} | {key[3]} | {count} | {key[4]} |"
                )
        else:
            lines.append("No failed or timed-out cases.")
        lines += [
            "",
            "## Measurement boundaries and limitations",
            "",
            "- Prepared traces and initial graph materialization are excluded from update throughput; matcher construction is measured separately. All public API transaction snapshots, invariant checks, graph scans, and rebuilds remain timed.",
            "- Fresh graphs and matchers are used for each repetition and pass. Correctness requires a proper maximal matching, the expected final graph, and identical final matching across repetitions of the same algorithm. Different algorithms need not choose identical matchings. Trace digests are checked across algorithms.",
            "- The baseline recomputes a greedy maximal matching after every real update; it uses the same trace but does not provide Axiom's transactional rollback or hierarchy guarantees. Its speed is a comparison, not an equivalent feature set.",
            "- Tracemalloc peak measures graph plus matcher allocations in a separate update pass after construction. Construction peak is separately in raw JSON. RSS is the isolated process lifetime high-water mark, including imports and prior passes, not current graph-only memory.",
            "- Finite growth/drain traces may end before the requested count. Short traces cannot characterize steady-state rebuild rates or reliable tails; consult actual operation and boundary counts.",
            "- Cases run sequentially, but this is a developer workstation: CPU frequency, thermal state, and unrelated applications were not controlled. No asymptotic complexity claim or statistically rigorous confidence interval follows from these measurements.",
            "",
            "Raw JSON includes every batch duration, latency sample, counter, query quantile, memory measurement, trace digest, and correctness certificate. CSV aggregates preserve graph family, size, degree target, workload, mode, sample count, and trace length.",
            "",
        ]
        (output / "report.md").write_text("\n".join(lines))


def main() -> None:
    """Render completed benchmark directories into one reproducible report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+")
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/results/report")
    )
    args = parser.parse_args()
    Report(args.directories).publish(args.output)


if __name__ == "__main__":
    main()
