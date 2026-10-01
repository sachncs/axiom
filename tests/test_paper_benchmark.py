from __future__ import annotations

import json

import pytest

from benchmarks.paper import (
    Benchmark,
    Collision,
    Complete,
    Construction,
    Reduction,
    Scenario,
)


@pytest.mark.parametrize(
    "scenario",
    [Collision(), Construction(), Reduction(), Complete("dense"), Complete("star")],
)
def test_benchmarks_certify_each_fresh_sample(scenario: Scenario) -> None:
    first = scenario.measure(3, 2)
    second = scenario.measure(3, 1)
    assert first.checksum == second.checksum
    assert first.minimum <= first.median <= first.maximum
    assert first.peak > 0


def test_benchmark_rejects_an_incomplete_coloring() -> None:
    scenario = Complete("dense")
    workload = scenario.prepare(8)
    with pytest.raises(AssertionError, match="incomplete"):
        scenario.verify(workload)


def test_benchmark_cli_reports_reproducible_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert Benchmark().run(["--sizes", "2", "--repeats", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["results"]) == 4
    assert {sample["scenario"] for sample in result["results"]} == {
        "Collision",
        "Construction",
        "Complete",
        "Reduction",
    }


@pytest.mark.parametrize("arguments", [["--sizes", "0"], ["--repeats", "0"]])
def test_benchmark_cli_rejects_invalid_workloads(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        Benchmark().run(arguments)
    assert error.value.code == 2
