"""Offered arrivals cannot count missed/rejected work as delivered updates."""

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from axiom.durable import Durable
from axiom.service import Service
from benchmarks import overload
from benchmarks.overload import Burst, PowerLaw, Schedule, measure


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


@pytest.mark.parametrize("rate", [3, 7, 11000])
def test_burst_exact_deadlines_and_second_boundary_never_duplicate(monkeypatch, rate):
    expected = [
        (index // rate) * 1_000_000_000 + (index % rate) * 1_000_000_000 // (4 * rate)
        for index in range(2 * rate)
    ]
    times = iter([*expected, 2_000_000_000])
    monkeypatch.setattr(overload.time, "perf_counter_ns", lambda: next(times))
    schedule = Burst(0, rate, 2, threading.Event())
    observed = list(schedule)
    assert observed == expected and len(set(observed)) == 2 * rate
    assert schedule.missed == 0
    assert observed[rate - 1] < 250000000 and observed[rate] == 1000000000


def test_burst_skips_late_slots_without_catchup_and_reconciles(monkeypatch):
    times = iter([0, 166666666, 1000000000, 1166666666])
    monkeypatch.setattr(overload.time, "perf_counter_ns", lambda: next(times))
    schedule = Burst(0, 3, 2, threading.Event())
    observed = list(schedule)
    assert observed == [0, 166666666, 1000000000, 1166666666]
    assert len(observed) + schedule.missed == schedule.total == 6
    assert schedule.missed == 2


def test_burst_quiet_window_waits_without_replaying_finished_slots(monkeypatch):
    class Clock:
        now = 0
        waits = []

        def is_set(self):
            return False

        def wait(self, seconds):
            self.waits.append(seconds)
            self.now += round(seconds * 1_000_000_000)

    clock = Clock()
    monkeypatch.setattr(overload.time, "perf_counter_ns", lambda: clock.now)
    schedule = Burst(0, 3, 2, clock)
    assert list(schedule) == [
        0,
        83333333,
        166666666,
        1000000000,
        1083333333,
        1166666666,
    ]
    assert schedule.missed == 0
    assert max(clock.waits) > 0.75


@pytest.mark.parametrize("policy", [Schedule, Burst])
def test_schedule_stop_during_wait_counts_all_unoffered_slots(monkeypatch, policy):
    class Stop(threading.Event):
        def wait(self, timeout=None):
            self.set()
            return True

    monkeypatch.setattr(overload.time, "perf_counter_ns", lambda: 0)
    schedule = policy(1000000000, 7, 2, Stop())
    assert list(schedule) == []
    assert schedule.missed == schedule.total == 14


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


def test_power_law_offered_workload_accounts_for_real_mutations_and_recovery(tmp_path):
    result = measure(
        tmp_path / "power-law.db",
        128,
        100,
        1,
        query_rate=20,
        queue_capacity=32,
        workload="power-law",
        seed=71,
        skew_edges=32,
    )
    assert result["workload"] == "power-law" and result["seed"] == 71
    assert result["power_law_exponent"] == 1.2
    assert result["bootstrap_updates"] == 64
    assert result["final_status"]["sequence"] == (
        result["bootstrap_updates"] + result["real_acknowledged_updates"]
    )
    assert result["real_acknowledged_updates"] > 0
    assert (
        result["real_insertions"] + result["real_deletions"]
        == result["real_acknowledged_updates"]
    )
    assert (
        result["acknowledged_latency"]["count"] == result["real_acknowledged_updates"]
    )
    assert (
        result["partner_queries"]
        + result["busy_query_offers"]
        + result["producer_missed_query_slots"]
        == result["planned_query_offers"]
    )
    assert (
        result["real_acknowledged_updates"]
        + result["busy_update_offers"]
        + result["producer_missed_update_slots"]
        == result["planned_update_offers"]
    )
    assert len(result["update_trace_digest"]) == 64
    assert result["independent_exact_audit_and_recovery_passed"]


def test_power_law_generator_is_seed_deterministic_and_degree_skewed():
    first, second = PowerLaw(256, 128, 599), PowerLaw(256, 128, 599)
    assert first.bootstrap() == second.bootstrap()
    assert first.wheel == second.wheel
    degrees = [4] * 256
    for u, v in first.bootstrap():
        degrees[u] += 1
        degrees[v] += 1
    assert max(degrees) > 10 * min(degrees[16:])
    actions = [first.request(index, index + 257) for index in range(100)]
    other_actions = [second.request(index, index + 257) for index in range(100)]
    assert actions == other_actions
    for (request, cell), (other, other_cell) in zip(
        actions, other_actions, strict=True
    ):
        first.commit(request, cell)
        second.commit(other, other_cell)
    assert first.digest.hexdigest() == second.digest.hexdigest()
    assert first.extras() == second.extras()


def test_power_law_rejected_offer_does_not_advance_toggle_or_trace():
    traffic = PowerLaw(128, 32, 599)
    before = traffic.digest.hexdigest()
    first, cell = traffic.request(0, 65)
    retry, same_cell = traffic.request(0, 65)
    assert first == retry and cell == same_cell
    assert traffic.active[cell]
    assert traffic.digest.hexdigest() == before
    traffic.commit(first, cell)
    assert not traffic.active[cell]
    assert traffic.digest.hexdigest() != before


def test_power_law_cli_exposes_bounded_options_and_emits_audited_json(tmp_path):
    database = tmp_path / "power-law-cli.db"
    runner = Path(__file__).resolve().parents[1] / "benchmarks" / "overload.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--database",
            str(database),
            "--vertices",
            "128",
            "--rate",
            "100",
            "--seconds",
            "1",
            "--query-rate",
            "10",
            "--queue-capacity",
            "32",
            "--workload",
            "power-law",
            "--seed",
            "71",
            "--skew-edges",
            "16",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = json.loads(completed.stdout)
    assert result["workload"] == "power-law"
    assert result["independent_exact_audit_and_recovery_passed"]
    assert len(result["graph_state_digest"]) == 64


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
        {"workload": "unknown"},
        {"workload": "power-law", "vertices": 32},
        {"workload": "power-law", "skew_edges": 0},
        {"workload": "power-law", "skew_edges": 8192, "vertices": 64},
    ],
)
def test_invalid_offered_envelope_never_creates_store(tmp_path, options):
    settings = dict(vertices=32, rate=100, seconds=1)
    settings.update(options)
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        measure(path, **settings)
    assert not path.exists()
