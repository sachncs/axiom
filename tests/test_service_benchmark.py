"""Verify streaming measurement counts, query queuing and independent recovery."""

from pathlib import Path

import pytest

from benchmarks.service import Histogram, measure


def test_histogram_is_bounded_and_never_hides_percentile_overflow() -> None:
    histogram = Histogram()
    assert histogram.summary()["p99_upper_ns"] is None
    for _ in range(1000):
        histogram.record(120001)
    assert len(histogram.bins) == 10001
    assert histogram.summary()["p99_upper_ns"] == 200000
    other = Histogram()
    for _ in range(20):
        other.record(2_000_000_000)
    histogram.merge(other)
    summary = histogram.summary()
    assert summary["count"] == 1020 and summary["overflow_at_1s"] == 20
    assert summary["p99_upper_ns"] is None and summary["max_ns"] == 2_000_000_000


def test_streaming_concurrent_trace_counts_real_acks_queries_and_checkpoints(
    tmp_path: Path,
) -> None:
    result = measure(
        tmp_path / "benchmark.db",
        64,
        200,
        599,
        clients=2,
        window=16,
        query_window=16,
        queue_capacity=64,
        checkpoint_interval=64,
    )
    assert result["real_acknowledged_updates"] == 400
    assert result["partner_queries"] >= 200
    assert result["acknowledged_latency"]["count"] == 400
    assert result["query_queue_wait"]["count"] == result["partner_queries"]
    assert result["service_metrics"]["peak_outstanding"] <= 64
    assert result["service_metrics"]["largest_group"] <= 256
    assert result["final_status"]["checkpoint_generation"] >= 2
    assert result["independent_audit_passed"] and result["exact_recovery_passed"]
    assert "NOT open-loop overload/power-cut" in result["scope"]


def test_duration_stops_admission_then_drains_and_audits_actual_completed_prefix(
    tmp_path: Path,
) -> None:
    result = measure(
        tmp_path / "duration.db",
        64,
        100000,
        599,
        clients=1,
        window=16,
        query_window=16,
        queue_capacity=32,
        checkpoint_interval=64,
        duration_seconds=1,
        timeout_seconds=11,
    )
    assert 0 < result["real_acknowledged_updates"] < 200000
    assert result["requested_duration_completed"]
    assert result["partner_queries"] >= result["real_acknowledged_updates"] // 2
    assert result["final_status"]["sequence"] == result["real_acknowledged_updates"]
    assert result["independent_audit_passed"] and result["exact_recovery_passed"]


def test_update_trace_and_matching_do_not_depend_on_query_or_batch_schedule(
    tmp_path: Path,
) -> None:
    first = measure(
        tmp_path / "one.db",
        64,
        120,
        599,
        clients=1,
        window=16,
        query_window=8,
        queue_capacity=32,
        checkpoint_interval=64,
    )
    second = measure(
        tmp_path / "two.db",
        64,
        120,
        599,
        clients=2,
        window=8,
        query_window=16,
        queue_capacity=32,
        checkpoint_interval=64,
    )
    assert first["trace_digest"] == second["trace_digest"]
    assert first["matching_digest"] == second["matching_digest"]


@pytest.mark.parametrize(
    "options",
    [
        {"clients": 0},
        {"window": 3},
        {"query_window": 0},
        {"queue_capacity": 32},
        {"timeout_seconds": 0},
        {"duration_seconds": 0},
        {"duration_seconds": 3600},
        {"duration_seconds": 1, "timeout_seconds": 5},
    ],
)
def test_invalid_benchmark_envelope_does_not_create_store(
    tmp_path: Path, options: dict
) -> None:
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        measure(path, 64, 20, 599, **options)
    assert not path.exists()
