"""Fresh-process paper-mode repeatability runner tests."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.repeatability import Repeatability


def runner(output: Path) -> Repeatability:
    return Repeatability(
        output,
        vertices=64,
        pairs=4,
        batch=8,
        seeds=[599, 600],
        repeats=2,
        modes=["basic", "multilevel"],
        workload="uniform",
        hub_degree=0,
    )


def test_fresh_process_repeats_verify_digests_and_write_spread(
    tmp_path: Path,
) -> None:
    output = tmp_path / "repeat"
    result = runner(output).run()

    assert result["scope"].endswith("not a qualification threshold")
    assert result["modes"]["basic"]["sample_count"] == 4
    assert result["modes"]["multilevel"]["sample_count"] == 4
    for mode in ("basic", "multilevel"):
        values = result["modes"][mode]
        assert values["same_seed_digests_verified"]["599"]
        assert values["same_seed_digests_verified"]["600"]
        assert values["throughput_updates_per_second"]["minimum"] > 0
        assert (
            values["process_peak_rss_bytes"]["maximum"]
            >= values["process_peak_rss_bytes"]["minimum"]
        )
    assert (
        result["modes"]["basic"]["same_seed_digests_verified"]["599"][0]
        != result["modes"]["basic"]["same_seed_digests_verified"]["600"][0]
    )
    assert len(list(output.glob("*.json"))) == 9
    assert len(list((output / "databases").glob("*.db"))) == 8
    assert json.loads((output / "summary.json").read_text()) == json.loads(
        json.dumps(result)
    )


def test_preflight_rejects_collision_before_any_benchmark_launch(
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "summary.json").write_text("{}")
    with pytest.raises(FileExistsError, match="summary.json"):
        runner(output).run()
    assert not (output / "databases").exists()


@pytest.mark.parametrize("stdout", ["not json", "{}"])
def test_sample_rejects_malformed_or_incomplete_child_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    instance = runner(tmp_path / "sample")
    monkeypatch.setattr(
        "benchmarks.repeatability.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=stdout),
    )
    with pytest.raises(RuntimeError, match="invalid JSON|output contract"):
        instance.sample("basic", 599, tmp_path / "fresh.db")


def test_sample_propagates_child_process_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = runner(tmp_path / "sample")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(2, args[0], stderr="benchmark failed")

    monkeypatch.setattr("benchmarks.repeatability.subprocess.run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        instance.sample("basic", 599, tmp_path / "fresh.db")


def test_invalid_hub_envelope_is_rejected_before_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repeatability workload envelope"):
        Repeatability(
            tmp_path / "invalid",
            vertices=64,
            pairs=4,
            batch=8,
            seeds=[599],
            repeats=2,
            modes=["basic"],
            workload="hub-churn",
            hub_degree=60,
        )
    assert not (tmp_path / "invalid").exists()
