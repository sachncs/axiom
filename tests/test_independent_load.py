"""Paper-mode workload benchmarks must certify updates and replay."""

import pytest

from benchmarks.independent_load import measure


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_measure_reports_durable_replay_and_real_rate(tmp_path, mode):
    result = measure(tmp_path / f"{mode}.db", 32, 12, mode=mode, batch=4)

    assert result["mode"] == mode
    assert result["updates"] == 12
    assert result["acknowledged_updates_per_second"] > 0
    assert result["recovery_audit_passed"]
    assert result["final_status"]["sequence"] == 12
    assert result["final_status"]["history_operations"] == 12
    assert "not network or power-loss" in result["scope"]


@pytest.mark.parametrize(
    "options",
    [
        {"vertices": 7},
        {"vertices": 9},
        {"updates": 0},
        {"updates": 1_000_001},
        {"batch": 257},
        {"mode": "native"},
    ],
)
def test_invalid_measurement_does_not_create_database(tmp_path, options):
    arguments = {"vertices": 32, "updates": 12}
    arguments.update(options)
    path = tmp_path / "invalid.db"

    with pytest.raises(ValueError):
        measure(path, **arguments)

    assert not path.exists()
