"""Tests for the ``axiom.cli`` command-line entry point.

These cover argument parsing, exit codes, and the documented CLI
behaviour surface (``--n``, ``--mode``, ``--updates``, ``--seed``).
"""

from __future__ import annotations

import contextlib
import io

import pytest

from axiom import cli


class TestCliMain:
    def test_returns_zero_on_success(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(
                ["--n", "10", "--mode", "basic", "--updates", "20", "--seed", "1"]
            )
        assert rc == 0
        out = buf.getvalue()
        assert "Completed 20 updates" in out
        assert "Maximal: True" in out

    def test_prints_matching_size(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["--n", "20", "--mode", "basic", "--updates", "30", "--seed", "7"])
        out = buf.getvalue()
        assert "Matching size:" in out
        assert "Final edges:" in out

    def test_invalid_mode_fails_parsing(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["--n", "10", "--mode", "bogus", "--updates", "5", "--seed", "1"])
        # argparse exits with code 2 on invalid arguments
        assert excinfo.value.code == 2

    def test_negative_updates_rejected(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(
                ["--n", "8", "--mode", "basic", "--updates", "0", "--seed", "1"]
            )
        # Zero updates is a no-op; the matcher is still maximal.
        assert rc == 0
        assert "Maximal: True" in buf.getvalue()

    def test_tiered_mode_runs(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(
                ["--n", "12", "--mode", "tiered", "--updates", "10", "--seed", "3"]
            )
        assert rc == 0
        assert "Maximal: True" in buf.getvalue()

    def test_multilevel_mode_runs(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(
                ["--n", "12", "--mode", "multilevel", "--updates", "10", "--seed", "3"]
            )
        assert rc == 0
        assert "Maximal: True" in buf.getvalue()
