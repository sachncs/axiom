"""Fail-closed schema and evidence tests for release qualification."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_qualification.py"
MODES = ("basic", "multilevel")
GATES = ("research", "durability", "performance", "deployment")


def manifest(status: str = "open", evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "modes": {
            mode: {
                gate: {"status": status, "evidence": list(evidence or [])}
                for gate in GATES
            }
            for mode in MODES
        },
    }


def run_verifier(
    tmp_path: Path, data: Any, *, release: bool = False
) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    manifest_path = tmp_path / "qualification.json"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    command = [
        sys.executable,
        str(VERIFIER),
        "--manifest",
        str(manifest_path),
        "--repo-root",
        str(repo),
    ]
    if release:
        command.append("--release")
    return subprocess.run(command, text=True, capture_output=True, check=False)


def test_valid_open_manifest_passes_normal_validation_but_not_release(
    tmp_path: Path,
) -> None:
    result = run_verifier(tmp_path, manifest())
    assert result.returncode == 0, result.stderr
    assert "gates may remain open" in result.stdout

    release = run_verifier(tmp_path, manifest(), release=True)
    assert release.returncode != 0
    assert "release qualification is open" in release.stderr


def test_incomplete_manifest_fails_for_missing_gate(tmp_path: Path) -> None:
    data = manifest()
    del data["modes"]["basic"]["performance"]
    result = run_verifier(tmp_path, data)
    assert result.returncode != 0
    assert "missing performance" in result.stderr


def test_pass_without_evidence_fails(tmp_path: Path) -> None:
    data = manifest()
    data["modes"]["basic"]["research"] = {"status": "pass", "evidence": []}
    result = run_verifier(tmp_path, data)
    assert result.returncode != 0
    assert "has no evidence" in result.stderr


def test_malformed_evidence_fails_even_for_an_open_gate(tmp_path: Path) -> None:
    data = manifest()
    data["modes"]["basic"]["research"]["evidence"] = [""]
    result = run_verifier(tmp_path, data)
    assert result.returncode != 0
    assert "nonempty strings" in result.stderr


@pytest.mark.parametrize(
    "evidence", ["missing.json", "../outside.json", "/tmp/outside.json"]
)
def test_pass_with_missing_or_outside_evidence_fails(
    tmp_path: Path, evidence: str
) -> None:
    data = manifest()
    data["modes"]["basic"]["research"] = {"status": "pass", "evidence": [evidence]}
    result = run_verifier(tmp_path, data)
    assert result.returncode != 0
    assert "evidence" in result.stderr


def test_evidence_symlink_cannot_escape_repository(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "escape.json").symlink_to(outside)
    data = manifest()
    data["modes"]["basic"]["research"] = {"status": "pass", "evidence": ["escape.json"]}
    manifest_path = tmp_path / "qualification.json"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(repo),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "inside the repository" in result.stderr


def test_all_pass_manifest_with_existing_evidence_is_release_qualified(
    tmp_path: Path,
) -> None:
    data = manifest(status="pass", evidence=["evidence/report.json"])
    repo = tmp_path / "repo"
    (repo / "evidence").mkdir(parents=True)
    (repo / "evidence" / "report.json").write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "qualification.json"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(repo),
            "--release",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "release-qualified" in result.stdout
