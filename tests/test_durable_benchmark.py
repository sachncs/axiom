"""Ensure durable rate labels count only real acknowledged changes."""

from pathlib import Path

import pytest

from benchmarks.durable import measure


def test_bounded_durable_trace_has_exact_recovery_and_query_certificates(
    tmp_path: Path,
) -> None:
    result = measure(tmp_path / "benchmark.db", 64, 80, 16, 599)
    assert result["real_acknowledged_updates"] == 160
    assert result["partner_queries"] == 80
    assert result["edges"] == 128 and result["average_degree"] == 4
    assert result["independent_audit_passed"] and result["exact_recovery_passed"]
    assert result["synchronous"] == "FULL" and result["fullfsync"]
    assert "NOT native checkpoint/soak" in result["scope"]


@pytest.mark.parametrize("n,pairs,batch", [(7, 8, 16), (64, 0, 16), (64, 8, 17)])
def test_benchmark_rejects_invalid_envelope_before_creating_database(
    tmp_path: Path,
    n: int,
    pairs: int,
    batch: int,
) -> None:
    path = tmp_path / "benchmark.db"
    with pytest.raises(ValueError):
        measure(path, n, pairs, batch, 599)
    assert not path.exists()
