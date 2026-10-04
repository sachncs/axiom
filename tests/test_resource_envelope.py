"""Component failures, exact data-flow references and safe destructive boundaries."""

import errno
import os
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from axiom.durable import MAX_BATCH, Durable, Request
from scripts import verify_resource_envelope as module
from scripts.verify_resource_envelope import (
    Audit,
    Cycle,
    Disk,
    Maintenance,
    Memory,
    Pressure,
    Volume,
)

SQLITEFULL = getattr(sqlite3, "SQLITE_FULL", 13)


def mounted(tmp_path, monkeypatch, capacity=192 << 20):
    original = Path.stat

    def stat(path, **options):
        result = original(path, **options)
        if path == tmp_path:
            fields = list(result)
            fields[2] = result.st_dev + 1
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(
        module.os,
        "statvfs",
        lambda path: SimpleNamespace(f_blocks=capacity // 4096, f_frsize=4096),
    )
    return Volume(tmp_path)


def test_volume_requires_dedicated_mount_before_any_pressure_write(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(module.sys, "platform", "linux")
    volume = Volume(tmp_path)
    for action in (volume.inspect, volume.fill):
        with pytest.raises(ValueError, match="dedicated"):
            action()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("capacity", [32 << 20, 512 << 20])
def test_volume_rejects_unqualified_filesystem_size(tmp_path, monkeypatch, capacity):
    volume = mounted(tmp_path, monkeypatch, capacity)
    with pytest.raises(ValueError, match="between"):
        volume.fill()
    assert not list(tmp_path.iterdir())


def test_volume_rejects_populated_and_symlink_paths(tmp_path, monkeypatch):
    volume = mounted(tmp_path, monkeypatch)
    assert volume.inspect() == 192 << 20
    graph = tmp_path / "graph.db"
    graph.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="fresh"):
        volume.inspect()
    assert volume.inspect(False) == 192 << 20
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        Volume(alias).fill()
    assert graph.read_bytes() == b"preserve"


def test_failed_exclusive_creation_never_deletes_existing_ballast(
    tmp_path, monkeypatch
):
    volume = mounted(tmp_path, monkeypatch)
    ballast = tmp_path / "ballast"
    ballast.write_bytes(b"not ours")
    with pytest.raises(FileExistsError):
        volume.fill()
    volume.release()
    assert ballast.read_bytes() == b"not ours"
    assert volume.ballast is None


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EIO])
def test_volume_counts_partial_writes_and_preserves_unexpected_io_errors(
    tmp_path, monkeypatch, code
):
    volume = mounted(tmp_path, monkeypatch)

    class Writer:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, block):
            self.calls += 1
            if self.calls == 1:
                assert len(block) == 65536
                return 123
            raise OSError(code, "test pressure")

        def fileno(self):
            return 123

    monkeypatch.setattr(Path, "open", lambda *args, **options: Writer())
    monkeypatch.setattr(module.os, "fsync", lambda descriptor: None)
    if code == errno.ENOSPC:
        assert volume.fill() == 123
    else:
        with pytest.raises(OSError) as error:
            volume.fill()
        assert error.value.errno == errno.EIO
    assert volume.ballast == tmp_path / "ballast"
    volume.release()
    assert volume.ballast is None


@pytest.mark.parametrize("vertices,sequence", [(9, 4), (8, 3), (True, 4), (8, True)])
def test_invalid_reference_rejects_before_accessing_owner(vertices, sequence):
    with pytest.raises(ValueError):
        Audit(vertices, sequence).verify(None)


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_reference_verifies_real_updates_exact_topology_partners_and_retry(
    tmp_path, mode
):
    path = tmp_path / f"graph-{mode}.db"
    with Durable(path, n=8, mode=mode) as owner:
        owner.apply(
            [
                Request(seq, "delete" if seq % 2 else "insert", 0, 1)
                for seq in range(1, 5)
            ]
        )
        assert owner.check()
        digest = Audit(8, 4).verify(owner)
    with Durable(path, mode=mode) as recovered:
        assert Audit(8, 4).verify(recovered) == digest
        assert recovered.check()


def test_reference_reads_exact_state_in_bounded_version_pinned_batches(
    tmp_path, monkeypatch
):
    from axiom.durable import MAX_READS

    path = tmp_path / "batched-audit.db"
    with Durable(path, n=8) as owner:
        owner.apply(
            [
                Request(seq, "delete" if seq % 2 else "insert", 0, 1)
                for seq in range(1, 5)
            ]
        )
        original = owner.read_snapshot
        calls = []

        def snapshot(vertices, edges, *, expected_version=None):
            calls.append((len(vertices) + len(edges), expected_version))
            return original(vertices, edges, expected_version=expected_version)

        monkeypatch.setattr(owner, "read_snapshot", snapshot)
        digest = Audit(8, 4).verify(owner)

        assert len(digest) == 64
        assert len(calls) < 8
        assert all(size <= MAX_READS for size, _ in calls)
        assert {version for _, version in calls} == {5}
        assert sum(size for size, _ in calls) == 8 + 8 + 16


@pytest.mark.parametrize("corruption", ["nonperfect", "missingedge"])
def test_reference_rejects_malformed_snapshot_state(tmp_path, monkeypatch, corruption):
    path = tmp_path / f"malformed-{corruption}.db"
    with Durable(path, n=8) as owner:
        owner.apply(
            [
                Request(seq, "delete" if seq % 2 else "insert", 0, 1)
                for seq in range(1, 5)
            ]
        )
        original = owner.read_snapshot
        changed = False

        def snapshot(vertices, edges, *, expected_version=None):
            nonlocal changed
            result = original(vertices, edges, expected_version=expected_version)
            if changed or not vertices and not edges:
                return result
            if corruption == "missingedge" and not edges:
                return result
            changed = True
            if corruption == "nonperfect" and vertices:
                partners = list(result.partners)
                counterpart = partners[0]
                partners[0] = partners[counterpart] = None
                return replace(result, partners=tuple(partners))
            if corruption == "missingedge" and edges:
                edge_state = list(result.has_edges)
                edge_state[0] = False
                return replace(result, has_edges=tuple(edge_state))
            return result

        monkeypatch.setattr(owner, "read_snapshot", snapshot)
        message = "perfect matching" if corruption == "nonperfect" else "proper"
        with pytest.raises(RuntimeError, match=message):
            Audit(8, 4).verify(owner, retry=False)


@pytest.mark.parametrize("committed", [False, True])
def test_full_volume_update_retries_same_id_from_either_commit_prefix(
    tmp_path, monkeypatch, committed
):
    from axiom.durable import Outcome, UnavailableError
    from axiom.service import Service

    path = tmp_path / "update-full.db"
    reference = Audit(8, 4)
    with Durable(path, n=8) as owner:
        owner.apply(
            [
                Request(sequence, "delete" if sequence % 2 else "insert", 0, 1)
                for sequence in range(1, 5)
            ]
        )
        digest = reference.verify(owner)

    volume = Volume(tmp_path)
    monkeypatch.setattr(Volume, "inspect", lambda self, fresh=True: 192 << 20)
    monkeypatch.setattr(Volume, "fill", lambda self: 4096)
    original_submit = Service.submit

    class FailedReceipt:
        def result(self, timeout=None):
            error = sqlite3.OperationalError("database or disk is full")
            error.sqlite_errorcode = SQLITEFULL
            raise error

    def submit(service, request):
        if committed:
            assert original_submit(service, request).result(5) == Outcome(5, False, 5)
        return FailedReceipt()

    def unavailable(*args, **kwargs):
        raise UnavailableError("injected uncertain commit")

    monkeypatch.setattr(Service, "submit", submit)
    monkeypatch.setattr(Service, "metrics", lambda self: {"state": "failed"})
    monkeypatch.setattr(Service, "partner", unavailable)
    monkeypatch.setattr(Service, "has_edge", unavailable)

    result = module.Disk(volume, reference).update(path, digest)

    assert result["update_sequence"] == 5
    assert result["update_written"] == 4096
    assert result["digest"] == digest
    assert result["verified"]
    with Durable(path) as recovered:
        assert recovered.status()["sequence"] == 5
        assert recovered.status()["version"] == 5
        assert recovered.apply([Request(5, "insert", 0, 1)]) == (Outcome(5, False, 5),)
        assert reference.verify(recovered, sequence=5, retry=False) == digest


def test_probe_verification_rejects_ambiguous_or_conflicting_sequences(tmp_path):
    path = tmp_path / "probe-sequence.db"
    reference = Audit(8, 4)
    with Durable(path, n=8) as owner:
        owner.apply(
            [
                Request(sequence, "delete" if sequence % 2 else "insert", 0, 1)
                for sequence in range(1, 5)
            ]
        )
        with pytest.raises(ValueError, match="outside one probe"):
            reference.verify(owner, sequence=6, retry=False)
        with pytest.raises(ValueError, match="baseline request"):
            reference.verify(owner, sequence=5)


@pytest.mark.parametrize(
    "vertices,sequence", [(True, 12), (9, 13), (8, 9), (8, 11), (8, True), (8, 40010)]
)
def test_cycle_invalid_reference_rejects_before_accessing_owner(vertices, sequence):
    with pytest.raises(ValueError, match="cycle"):
        Cycle(vertices, sequence).verify(None)


@pytest.mark.parametrize("reference", [Audit(8, 4), Cycle(8, 12)])
@pytest.mark.parametrize("sequence", [True, 0, -1, 99])
def test_resource_operation_rejects_out_of_range_sequences(reference, sequence):
    with pytest.raises(ValueError, match="sequence"):
        reference.operation(sequence)


def test_cycle_launcher_validates_reference_before_starting_pressure_worker(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Volume, "inspect", lambda volume: 192 << 20)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("invalid worker launched"),
    )
    with pytest.raises(ValueError, match="cycle"):
        module.Envelope(Volume(tmp_path), Cycle(8, 9)).launch()
    assert not list(tmp_path.iterdir())


def test_million_vertex_cycle_fits_the_durable_history_limit():
    from axiom.durable import MAX_OPERATIONS

    assert module.RESOURCE_HISTORY_LIMIT == MAX_OPERATIONS
    assert module.RESOURCE_BATCH <= MAX_BATCH
    reference = Cycle(1_000_000, 1_000_000)
    reference.inspect()

    assert reference.operation(1) == ("insert", 0, 500_000)
    assert reference.operation(500_000) == ("insert", 499_999, 999_999)
    assert reference.operation(500_001) == ("delete", 0, 500_000)
    assert reference.operation(1_000_000) == ("delete", 499_999, 999_999)


def test_cycle_verification_retries_the_final_committed_request(tmp_path):
    reference = Cycle(8, 8)
    with Durable(tmp_path / "cycle-retry.db", n=8, max_operations=16) as owner:
        owner.apply(
            [
                Request(sequence, *reference.operation(sequence))
                for sequence in range(1, reference.sequence + 1)
            ]
        )

        digest = reference.verify(owner)

        assert len(digest) == 64
        assert owner.status()["sequence"] == reference.sequence


@pytest.mark.parametrize("pages", [(0, 0), (5, 5)])
def test_maintenance_checks_service_status_checkpoint_and_paper_audit(pages):
    reference = Audit(8, 2)
    state = {
        "sequence": 2,
        "history_operations": 2,
        "version": 3,
        "vertices": 8,
        "edges": 16,
        "matching": 4,
        "max_operations": module.RESOURCE_HISTORY_LIMIT,
    }
    checkpoint = {
        "busy": 0,
        "wal_pages": pages[0],
        "checkpointed_pages": pages[1],
    }
    timeouts = []

    def resolved(value):
        return SimpleNamespace(result=lambda timeout: timeouts.append(timeout) or value)

    service = SimpleNamespace(
        status=lambda: resolved(state),
        checkpoint=lambda: resolved(checkpoint),
        check=lambda: resolved(True),
    )
    assert Maintenance(reference).verify(service) == state
    assert timeouts == [30, 30, module.RESOURCE_AUDIT_TIMEOUT]


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("history_operations", 1, "status differs"),
        ("busy", 1, "checkpoint is incomplete"),
        ("checkpointed_pages", 4, "checkpoint is incomplete"),
        ("wal_pages", "bad", "checkpoint is incomplete"),
        ("missing_wal", None, "checkpoint is incomplete"),
        ("wal_pages", -1, "checkpoint is incomplete"),
        ("audit", False, "graph audit failed"),
    ],
)
def test_maintenance_rejects_unverified_history_or_wal(field, value, message):
    reference = Audit(8, 2)
    state = {
        "sequence": 2,
        "history_operations": 2,
        "version": 3,
        "vertices": 8,
        "edges": 16,
        "matching": 4,
        "max_operations": module.RESOURCE_HISTORY_LIMIT,
    }
    checkpoint = {"busy": 0, "wal_pages": 5, "checkpointed_pages": 5}

    def resolved(result):
        return SimpleNamespace(result=lambda timeout: result)

    check = True
    if field == "audit":
        check = value
    elif field == "missing_wal":
        del checkpoint["wal_pages"]
    elif field in checkpoint:
        checkpoint[field] = value
    else:
        state[field] = value
    service = SimpleNamespace(
        status=lambda: resolved(state),
        checkpoint=lambda: resolved(checkpoint),
        check=lambda: resolved(check),
    )

    with pytest.raises(RuntimeError, match=message):
        Maintenance(reference).verify(service)


@pytest.mark.parametrize(
    "vertices,expected", [(256_000, 296_000), (1_000_000, 1_000_000)]
)
def test_growth_cli_caps_tail_at_durable_history_limit(
    vertices, expected, monkeypatch, tmp_path
):
    observed = []

    class CapturedCycle:
        def __init__(self, size, sequence):
            observed.extend((size, sequence))

    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "resource",
            "--directory",
            str(tmp_path),
            "--vertices",
            str(vertices),
            "--growth",
        ],
    )
    monkeypatch.setattr(module, "Cycle", CapturedCycle)
    monkeypatch.setattr(module.Envelope, "launch", lambda envelope: None)

    module.Envelope.cli()

    assert observed == [vertices, expected]


def test_envelope_launcher_forwards_the_selected_paper_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(Volume, "inspect", lambda volume: 192 << 20)
    launched = []
    monkeypatch.setattr(
        module.subprocess, "run", lambda command, **options: launched.append(command)
    )

    module.Envelope(Volume(tmp_path), Audit(8, 4), "multilevel").launch()

    assert len(launched) == 1
    assert launched[0][launched[0].index("--mode") + 1] == "multilevel"


@pytest.mark.parametrize("growth,timeout", [(False, 180), (True, 450)])
def test_launcher_preserves_deadline_headroom_for_resource_stages(
    tmp_path, monkeypatch, growth, timeout
):
    monkeypatch.setattr(Volume, "inspect", lambda volume: 192 << 20)
    launched = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **options: launched.append((command, options)),
    )
    audit = Cycle(8, 8) if growth else Audit(8, 4)

    module.Envelope(Volume(tmp_path), audit).launch()

    assert launched[0][1]["timeout"] == timeout


def test_envelope_rejects_an_unsupported_mode_before_worker_launch(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Volume, "inspect", lambda volume: 192 << 20)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **options: pytest.fail("invalid mode launched a worker"),
    )

    with pytest.raises(ValueError, match="mode must"):
        module.Envelope(Volume(tmp_path), Audit(8, 4), "native").launch()


@pytest.mark.parametrize("backend", ["owner", "service"])
@pytest.mark.parametrize("vertices", [8, 32])
def test_complete_cycle_each_edge_partner_and_retry_through_restart(
    tmp_path, backend, vertices
):
    from axiom.service import Service

    reference = Cycle(vertices, vertices + 4)
    reference.inspect()
    path = tmp_path / "cycle.db"
    graph = {
        tuple(sorted((u, (u + distance) % vertices)))
        for u in range(vertices)
        for distance in (1, 2)
    }
    initial = graph.copy()
    factory = (
        Durable(path, n=vertices, max_operations=100)
        if backend == "owner"
        else Service(path, n=vertices, max_operations=100, queue_capacity=8)
    )
    with factory as owner:
        for sequence in range(1, reference.sequence + 1):
            action, u, v = reference.operation(sequence)
            if action == "insert":
                assert (u, v) not in graph
                graph.add((u, v))
            else:
                assert (u, v) in graph
                graph.remove((u, v))
            request = Request(sequence, action, u, v)
            result = (
                owner.apply([request])[0]
                if backend == "owner"
                else owner.submit(request).result(5)
            )
            assert result.changed and result.version == sequence + 1
            state = owner.status() if backend == "owner" else owner.status().result(5)
            assert state["edges"] == len(graph)
            for a in range(vertices):
                partner = owner.partner(a)
                if backend == "service":
                    partner = partner.result(5)
                assert partner[0] == sequence + 1
                for b in range(a + 1, vertices):
                    present = owner.has_edge(a, b)
                    if backend == "service":
                        present = present.result(5)
                    assert present == (sequence + 1, (a, b) in graph)
            if sequence == vertices // 2:
                assert len(graph) == len(initial) + vertices // 2
            if sequence == vertices:
                assert graph == initial
    with Durable(path) as recovered:
        assert recovered.check()
        # A same-count substitution must be visible in the independently checked
        # edge set; matching identity is deliberately mode-dependent.
        recovered.apply(
            [
                Request(reference.sequence + 1, "insert", 0, vertices // 2),
                Request(reference.sequence + 2, "delete", 0, 2),
            ]
        )
        expected = {
            tuple(sorted((u, (u + distance) % vertices)))
            for u in range(vertices)
            for distance in (1, 2)
        }
        actual = {
            (u, v)
            for u in range(vertices)
            for v in range(u + 1, vertices)
            if recovered.has_edge(u, v)[1]
        }
        assert actual != expected


def test_reference_rejects_changed_topology_even_when_counts_and_matching_agree(
    tmp_path,
):
    with Durable(tmp_path / "graph.db", n=8) as owner:
        owner.apply(
            [
                Request(seq, "delete" if seq % 2 else "insert", 0, 1)
                for seq in range(1, 5)
            ]
            + [Request(5, "insert", 0, 4), Request(6, "delete", 0, 2)]
        )
        assert owner.status()["edges"] == 16
        expected_ring = {
            tuple(sorted((u, (u + distance) % 8)))
            for u in range(8)
            for distance in (1, 2)
        }
        actual_ring = {
            (u, v) for u in range(8) for v in range(u + 1, 8) if owner.has_edge(u, v)[1]
        }
        assert actual_ring != expected_ring


def test_reference_rejects_different_proper_perfect_matching(tmp_path):
    with Durable(tmp_path / "graph.db", n=8) as owner:
        owner.apply(
            [
                Request(1, "delete", 0, 1),
                Request(2, "delete", 2, 3),
                Request(3, "insert", 0, 1),
                Request(4, "insert", 2, 3),
            ]
        )
        assert owner.status()["edges"] == 16 and owner.status()["matching"] == 4
        assert owner.check()
        with pytest.raises(RuntimeError, match="matching"):
            Audit(8, 4, tuple(vertex ^ 1 for vertex in range(8))).verify(owner)


def test_memory_refuses_unbounded_execution_and_pressure_is_polymorphic(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(module.resource, "getrlimit", lambda kind: (-1, -1))
    pressure = Memory(Volume(tmp_path), Audit(8, 4))
    assert isinstance(pressure, Pressure)
    assert issubclass(Disk, Pressure)
    with pytest.raises(ValueError, match="enforced"):
        pressure.apply()
    assert not list(tmp_path.iterdir())


def test_memory_workload_allocates_distinct_edges_across_a_real_group():
    requests = Memory.requests(Request, 16386)

    assert len(requests) == 4096
    assert requests[0] == Request(3, "insert", 2, 5)
    assert requests[-1] == Request(4098, "insert", 16382, 16385)
    assert len({(request.u, request.v) for request in requests}) == len(requests)
    assert all(request.operation == "insert" for request in requests)
    assert all(
        (request.v - request.u) % 16386 not in (1, 2, 16384, 16385)
        for request in requests
    )
    with pytest.raises(ValueError, match="16,386"):
        Memory.requests(Request, 16384)


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_checkpoint_pressure_setup_retains_committed_wal_pages(tmp_path, mode):
    from axiom.durable import Outcome
    from axiom.service import Service

    path = tmp_path / f"checkpoint-pressure-{mode}.db"
    audit = Audit(256, 256)
    requests = tuple(
        Request(sequence, "delete" if sequence % 2 else "insert", 0, 1)
        for sequence in range(1, 257)
    )
    with Service(
        path,
        n=audit.vertices,
        mode=mode,
        max_batch=MAX_BATCH,
        max_operations=8192,
    ) as service:
        outcomes = service.submit_batch(requests).result(10)
        assert len(outcomes) == len(requests)
        assert all(outcome.changed for outcome in outcomes)
        assert outcomes[-1] == Outcome(256, True, 257)
        wal = path.with_name(path.name + "-wal")
        assert wal.is_file() and wal.stat().st_size > 32
        with path.open("rb") as database:
            header = database.read(100)
        page_size = int.from_bytes(header[16:18], "big")
        page_size = 65536 if page_size == 1 else page_size
        database_pages = path.stat().st_size // page_size
        frame_size = page_size + 24
        with wal.open("rb") as log:
            log.seek(32)
            transaction_pages = 0
            growth_commits = []
            while frame := log.read(frame_size):
                assert len(frame) == frame_size
                page_number = int.from_bytes(frame[:4], "big")
                committed_pages = int.from_bytes(frame[4:8], "big")
                transaction_pages = max(transaction_pages, page_number)
                if committed_pages:
                    growth_commits.append(
                        committed_pages > database_pages
                        and transaction_pages > database_pages
                    )
                    transaction_pages = 0
        assert growth_commits and growth_commits[-1]
        with sqlite3.connect(path) as verifier:
            assert verifier.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    with Durable(path, mode=mode) as recovered:
        assert audit.verify(recovered, retry=False)
        page = recovered.history(1, 256)
        assert page.latest_sequence == 256 and not page.has_more
        assert tuple(
            (record.sequence, record.operation, record.u, record.v, record.changed)
            for record in page.records
        ) == tuple(
            (request.sequence, request.operation, request.u, request.v, True)
            for request in requests
        )


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_checkpoint_disk_full_fail_stops_and_recovers_exact_history(
    tmp_path, monkeypatch, mode
):
    from axiom.durable import Durable, RecoveryError, UnavailableError
    from axiom.service import Service

    database = tmp_path / "checkpoint-failure.db"
    vertices = 8
    requests = (
        Request(1, "delete", 0, 1),
        Request(2, "insert", 0, 1),
    )
    with Durable(database, n=vertices, mode=mode) as owner:
        outcomes = owner.apply(requests)
        before_status = owner.status()
        before_partners = tuple(owner.partner(vertex) for vertex in range(vertices))

    original_db = Durable._db

    class FailingCheckpoint:
        def __init__(self, database):
            self.database = database

        def execute(self, statement, *parameters):
            if statement == "PRAGMA wal_checkpoint(PASSIVE)":
                error = sqlite3.OperationalError("database or disk is full")
                error.sqlite_errorcode = SQLITEFULL
                raise error
            return self.database.execute(statement, *parameters)

        def __getattr__(self, name):
            return getattr(self.database, name)

    monkeypatch.setattr(
        Durable,
        "_db",
        lambda owner: FailingCheckpoint(original_db(owner)),
    )
    service = Service(database, n=vertices, mode=mode)
    try:
        with pytest.raises(RecoveryError) as failure:
            service.checkpoint().result(10)
        assert isinstance(failure.value.__cause__, sqlite3.Error)
        assert failure.value.__cause__.sqlite_errorcode == SQLITEFULL
        assert service.metrics()["state"] == "failed"
        with pytest.raises(UnavailableError):
            service.partner(0).result(10)
    finally:
        service.close(10)

    with Durable(database, mode=mode) as recovered:
        assert recovered.status() == before_status
        assert tuple(recovered.partner(vertex) for vertex in range(vertices)) == (
            before_partners
        )
        assert recovered.check()
        history = recovered.history(1, 2)
        assert history.latest_sequence == before_status["sequence"]
        assert not history.has_more
        assert tuple(
            (record.sequence, record.operation, record.u, record.v, record.changed)
            for record in history.records
        ) == tuple(
            (outcome.sequence, request.operation, request.u, request.v, outcome.changed)
            for request, outcome in zip(requests, outcomes, strict=True)
        )


def test_service_update_qualification_reports_concurrent_partner_reads():
    from concurrent.futures import Future

    class Receipt:
        def __init__(self, result):
            self.value = result

        def result(self, timeout=None):
            return self.value

    class Service:
        def __init__(self):
            self.queried = threading.Event()
            self.query_count = 0

        def partner(self, vertex):
            self.query_count += 1
            self.queried.set()
            result = Future()
            result.set_result((self.query_count, (vertex + 1) % 8))
            return result

        def submit(self, request):
            from axiom.durable import Outcome

            assert self.queried.wait(5), "partner queries did not overlap updates"
            return Receipt(Outcome(request.sequence, True, request.sequence + 1))

        def metrics(self):
            return {"groups": 1, "largest_group": 1}

    service = Service()
    seconds, report = module.Envelope(None, Audit(8, 8)).update(service)

    assert seconds >= 0
    assert report["count"] == service.query_count > 0
    latency = report["latency_ms"]
    assert latency["minimum"] >= 0
    assert latency["mean"] >= 0
    assert latency["maximum"] >= latency["minimum"]
    assert latency["p50_upper_bound"] is not None
    assert latency["p95_upper_bound"] is not None
    assert latency["p99_upper_bound"] is not None
    assert latency["p999_upper_bound"] is not None
    assert sum(latency["bucket_counts"]) == report["count"]
    assert len(latency["bucket_counts"]) == len(latency["buckets_ms_upper_bounds"])


@pytest.mark.parametrize("failure", ["update", "query"])
def test_service_update_qualification_stops_query_worker_after_failure(
    monkeypatch, failure
):
    from concurrent.futures import Future

    workers = []
    worker_type = module.QueryWorker

    class TrackingWorker(worker_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)

    monkeypatch.setattr(module, "QueryWorker", TrackingWorker)

    class Receipt:
        def result(self, timeout=None):
            if failure == "update":
                raise OSError("durable update failed")
            from axiom.durable import Outcome

            return Outcome(1, True, 2)

    class Service:
        def __init__(self):
            self.queried = threading.Event()

        def partner(self, vertex):
            self.queried.set()
            result = Future()
            if failure == "query":
                result.set_exception(OSError("partner read failed"))
            else:
                result.set_result((0, (vertex + 1) % 8))
            return result

        def submit(self, request):
            assert self.queried.wait(5), "partner query did not start"
            return Receipt()

        def metrics(self):
            return {"groups": 1, "largest_group": 1}

    with pytest.raises((OSError, RuntimeError)):
        module.Envelope(None, Audit(8, 2)).update(Service())
    assert len(workers) == 1
    assert not workers[0].thread.is_alive()


@pytest.mark.parametrize("count", [0, None])
def test_volume_rejects_stalled_writes_and_releases_only_owned_file(
    tmp_path, monkeypatch, count
):
    volume = mounted(tmp_path, monkeypatch)
    graph = tmp_path / "graph.db"
    graph.write_bytes(b"acknowledged")

    class Writer:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, block):
            return count

    monkeypatch.setattr(Path, "open", lambda *args, **options: Writer())
    with pytest.raises(RuntimeError, match="no progress"):
        volume.fill()
    volume.release()
    volume.release()
    monkeypatch.undo()
    assert graph.read_bytes() == b"acknowledged"


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EIO])
def test_volume_flush_only_accepts_expected_capacity_failure(
    tmp_path, monkeypatch, code
):
    volume = mounted(tmp_path, monkeypatch)

    class Writer:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, block):
            raise OSError(errno.ENOSPC, "full")

        def fileno(self):
            return 123

    def flush(descriptor):
        assert descriptor == 123
        raise OSError(code, "flush failed")

    monkeypatch.setattr(Path, "open", lambda *args, **options: Writer())
    monkeypatch.setattr(module.os, "fsync", flush)
    if code == errno.ENOSPC:
        assert volume.fill() == 0
    else:
        with pytest.raises(OSError) as error:
            volume.fill()
        assert error.value.errno == errno.EIO
    volume.release()
    assert volume.ballast is None
