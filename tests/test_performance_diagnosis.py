from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.diagnose import Diagnosis
from benchmarks.performance import Churn, Shape


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_diagnosis_profiles_public_calls_and_checks_the_prepared_trace(
    mode: str,
) -> None:
    result = Diagnosis().measure(8, mode, 16, 7)
    assert result["digest"] == Churn().prepare(Shape(8, "sparse", 4), 7, 16).digest
    assert result["seconds"] > 0
    assert result["functions"]
    assert any(item["function"] == "insert" for item in result["functions"])
    assert any(item["function"] == "delete" for item in result["functions"])
    assert "not throughput evidence" in result["notice"]
    cumulative = [item["cumulativeseconds"] for item in result["functions"]]
    assert cumulative == sorted(cumulative, reverse=True)


def test_diagnosis_cli_preserves_the_complete_function_table(tmp_path: Path) -> None:
    output = tmp_path / "diagnosis.json"
    Diagnosis().run(
        ["--sizes", "4", "--modes", "basic", "--updates", "4", "--output", str(output)]
    )
    results = json.loads(output.read_text())
    assert len(results) == 1
    assert results[0]["vertices"] == 4
    assert results[0]["updates"] == 4


@pytest.mark.parametrize("arguments", [["--sizes", "1"], ["--updates", "0"]])
def test_diagnosis_rejects_invalid_input(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        Diagnosis().run(arguments)
    assert error.value.code == 2
