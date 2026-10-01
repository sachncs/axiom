"""Count real bootstrap edits, checkpoint/tail and independently restored state."""

import hashlib
from pathlib import Path

import pytest

from benchmarks.backup import measure


def test_backup_measurement_checks_complete_recovery_and_retry_state(tmp_path: Path):
    result = measure(tmp_path / "source.db", tmp_path / "backup.db", 32, 32772)
    assert result["bootstrap_real_updates"] == 32772
    assert result["source_status"]["checkpoint_generation"] == 1
    assert result["source_status"]["checkpoint_sequence"] == 32768
    assert result["manifest"]["sequence"] == 32772
    assert (
        result["independent_exact_restore_passed"] and result["retry_and_expiry_passed"]
    )
    assert (
        result["manifest"]["sha256"]
        == hashlib.sha256((tmp_path / "backup.db").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "vertices,updates", [(4, 40000), (32, 32768), (32, 40001), (32, 250004)]
)
def test_invalid_backup_measurement_does_not_create_files(tmp_path, vertices, updates):
    source, destination = tmp_path / "source.db", tmp_path / "backup.db"
    with pytest.raises(ValueError):
        measure(source, destination, vertices, updates)
    assert not source.exists() and not destination.exists()
