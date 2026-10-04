"""Component failures, exact data-flow references and safe destructive boundaries."""

import errno
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from axiom.durable import Durable, Request
from scripts import verify_resource_envelope as module
from scripts.verify_resource_envelope import (
    Audit,
    Cycle,
    Disk,
    Memory,
    Pressure,
    Volume,
)


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


def test_reference_verifies_real_updates_exact_topology_partners_and_retry(tmp_path):
    path = tmp_path / "graph.db"
    with Durable(path, n=8) as owner:
        owner.apply(
            [
                Request(seq, "delete" if seq % 2 else "insert", 0, 1)
                for seq in range(1, 5)
            ]
        )
        assert owner.check()
        partners = [owner.partner(vertex)[1] for vertex in range(8)]
        assert all(
            partner is None or (partner != vertex and partners[partner] == vertex)
            for vertex, partner in enumerate(partners)
        )
        assert all(
            partners[u] is not None or partners[v] is not None
            for u in range(8)
            for v in range(u + 1, 8)
            if owner.has_edge(u, v)[1]
        )
        digest = hashlib.sha256(
            b"".join(
                (partner if partner is not None else 0xFFFFFFFF).to_bytes(4, "little")
                for partner in partners
            )
        ).hexdigest()
    with Durable(path) as recovered:
        partners = [recovered.partner(vertex)[1] for vertex in range(8)]
        restored_digest = hashlib.sha256(
            b"".join(
                (partner if partner is not None else 0xFFFFFFFF).to_bytes(4, "little")
                for partner in partners
            )
        ).hexdigest()
        assert restored_digest == digest
        assert recovered.check()


@pytest.mark.parametrize(
    "vertices,sequence", [(True, 12), (9, 13), (8, 8), (8, 11), (8, True), (8, 40010)]
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
        module.Envelope(Volume(tmp_path), Cycle(8, 8)).launch()
    assert not list(tmp_path.iterdir())


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
            Audit(8, 4).verify(owner)


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
