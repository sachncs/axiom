"""Component failures, exact data-flow references and safe destructive boundaries."""

import errno
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from axiom.durable import Durable, Request
from scripts import verify_resource_envelope as module
from scripts.verify_resource_envelope import Audit, Disk, Memory, Pressure, Volume


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
    with Durable(tmp_path / "graph.db", n=8) as owner:
        owner.apply(
            [
                Request(seq, "delete" if seq % 2 else "insert", 0, 1)
                for seq in range(1, 5)
            ]
        )
        expected = hashlib.sha256(
            b"".join((vertex ^ 1).to_bytes(4, "little") for vertex in range(8))
        ).hexdigest()
        assert Audit(8, 4).verify(owner) == expected


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
        assert owner.status()["edges"] == 16 and owner.status()["matching"] == 4
        with pytest.raises(RuntimeError, match="topology"):
            Audit(8, 6).verify(owner)


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
