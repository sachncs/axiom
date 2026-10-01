from __future__ import annotations

import json
import random
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from axiom.graph import Adjacency
from benchmarks.performance import Bag, Configuration, Recompute, Runner, Shape, Suite


@pytest.mark.parametrize(
    "matching",
    [
        {(0, 1), (1, 2), (2, 3)},
        {(0, 3), (1, 2)},
        {(1, 0), (2, 3)},
    ],
)
def test_certificate_rejects_improper_matchings(matching: set[tuple[int, int]]) -> None:
    graph = Adjacency(4)
    for edge in ((0, 1), (1, 2), (2, 3)):
        graph.add_edge(*edge)
    engine = Recompute(graph)
    engine.matching = matching
    with pytest.raises(AssertionError, match="not proper"):
        engine.verify()


@pytest.mark.parametrize("family", ["sparse", "dense", "star", "bipartite"])
@pytest.mark.parametrize("workload", list(Runner.workloads))
def test_traces_are_deterministic_valid_and_algorithm_independent(
    family: str, workload: str
) -> None:
    shape = Shape(16, family, 4)
    generator = Runner.workloads[workload]()
    trace = generator.prepare(shape, 7, 64)
    assert trace == generator.prepare(shape, 7, 64)
    live = set(trace.initial)
    for operation, left, right in trace.operations:
        assert 0 <= left < right < shape.vertices
        if family == "star":
            assert left == 0
        if family == "bipartite":
            assert left < shape.vertices // 2 <= right
        if operation == "insert":
            assert ((left, right) in live) == (workload == "duplicate")
            live.add((left, right))
        else:
            assert ((left, right) not in live) == (workload == "absent")
            live.discard((left, right))
    if workload == "churn":
        assert len(trace.operations) == 64
        assert len(live) == len(trace.initial)
    if workload == "growth":
        assert len(trace.operations) == min(64, shape.capacity - len(trace.initial))
    if workload == "drain":
        assert len(trace.operations) == len(trace.initial)


def test_pool_swap_and_saturated_domain() -> None:
    pool = Bag(((0, 1), (0, 2), (0, 3)))
    pool.remove((0, 2))
    assert pool.values == [(0, 1), (0, 3)]
    assert pool.index == {(0, 1): 0, (0, 3): 1}
    assert Shape(4, "star", 2).absent(random.Random(7), pool) == (0, 2)
    pool.add((0, 2))
    with pytest.raises(ValueError, match="no absent"):
        Shape(4, "star", 2).absent(random.Random(7), pool)
    with pytest.raises(ValueError, match="already present"):
        pool.add((0, 2))


@pytest.mark.parametrize("mode", ["basic", "multilevel", "recompute"])
@pytest.mark.parametrize("workload", ["churn", "duplicate", "absent"])
def test_runner_certifies_separate_passes_and_keeps_noops_separate(
    mode: str, workload: str
) -> None:
    config = Configuration(8, "sparse", 4, workload, mode, 7, 32, 2)
    result = Runner().run(config)
    assert result["status"] == "ok"
    assert result["operations"] == 32
    assert len(result["batches"]) == 2
    assert result["initialization"]["count"] == 2
    assert len(result["samples"]) == 32
    assert result["throughput"] > 0
    assert result["memory"]["peak"] >= result["memory"]["initial"] > 0
    assert result["noop"] == (workload != "churn")
    assert (result["realrate"] == 0) == result["noop"]
    assert all(sample["real"] != result["noop"] for sample in result["samples"])
    if workload == "churn":
        assert result["counts"] == {"insert": 16, "delete": 16}
        assert result["counters"]["phase_rebuilds"] > 0
        assert result["latency"]["insert"]["count"] == 16
        assert result["latency"]["delete"]["count"] == 16
        boundary = "recompute" if mode == "recompute" else "phase"
        assert (
            result["latency"][boundary]["count"] == result["counters"]["phase_rebuilds"]
        )
        assert (
            result["latency"].get("matched-delete", {"count": 0})["count"]
            + result["latency"].get("unmatched-delete", {"count": 0})["count"]
            == 16
        )
    if mode != "recompute":
        assert result["queries"]["partner"]["count"] == 256
    else:
        assert not result["queries"]
        if workload == "churn":
            assert result["latency"]["recompute"]["count"] == 32
            assert "phase" not in result["latency"]
    assert (
        result["digest"]
        == Runner.workloads[workload]().prepare(Shape(8, "sparse", 4), 7, 32).digest
    )


def test_empirical_quantiles_and_empty_buckets() -> None:
    assert Runner.summarize([]) == {"count": 0}
    summary = Runner.summarize(list(range(1, 101)))
    assert summary == {
        "count": 100,
        "median": 50.5,
        "p95": 95,
        "p99": 99,
        "maximum": 100,
        "total": 5050,
    }


def test_cli_preserves_raw_data_and_metadata(tmp_path: Path) -> None:
    assert (
        Suite().run(
            [
                "--output",
                str(tmp_path),
                "--sizes",
                "4",
                "--profiles",
                "star",
                "--workloads",
                "churn",
                "--modes",
                "recompute",
                "--seeds",
                "7",
                "--updates",
                "4",
                "--repeats",
                "1",
            ]
        )
        == 0
    )
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["python"] and metadata["commit"] and metadata["clock"]
    result = json.loads((tmp_path / "results.jsonl").read_text())
    assert result["status"] == "ok"
    assert result["operations"] == 4
    assert (tmp_path / "summary.csv").read_text().startswith("vertices,family,")
    assert len((tmp_path / "latency.csv").read_text().splitlines()) == 5


def test_cli_records_timeouts_without_assigning_rates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("case", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    # check_output also uses run; preserve metadata collection via its own stub.
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "metadata")
    Suite().run(
        [
            "--output",
            str(tmp_path),
            "--sizes",
            "4",
            "--profiles",
            "star",
            "--workloads",
            "churn",
            "--modes",
            "basic",
            "--seeds",
            "7",
            "--updates",
            "4",
            "--repeats",
            "1",
            "--timeout",
            "1",
        ]
    )
    result = json.loads((tmp_path / "results.jsonl").read_text())
    assert result["status"] == "timeout"
    assert "throughput" not in result
    assert result["error"] == "case exceeded 1 seconds"


def test_case_worker_records_correctness_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(self: Runner, config: Configuration) -> dict:
        raise AssertionError("invalid certificate")

    monkeypatch.setattr(Runner, "run", fail)
    config = Configuration(4, "star", 2, "churn", "basic", 7, 4, 1)
    Suite().run(["--case", json.dumps(asdict(config))])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"
    assert "invalid certificate" in result["error"]
    assert "throughput" not in result


@pytest.mark.parametrize(
    "arguments",
    [
        ["--sizes", "1"],
        ["--updates", "0"],
        ["--repeats", "0"],
        ["--timeout", "0"],
        ["--profiles", "unknown"],
    ],
)
def test_cli_rejects_invalid_settings(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        Suite().run(arguments)
    assert error.value.code == 2
