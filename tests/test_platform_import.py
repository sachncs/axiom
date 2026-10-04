"""Platform boundaries for portable algorithms and POSIX-only durability."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest


def test_package_import_and_paper_modes_do_not_require_fcntl() -> None:
    script = textwrap.dedent(
        """
        import builtins

        original = builtins.__import__

        def without_fcntl(name, *args, **kwargs):
            if name == "fcntl":
                raise ModuleNotFoundError("fcntl is unavailable", name="fcntl")
            return original(name, *args, **kwargs)

        builtins.__import__ = without_fcntl

        import axiom
        from axiom import Matcher, Packed

        graph = Packed(4)
        graph.add_edge(0, 1)
        assert graph.has_edge(0, 1)
        for mode in ("basic", "multilevel"):
            matcher = Matcher(n=4, mode=mode)
            matcher.insert(0, 1)
            assert matcher.maximal()
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_durable_and_service_reject_non_posix_platforms(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import axiom.durable as durable
    from axiom.service import Service

    monkeypatch.setattr(durable.os, "name", "nt")
    with pytest.raises(ValueError, match="requires POSIX locks"):
        durable.Durable(tmp_path / "graph.db", n=4)
    with pytest.raises(ValueError, match="requires POSIX locks"):
        Service(tmp_path / "service.db", n=4)
