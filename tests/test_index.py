"""Fixed index profiles reject unsafe workloads and independently verify state."""

import hashlib

import pytest

from benchmarks.index import Trial


@pytest.mark.parametrize(
    "options",
    [
        {"vertices": True},
        {"vertices": 9},
        {"width": 32, "vertices": 32},
        {"updates": 3},
        {"updates": 200002},
        {"budget": 0},
    ],
)
def test_invalid_fixed_trace_rejects_before_running(options):
    with pytest.raises(ValueError):
        Trial(**options)


def test_fixed_trace_exact_reference_and_checkpoint_repeatability():
    trial = Trial(128, 32, 300, 1 << 20)
    first, second = trial.run(), trial.run()
    expected = hashlib.sha256(
        b"".join((vertex ^ 1).to_bytes(4, "little") for vertex in range(128))
    ).hexdigest()
    assert first["verified"] and second["verified"]
    assert first["matching"] == second["matching"] == expected
    assert first["checkpoint"] == second["checkpoint"]
    assert first["memory"]["allocated"] <= first["budget"] == 1 << 20
    assert first["updates"] == 300 and first["rate"] > 0
