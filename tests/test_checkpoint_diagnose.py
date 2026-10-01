"""Maintenance profiles must keep certificates, real edits and exact recovery."""

import pytest

from benchmarks.checkpoint_diagnose import measure


def test_profile_keeps_full_history_validation_and_exact_recovery(tmp_path):
    result = measure(tmp_path / "diagnostic.db", 32, 256)
    assert result["history_rows_validated"] == 256
    assert result["real_updates_before_checkpoint"] == 256
    assert result["status"]["synchronous"] == "FULL"
    assert result["status"]["fullfsync"] == 1
    assert result["checkpoint"]["generation"] == 1
    assert result["independent_exact_audit_and_recovery_passed"]
    functions = {item["function"]: item for item in result["functions"]}
    assert functions["_digest"]["calls"] == 256
    assert functions["_integer"]["calls"] == 6 * 256
    assert functions["_checkpoint_record"]["calls"] == 1
    assert functions["_persist_checkpoint"]["calls"] == 1


@pytest.mark.parametrize(
    "vertices,updates",
    [(True, 256), (9, 256), (32, True), (32, 255), (32, 49153)],
)
def test_invalid_profile_envelope_creates_no_database(tmp_path, vertices, updates):
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        measure(path, vertices, updates)
    assert not path.exists()


def test_profile_refuses_existing_database_without_modification(tmp_path):
    path = tmp_path / "existing.db"
    path.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="fresh"):
        measure(path, 32, 256)
    assert path.read_bytes() == b"preserve"
