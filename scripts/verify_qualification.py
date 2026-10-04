#!/usr/bin/env python3
"""Validate Axiom's per-mode qualification manifest.

The manifest is deliberately fail-closed: its shape is exact, each matching
mode must declare all four independent gates, and every claimed pass must cite
one or more existing files inside the repository. ``--release`` additionally
requires every gate to pass. The standard library is sufficient so the check
can run in a clean source checkout and in release environments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MODES = ("basic", "multilevel")
GATES = ("research", "durability", "performance", "deployment")


class QualificationError(ValueError):
    """Raised when qualification data is malformed or cannot be verified."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON objects instead of silently taking the last key."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def require_object(value: Any, expected: set[str], location: str) -> dict[str, Any]:
    """Require an object with exactly the specified keys."""
    if not isinstance(value, dict):
        raise QualificationError(f"{location} must be an object")
    actual = set(value)
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unexpected " + ", ".join(sorted(extra)))
        raise QualificationError(f"{location}: " + "; ".join(details))
    return value


def validate_evidence(items: Any, root: Path, location: str, *, required: bool) -> None:
    """Require each evidence path to resolve to a file within the repository."""
    if not isinstance(items, list):
        raise QualificationError(f"{location}.evidence must be an array")
    if required and not items:
        raise QualificationError(f"{location} is pass but has no evidence")
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise QualificationError(
                f"{location}.evidence paths must be nonempty strings"
            )
        relative = Path(item)
        if relative.is_absolute():
            raise QualificationError(
                f"{location} evidence must be repo-relative: {item}"
            )
        try:
            resolved = (root / relative).resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            raise QualificationError(
                f"{location} evidence must exist inside the repository: {item}"
            ) from None
        if not resolved.is_file():
            raise QualificationError(f"{location} evidence is not a file: {item}")


def validate_manifest(data: Any, root: Path, release: bool = False) -> None:
    """Validate exact manifest shape and optional release readiness."""
    document = require_object(data, {"schema_version", "modes"}, "manifest")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise QualificationError("manifest.schema_version must be integer 1")
    modes = require_object(document["modes"], set(MODES), "manifest.modes")
    for mode in MODES:
        gates = require_object(modes[mode], set(GATES), f"modes.{mode}")
        for gate in GATES:
            location = f"modes.{mode}.{gate}"
            entry = require_object(gates[gate], {"status", "evidence"}, location)
            status = entry["status"]
            if status not in ("open", "pass"):
                raise QualificationError(f"{location}.status must be 'open' or 'pass'")
            evidence = entry["evidence"]
            validate_evidence(evidence, root, location, required=(status == "pass"))
            if release and status != "pass":
                raise QualificationError(f"release qualification is open: {location}")


def main(arguments: list[str] | None = None) -> int:
    """Run the command-line verifier and return its process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "qualification.json",
        help="manifest path (default: repository qualification.json)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root against which evidence paths are resolved",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="fail unless every gate for both modes has passed",
    )
    options = parser.parse_args(arguments)
    root = options.repo_root.resolve()
    try:
        with options.manifest.open(encoding="utf-8") as manifest_file:
            data = json.load(manifest_file, object_pairs_hook=reject_duplicate_keys)
        validate_manifest(data, root, options.release)
    except (OSError, json.JSONDecodeError, QualificationError) as error:
        print(f"qualification: FAIL: {error}", file=sys.stderr)
        return 1
    outcome = (
        "release-qualified" if options.release else "valid (gates may remain open)"
    )
    print(f"qualification: PASS: {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
