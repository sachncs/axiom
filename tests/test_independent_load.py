"""Independent offers must reconcile every loss class and bound accepted work."""

import errno
import threading

import pytest

from axiom.durable import Durable
from axiom.service import Service
from benchmarks import independent_load
from benchmarks.independent_load import measure


@pytest.mark.parametrize("ipc_batch", [1, 16])
def test_separate_producer_saturation_and_exact_recovery(
    tmp_path, monkeypatch, ipc_batch
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
            tmp_path / "independent.db",
            32,
            10000,
            1,
            queue_capacity=8,
            ipc_batch=ipc_batch,
        )
    finally:
        release.set()
    assert (
        (
            result["producer_missed_updates"]
            + result["ipc_dropped_updates"]
            + result["busy_updates"]
            + result["real_acknowledged_updates"]
        )
        == result["planned_updates"]
        == 10000
    )
    assert (
        (
            result["producer_missed_queries"]
            + result["ipc_dropped_queries"]
            + result["busy_queries"]
            + result["partner_queries"]
        )
        == result["planned_queries"]
        == 1000
    )
    assert result["busy_updates"] >= 24
    assert result["service_metrics"]["peak_outstanding"] <= 8
    assert result["peak_client_receipts"] <= 264
    assert result["independent_exact_audit_and_recovery_passed"]


@pytest.mark.parametrize("code", [errno.EAGAIN, errno.ENOBUFS])
@pytest.mark.parametrize("ipc_batch", [1, 2, 16])
def test_producer_counts_ipc_drops_separately_without_blocking(
    monkeypatch, code, ipc_batch
):
    class Schedule:
        def __init__(self, *args):
            self.missed = 2

        def __iter__(self):
            return iter([100, 200, 300])

    class Channel:
        def send(self, packet, flags):
            assert 0 < len(packet) <= independent_load._PACKET.size * ipc_batch
            raise OSError(code, "bounded IPC full")

        def close(self):
            pass

    class Report:
        def send(self, value):
            self.value = value

        def poll(self, timeout):
            return True

        def recv(self):
            return "drained"

        def close(self):
            pass

    report = Report()
    monkeypatch.setattr(independent_load, "Schedule", Schedule)
    independent_load._produce(Channel(), report, 0, 10, 10, 1, ipc_batch)
    assert report.value[:2] == ([[0, 3, 2], [0, 3, 2]], [])
    assert report.value[2] > 0


@pytest.mark.parametrize(
    "options",
    [
        {"vertices": True},
        {"vertices": 9},
        {"rate": 0},
        {"seconds": 0},
        {"seconds": True},
        {"seconds": 1801},
        {"query_rate": 0},
        {"queue_capacity": 1},
        {"ipc_bytes": 0},
        {"ipc_bytes": 65537},
        {"ipc_batch": 0},
        {"ipc_batch": 65},
    ],
)
def test_invalid_envelope_never_starts_process_or_creates_store(tmp_path, options):
    settings = dict(vertices=32, rate=100, seconds=1)
    settings.update(options)
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        measure(path, **settings)
    assert not path.exists()


def test_soak_duration_is_accepted_without_overwriting_existing_store(tmp_path):
    path = tmp_path / "existing.db"
    path.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="fresh database"):
        measure(path, 32, 11000, 1800)
    assert path.read_bytes() == b"preserve"
