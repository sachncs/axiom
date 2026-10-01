"""Certificates and boundary validation for the native-only measurement."""

import pytest

from benchmarks.storage import measure


def test_storage_measurement_counts_real_updates_and_verifies_restoration() -> None:
    result = measure(33, 2, 20, 599, 1 << 20)
    assert result["vertices"] == 33 and result["edges"] == 66
    assert result["audit_passed"] is True
    assert result["trace_updates_per_second"] > 0
    assert result["final_native_memory"]["active"] == 0
    for metrics in result["operations"].values():
        assert metrics["real_updates"] == 20
        assert metrics["updates_per_second"] > 0
        assert metrics["max_ns"] >= metrics["p99_ns"] > 0


@pytest.mark.parametrize(
    "n,width,pairs", [(2, 1, 1), (8, 0, 1), (8, 4, 1), (8, 1, 0), (8, 1, 1000001)]
)
def test_storage_measurement_rejects_unbounded_or_invalid_trace(
    n: int, width: int, pairs: int
) -> None:
    with pytest.raises(ValueError):
        measure(n, width, pairs, 599, 1 << 20)
