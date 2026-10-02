"""Offered arrivals cannot count missed/rejected work as delivered updates."""

import threading

import pytest

from axiom.durable import Durable
from axiom.service import Service
from benchmarks import overload
from benchmarks.overload import Schedule, measure


def test_schedule_reports_missed_slots_without_unbounded_catch_up(monkeypatch):
    times = iter([0, 250000000, 300000000, 1000000000])
    monkeypatch.setattr(overload.time, "perf_counter_ns", lambda: next(times))
    schedule = Schedule(0, 10, 1, threading.Event())
    assert list(schedule) == [0, 200000000, 300000000]
    assert schedule.missed == 7 and schedule.total == 10


@pytest.mark.parametrize("rate", [3, 7, 11000])
@pytest.mark.parametrize("seconds", [1, 2])
def test_schedule_exact_rounded_deadlines_never_regress_or_repeat(
    monkeypatch, rate, seconds
):
    started = 23
    expected = [
        started + index * 1_000_000_000 // rate for index in range(rate * seconds)
    ]
    times = iter([*expected, started + seconds * 1_000_000_000])
    monkeypatch.setattr(overload.time, "perf_counter_ns", lambda: next(times))
    schedule = Schedule(started, rate, seconds, threading.Event())
    observed = list(schedule)
    assert observed == expected
    assert len(set(observed)) == schedule.total
    assert schedule.missed == 0


def test_schedule_skipping_to_a_rounded_deadline_reconciles_exactly(monkeypatch):
    times = iter([0, 666666666])
    monkeypatch.setattr(overload.time, "perf_counter_ns", lambda: next(times))
    schedule = Schedule(0, 3, 1, threading.Event())
    observed = list(schedule)
    assert observed == [0, 666666666]
    assert schedule.missed == 1
    assert len(observed) + schedule.missed == schedule.total


def test_offered_load_counts_all_outcomes_and_audits_exact_recovery(tmp_path):
    result = measure(
        tmp_path / "offered.db", 32, 10000, 1, query_rate=1000, queue_capacity=8
    )
    assert result["planned_update_offers"] == 10000
    assert (
        result["real_acknowledged_updates"]
        + result["busy_update_offers"]
        + result["producer_missed_update_slots"]
    ) == 10000
    assert (
        result["partner_queries"]
        + result["busy_query_offers"]
        + result["producer_missed_query_slots"]
    ) == 1000
    assert result["real_acknowledged_updates"] > 0
    assert result["service_metrics"]["peak_outstanding"] <= 8
    assert result["peak_client_receipts"] <= 264
    assert result["final_status"]["sequence"] == result["real_acknowledged_updates"]
    assert result["independent_exact_audit_and_recovery_passed"]


def test_blocked_durability_forces_busy_without_dropping_or_resequencing_accepted_work(
    tmp_path, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    persist, submit = Durable._persist, Service.submit
    calls = 0

    def paused(owner, rows):
        if not entered.is_set():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test durability release timed out")
        persist(owner, rows)

    def offered(service, request):
        nonlocal calls
        try:
            return submit(service, request)
        finally:
            calls += 1
            if calls == 2:
                assert entered.wait(5)
            if calls >= 32:
                release.set()

    monkeypatch.setattr(Durable, "_persist", paused)
    monkeypatch.setattr(Service, "submit", offered)
    try:
        result = measure(
            tmp_path / "blocked.db", 32, 10000, 1, query_rate=1000, queue_capacity=8
        )
    finally:
        release.set()
    assert result["busy_update_offers"] >= 24
    assert 7 <= result["service_metrics"]["peak_outstanding"] <= 8
    assert result["busy_query_offers"] == 0
    assert result["independent_exact_audit_and_recovery_passed"]


@pytest.mark.parametrize(
    "options",
    [
        {"vertices": 9},
        {"rate": 0},
        {"seconds": 0},
        {"query_rate": 0},
        {"queue_capacity": 1},
        {"seconds": True},
        {"seconds": 1.5},
    ],
)
def test_invalid_offered_envelope_never_creates_store(tmp_path, options):
    settings = dict(vertices=32, rate=100, seconds=1)
    settings.update(options)
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        measure(path, **settings)
    assert not path.exists()
