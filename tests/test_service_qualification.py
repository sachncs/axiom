"""Focused tests for production-paper Service qualification accounting."""

import argparse
from pathlib import Path

import pytest

from axiom.durable import BusyError, Durable, Request
from axiom.service import Service
from benchmarks.service_qualification import (
    Latency,
    main,
    rate_value,
    run,
    validate,
)


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_small_run_counts_durable_transitions_and_reopens_exact_state(
    tmp_path: Path, mode: str
) -> None:
    result = run(
        tmp_path / f"{mode}.db",
        mode=mode,
        vertices=32,
        updates=24,
        rate=None,
        read_rate=100,
        seed=599,
    )
    assert result["offered"] == result["acknowledged_durable"] == 24
    assert result["accepted"] == 24
    assert result["failed"] == result["rejected"] == 0
    assert result["query_succeeded"] > 0
    assert result["query_failed"] == 0
    assert result["receipt_latency_ns"]["count"] == 24
    assert result["window"] == 64
    assert result["independent_reopen_verified"]
    assert result["scope"].startswith("PER-RUN SMOKE ONLY")
    assert result["service_initialization_seconds"] >= 0
    assert result["workload_seconds"] > 0
    assert result["end_to_end_seconds"] >= result["workload_seconds"]


@pytest.mark.parametrize(
    ("samples", "expected"),
    [([], None), ([3, 1, 2, 4], 4), ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 10)],
)
def test_latency_percentiles_use_nearest_rank(
    samples: list[int], expected: int | None
) -> None:
    histogram = Latency()
    for sample in samples:
        histogram.record(sample)
    result = histogram.summary()
    assert result["count"] == len(samples)
    p95 = None if expected is None else ((expected - 1) // 100_000 + 1) * 100_000
    assert result["p95_ns"] == p95
    assert result["max_ns"] == max(samples, default=None)


@pytest.mark.parametrize("value", ["max", "0.5", "12"])
def test_rate_parser_accepts_max_and_positive_rates(value: str) -> None:
    assert rate_value(value) == (None if value == "max" else float(value))


@pytest.mark.parametrize("value", ["0", "-2", "nan", "inf", "slow"])
def test_rate_parser_rejects_nonpositive_or_nonfinite_rates(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        rate_value(value)


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "native"},
        {"vertices": 7},
        {"vertices": True},
        {"updates": 0},
        {"updates": 1_000_001},
        {"vertices": 9, "updates": 9},
        {"rate": 0},
        {"read_rate": float("inf")},
        {"window": 0},
        {"window": 513},
        {"seed": -1},
        {"seed": True},
    ],
)
def test_validation_rejects_invalid_workloads(options: dict[str, object]) -> None:
    arguments: dict[str, object] = {
        "mode": "basic",
        "vertices": 32,
        "updates": 10,
        "rate": None,
        "read_rate": None,
        "seed": 599,
    }
    arguments.update(options)
    with pytest.raises(ValueError):
        validate(**arguments)  # type: ignore[arg-type]


def test_database_must_be_fresh(tmp_path: Path) -> None:
    path = tmp_path / "existing.db"
    path.touch()
    with pytest.raises(ValueError, match="fresh"):
        run(
            path,
            mode="basic",
            vertices=32,
            updates=1,
            rate=None,
            read_rate=None,
            seed=1,
        )


def test_rejected_update_is_not_counted_as_acknowledged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(self: Service, request: Request) -> None:
        raise BusyError("injected full admission queue")

    monkeypatch.setattr(Service, "submit", reject)
    result = run(
        tmp_path / "rejected.db",
        mode="basic",
        vertices=32,
        updates=5,
        rate=None,
        read_rate=None,
        seed=599,
    )
    assert result["offered"] == 1
    assert result["acknowledged_durable"] == 0
    assert result["failed"] == 0 and result["rejected"] == 1
    assert result["recovered_status"]["sequence"] == 0
    assert result["independent_reopen_verified"]


def test_rejection_drains_and_recovers_exact_inflight_acknowledged_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submit = Service.submit

    def reject_fourth(self: Service, request: Request):
        if request.sequence == 4:
            raise BusyError("injected rejection with three accepted updates")
        return submit(self, request)

    monkeypatch.setattr(Service, "submit", reject_fourth)
    path = tmp_path / "inflight-rejection.db"
    result = run(
        path,
        mode="basic",
        vertices=32,
        updates=8,
        rate=None,
        read_rate=100,
        seed=599,
        window=8,
    )
    assert result["offered"] == 4
    assert result["accepted"] == result["acknowledged_durable"] == 3
    assert result["rejected"] == 1 and result["failed"] == 0
    assert result["recovered_status"]["sequence"] == 3
    assert result["recovered_status"]["edges"] == 65
    with Durable(path, mode="basic") as restored:
        assert not restored.has_edge(0, 16)[1]
        assert restored.has_edge(1, 17)[1]


def test_failed_receipt_is_not_counted_as_durable_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailedReceipt:
        def result(self, timeout: float) -> None:
            raise RuntimeError("injected receipt failure")

    def fail(self: Service, request: Request) -> FailedReceipt:
        return FailedReceipt()

    monkeypatch.setattr(Service, "submit", fail)
    result = run(
        tmp_path / "failed.db",
        mode="basic",
        vertices=32,
        updates=5,
        rate=None,
        read_rate=None,
        seed=599,
    )
    assert result["offered"] == result["accepted"] == 5
    assert result["acknowledged_durable"] == 0
    assert result["failed"] == 5 and result["rejected"] == 0
    assert result["recovered_status"]["sequence"] == 0
    assert result["independent_reopen_verified"]


def test_synchronous_service_failure_is_not_misreported_as_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(self: Service, request: Request) -> None:
        raise RuntimeError("injected unavailable service")

    monkeypatch.setattr(Service, "submit", fail)
    result = run(
        tmp_path / "unavailable.db",
        mode="basic",
        vertices=32,
        updates=5,
        rate=None,
        read_rate=None,
        seed=599,
    )
    assert result["offered"] == 1
    assert result["acknowledged_durable"] == 0
    assert result["failed"] == 1 and result["rejected"] == 0
    assert result["recovered_status"]["sequence"] == 0
    assert result["independent_reopen_verified"]


def test_cli_requires_explicit_workload_fields() -> None:
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
