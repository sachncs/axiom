"""Count and independently certify the non-durable native measurement."""

import pytest

from benchmarks.engine import measure


def test_engine_measurement_certifies_churn_and_queries() -> None:
    result = measure(64, 40, 599, 1 << 20)
    assert result["real_updates"] == 80
    assert result["partner_queries"] == 40
    assert result["edges"] == 128 and result["average_degree"] == 4
    assert result["matched_deletes"] > 0
    assert result["independent_audit_passed"]
    assert result["real_updates_per_second"] > 0
    assert result["final_native_memory"]["active"] == 0
    assert "NO durable acknowledgments" in result["scope"]


@pytest.mark.parametrize(
    "vertices,pairs", [(7, 1), (64, 0), (64, 65), (1000000, 100001)]
)
def test_engine_measurement_bounds_trace_generation(vertices: int, pairs: int) -> None:
    with pytest.raises(ValueError):
        measure(vertices, pairs, 599, 1 << 20)
