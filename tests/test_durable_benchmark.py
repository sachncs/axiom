"""Ensure durable rate labels count only real acknowledged changes."""

from pathlib import Path

import pytest

from benchmarks.durable import measure


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_bounded_paper_trace_has_exact_recovery_and_query_certificates(
    tmp_path: Path, mode: str
) -> None:
    result = measure(tmp_path / f"benchmark-{mode}.db", 64, 80, 16, 599, mode=mode)
    assert result["real_acknowledged_updates"] == 160
    assert result["partner_queries"] == 80
    assert result["edges"] == 128 and result["average_degree"] == 4
    assert result["independent_audit_passed"] and result["exact_recovery_passed"]
    assert result["synchronous"] == "FULL" and result["fullfsync"]
    assert result["paper_mode"] == mode
    assert result["operation_history_entries"] == 160
    assert "SQLite FULL-WAL" in result["scope"]


def test_multilevel_trace_reports_sqlite_and_paper_storage_separately(
    tmp_path: Path,
) -> None:
    result = measure(tmp_path / "multilevel.db", 64, 120, 16, 599, mode="multilevel")
    assert result["real_acknowledged_updates"] == 240
    assert result["paper_mode"] == "multilevel"
    assert result["initial_paper_graph_bytes"] > 0
    assert result["final_paper_graph_bytes"] > 0
    assert result["sampled_database_wal_shm_peak_bytes"] > 0
    assert result["independent_audit_passed"] and result["exact_recovery_passed"]
    assert "operation-log replay" in result["scope"]


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_hub_churn_profile_preloads_skew_and_recovers_exactly(
    tmp_path: Path, mode: str
) -> None:
    result = measure(
        tmp_path / f"hub-{mode}.db",
        128,
        32,
        8,
        599,
        mode=mode,
        workload="hub-churn",
        hub_degree=16,
    )

    assert result["workload"] == "hub-churn"
    assert result["hub_vertex"] == 0
    assert result["preloaded_hub_degree"] == 16
    assert result["churn_hub_pool_size"] == result["churn_pool_pairs"]
    assert result["preload_updates"] == 16
    assert result["initial_hub_degree"] == 20
    assert result["base_edges"] == 256
    assert result["edges"] == 272
    assert result["average_degree"] > 4
    assert result["real_acknowledged_updates"] == 64
    assert result["operation_history_entries"] == 80
    assert result["independent_audit_passed"] and result["exact_recovery_passed"]


@pytest.mark.parametrize(
    "vertices,workload,hub_degree",
    [
        (64, "invalid", 0),
        (64, "hub-churn", 0),
        (64, "hub-churn", 60),
        (64, "uniform", 1),
    ],
)
def test_benchmark_rejects_invalid_skew_profiles_before_creating_database(
    tmp_path: Path, vertices: int, workload: str, hub_degree: int
) -> None:
    path = tmp_path / "invalid-skew.db"
    with pytest.raises(ValueError):
        measure(
            path,
            vertices,
            8,
            8,
            599,
            workload=workload,
            hub_degree=hub_degree,
        )
    assert not path.exists()


def test_benchmark_accepts_the_production_batch_limit(
    tmp_path: Path,
) -> None:
    result = measure(tmp_path / "large-batch.db", 64, 8, 4096, 599, mode="multilevel")
    assert result["batch_limit"] == 4096
    assert result["real_acknowledged_updates"] == 16
    assert result["exact_recovery_passed"]


def test_benchmark_reports_tail_latency_quantiles_when_sample_count_supports_them(
    tmp_path: Path,
) -> None:
    result = measure(tmp_path / "quantiles.db", 64, 512, 256, 599, mode="basic")
    latency = result["acknowledged_latency"]
    assert latency["count"] == 1024
    assert latency["p50_ns"] <= latency["p95_ns"] <= latency["p99_ns"]
    assert latency["p99_ns"] <= latency["p999_ns"] <= latency["max_ns"]


@pytest.mark.parametrize(
    "n,pairs,batch",
    [(7, 8, 16), (64, 0, 16), (64, 8, 17), (64, 8, 4098)],
)
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
