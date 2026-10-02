"""Independent offers must reconcile every loss class and bound accepted work."""

import errno
import threading

import pytest

from axiom.durable import CapacityError, Durable, Request
from axiom.service import Service
from benchmarks import independent_load
from benchmarks.independent_load import measure


@pytest.mark.parametrize("ipc_batch", [1, 16])
@pytest.mark.parametrize("workload", ["hot", "sweep"])
def test_separate_producer_saturation_and_exact_recovery(
    tmp_path, monkeypatch, ipc_batch, workload
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
            workload=workload,
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
    assert result["workload"] == workload


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
        {"workload": "unknown"},
        {"width": True},
        {"width": 3},
        {"width": 32},
        {"limit": True},
        {"limit": 0},
        {"limit": (1 << 30) + 1},
        {"budget": 0},
        {"budget": True},
        {"budget": (1 << 40) + 1},
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


@pytest.mark.parametrize("vertices", [True, 7, 9, 1000002])
def test_traffic_rejects_invalid_universe(vertices):
    with pytest.raises(ValueError, match="vertices"):
        independent_load.Sweep(vertices)


def test_sweep_pairing_wraparound_and_query_reference():
    traffic = independent_load.Sweep(8)
    expected = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 1)]
    assert [traffic.edge(2 * index + 1) for index in range(5)] == expected
    assert [traffic.edge(2 * index + 2) for index in range(5)] == expected
    assert [traffic.partner(version) for version in range(1, 12)] == [
        1,
        None,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        None,
        1,
    ]
    assert isinstance(traffic, independent_load.Traffic)


@pytest.mark.parametrize("count", [31, 32, 35])
@pytest.mark.parametrize("width", [2, 8, 32])
def test_sweep_reference_tracks_every_live_edit_and_exact_restart(
    tmp_path, count, width
):
    path = tmp_path / "sweep.db"
    vertices = 128 if width == 32 else 32
    traffic = independent_load.Sweep(vertices)
    with Durable(path, n=vertices, width=width) as owner:
        for sequence in range(1, count + 1):
            edge = traffic.edge(sequence)
            request = Request(sequence, "delete" if sequence % 2 else "insert", *edge)
            outcome = owner.apply([request])[0]
            assert outcome.changed and outcome.version == sequence + 1
            for vertex in range(vertices):
                assert owner.partner(vertex) == (
                    sequence + 1,
                    traffic.partner(sequence + 1, vertex),
                )
            assert owner.has_edge(*edge) == (sequence + 1, not sequence % 2)
        removed = {traffic.edge(count)} if count % 2 else set()
        digest = independent_load.certificate(owner, set(), removed, vertices, width)
        with pytest.raises(RuntimeError, match="edge count"):
            independent_load.certificate(owner, set(), removed, vertices, width + 1)
    with Durable(path) as recovered:
        assert (
            independent_load.certificate(recovered, set(), removed, vertices, width)
            == digest
        )


@pytest.mark.parametrize("width", [2, 8, 32])
def test_dense_independent_sweep_preserves_explicit_limits_and_exact_recovery(
    tmp_path, width
):
    result = measure(
        tmp_path / "dense.db",
        128,
        100,
        1,
        query_rate=100,
        workload="sweep",
        width=width,
        limit=1 << 20,
        budget=1 << 20,
    )
    assert result["width"] == width
    assert result["limits"] == {
        "native": 1 << 20,
        "snapshot": 1 << 20,
        "database": 1 << 20,
    }
    assert result["final_status"]["native_bytes"] <= 1 << 20
    assert result["final_status"]["edges"] == width * 128 - (
        result["real_acknowledged_updates"] % 2
    )
    assert result["independent_exact_audit_and_recovery_passed"]
    assert (
        result["real_acknowledged_updates"]
        + result["busy_updates"]
        + result["ipc_dropped_updates"]
        + result["producer_missed_updates"]
    ) == 100


@pytest.mark.parametrize("width", [True, 0, 16])
def test_invalid_certificate_width_rejects_before_owner_access(width):
    with pytest.raises(ValueError, match="width"):
        independent_load.certificate(None, set(), set(), 32, width)


def test_dense_image_cap_rejects_before_starting_producer(tmp_path, monkeypatch):
    started = []

    def forbidden(process):
        started.append(process)
        raise AssertionError("producer must not start after failed construction")

    monkeypatch.setattr(
        independent_load.multiprocessing.process.BaseProcess, "start", forbidden
    )
    with pytest.raises(CapacityError, match="checkpoint image capacity"):
        measure(
            tmp_path / "oversized.db",
            4096,
            100,
            1,
            width=32,
            limit=1 << 20,
            budget=16 << 20,
        )
    assert not started
    with Durable(tmp_path / "subsequent.db", n=128, width=32) as owner:
        outcome = owner.apply([Request(1, "delete", 0, 1)])[0]
        assert outcome.changed and owner.check()
