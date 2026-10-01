"""Checkpoint measurements must independently verify exact restoration."""

import pytest

from benchmarks.checkpoint import measure


def test_checkpoint_measurement_keeps_exact_state_and_declares_nondurable_scope() -> (
    None
):
    result = measure(64, 40)
    assert result["edges"] == 128 and result["version"] == 81
    assert result["image_bytes"] == 40 + 8 * 64 + 8 * 128
    assert result["exact_restoration_passed"]
    assert "NO durable checkpoint" in result["scope"]


@pytest.mark.parametrize("n,pairs", [(7, 4), (64, 0), (64, 65)])
def test_measurement_rejects_invalid_envelope(n: int, pairs: int) -> None:
    with pytest.raises(ValueError):
        measure(n, pairs)
