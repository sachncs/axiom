"""Backup benchmark validates paper-mode state and retry durability."""

from pathlib import Path

import pytest

from benchmarks.backup import measure


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_backup_measurement_restores_exact_paper_state(tmp_path: Path, mode: str):
    result = measure(tmp_path / "source.db", tmp_path / "backup.db", 32, 8, mode=mode)

    assert result["mode"] == mode
    assert result["updates"] == 8
    assert result["exact_restore_passed"]
    assert result["retry_result_preserved"]
    assert result["source_status"]["sequence"] == 8
    assert result["source_status"]["mode"] == mode
    assert result["manifest"]["sequence"] == 8
    assert "not power-loss" in result["scope"]


@pytest.mark.parametrize(
    "vertices,updates,mode",
    [(4, 8, "basic"), (32, 0, "basic"), (32, 100_001, "basic"), (32, 8, "native")],
)
def test_invalid_measurement_leaves_paths_absent(tmp_path, vertices, updates, mode):
    source, destination = tmp_path / "source.db", tmp_path / "backup.db"

    with pytest.raises(ValueError):
        measure(source, destination, vertices, updates, mode=mode)

    assert not source.exists()
    assert not destination.exists()
