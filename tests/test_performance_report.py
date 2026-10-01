from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.performance import Configuration, Runner

Report = pytest.importorskip("benchmarks.report", exc_type=ImportError).Report


@pytest.fixture
def measurements(tmp_path: Path) -> Path:
    results = [
        Runner().run(Configuration(8, "sparse", 4, "churn", mode, seed, 16, 1))
        for mode in ("basic", "recompute")
        for seed in (7, 19)
    ]
    (tmp_path / "metadata.json").write_text("{}")
    (tmp_path / "results.jsonl").write_text(
        "\n".join(json.dumps(result) for result in results)
    )
    return tmp_path


def test_report_keeps_algorithms_separate_and_pools_only_seed_samples(
    measurements: Path,
) -> None:
    report = Report([measurements])
    rows = report.aggregate()
    assert len(rows) == 2
    assert {row["mode"] for row in rows} == {"basic", "recompute"}
    for row in rows:
        assert row["seeds"] == 2
        assert row["insertcount"] == row["deletecount"] == 16
        assert row["ratemin"] <= row["rate"] <= row["ratemax"]
        assert row["insertmedian"] <= row["insertp99"] <= row["insertmaximum"]


def test_report_rejects_duplicate_cases(measurements: Path) -> None:
    with pytest.raises(ValueError, match="duplicate configuration"):
        Report([measurements, measurements])


def test_report_rejects_different_algorithm_traces(measurements: Path) -> None:
    path = measurements / "results.jsonl"
    results = [json.loads(line) for line in path.read_text().splitlines()]
    results[0]["digest"] = "different"
    path.write_text("\n".join(json.dumps(result) for result in results))
    with pytest.raises(ValueError, match="identical traces"):
        Report([measurements])


def test_report_excludes_failures_from_rates(measurements: Path) -> None:
    path = measurements / "results.jsonl"
    results = [json.loads(line) for line in path.read_text().splitlines()]
    failed = results[0]
    results[0] = {
        "status": "timeout",
        "configuration": failed["configuration"],
        "error": "deadline",
    }
    path.write_text("\n".join(json.dumps(result) for result in results))
    rows = Report([measurements]).aggregate()
    assert {row["mode"]: row["seeds"] for row in rows} == {"basic": 1, "recompute": 2}
