"""Native checkpoint bounds, exact restoration and independent certificates."""

import random
import struct

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_engine import Reference, certify, snapshot

from axiom.engine import Engine


def image(n: int, rows: list[list[int]], partners: list[int], matched: int) -> bytes:
    entries = sum(map(len, rows))
    return struct.pack(
        "<8sIIQQQ", b"AXENG001", n, 0, entries // 2, 9, matched
    ) + b"".join(
        struct.pack("<II", len(row), partner)
        + b"".join(struct.pack("<I", v) for v in row)
        for row, partner in zip(rows, partners, strict=True)
    )


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.tuples(st.booleans(), st.integers(0, 32), st.integers(0, 32)), max_size=150
    )
)
def test_checkpoint_preserves_exact_state_and_future_deterministic_repairs(
    updates: list,
) -> None:
    engine, reference = Engine(33), Reference(33)
    for adding, u, v in updates:
        assert (
            engine.insert(u, v) if adding else engine.delete(u, v)
        ) == reference.edit(u, v, adding)
    saved = snapshot(engine)
    encoded = engine.snapshot()
    assert len(encoded) == 40 + 8 * engine.n + 8 * engine.num_edges()
    assert encoded[:8] == b"AXENG001"
    restored = Engine.restore(encoded)
    assert snapshot(engine) == snapshot(restored) == saved
    assert restored.active is False and restored.poisoned is False
    certify(restored, reference)
    for adding, u, v in reversed(updates):
        expected = reference.edit(u, v, adding)
        assert (restored.insert(u, v) if adding else restored.delete(u, v)) == expected
        assert (engine.insert(u, v) if adding else engine.delete(u, v)) == expected
    certify(restored, reference)
    assert snapshot(engine) == snapshot(restored)


@pytest.mark.parametrize("n", [0, 1, 2, 129])
def test_empty_checkpoint_and_high_degree_ring(n: int) -> None:
    engine = Engine(n)
    if n == 129:
        engine.ring(16)
        engine.delete(0, 1)
    encoded = engine.snapshot()
    restored = Engine.restore(encoded)
    assert restored.check() and snapshot(engine) == snapshot(restored)
    assert restored.snapshot() == encoded


def test_restore_keeps_partners_instead_of_recomputing_another_matching() -> None:
    # Proper maximal matching {1--2}, not the matching {0--1, 2--3} that a
    # fresh canonical insertion pass would choose. Restore must retain the image.
    encoded = image(4, [[1], [0, 2], [1, 3], [2]], [0xFFFFFFFF, 2, 1, 0xFFFFFFFF], 1)
    restored = Engine.restore(encoded)
    assert restored.check() and restored.version == 9 and restored.size() == 1
    assert [restored.partner(u) for u in range(4)] == [None, 2, 1, None]
    assert restored.snapshot() == encoded


def test_unpublished_checkpoint_rejects_without_closing_or_changing_batch() -> None:
    engine = Engine(16)
    engine.ring()
    before = snapshot(engine)
    token = engine.begin()
    engine.delete(0, 1)
    with pytest.raises(RuntimeError, match="unpublished"):
        engine.snapshot()
    assert engine.active and engine.check()
    engine.rollback(token)
    assert snapshot(engine) == before


def test_checkpoint_byte_and_native_budgets_reject_without_changing_source() -> None:
    engine = Engine(33)
    engine.ring()
    before = snapshot(engine)
    encoded = engine.snapshot()
    with pytest.raises(MemoryError, match="output byte"):
        engine.snapshot(max_bytes=len(encoded) - 1)
    with pytest.raises(MemoryError, match="input byte"):
        Engine.restore(encoded, max_bytes=len(encoded) - 1)
    with pytest.raises(MemoryError):
        Engine.restore(encoded, budget=Engine(33).memory()["allocated"])
    with pytest.raises(ValueError):
        Engine.restore(bytearray(encoded))
    assert snapshot(engine) == before and engine.check()
    assert Engine.restore(encoded).check()


@pytest.mark.parametrize(
    "part",
    [
        "magic",
        "reserved",
        "edges",
        "matching",
        "degree",
        "partner",
        "neighbor",
        "truncated",
        "trailing",
    ],
)
def test_invalid_checkpoint_headers_offsets_and_values_reject(part: str) -> None:
    encoded = bytearray(image(4, [[1], [0], [], []], [1, 0, 0xFFFFFFFF, 0xFFFFFFFF], 1))
    if part == "magic":
        encoded[0] = 0
    elif part == "reserved":
        struct.pack_into("<I", encoded, 12, 1)
    elif part == "edges":
        struct.pack_into("<Q", encoded, 16, 0xFFFFFFFFFFFFFFFF)
    elif part == "matching":
        struct.pack_into("<Q", encoded, 32, 99)
    elif part == "degree":
        struct.pack_into("<I", encoded, 40, 0xFFFFFFFF)
    elif part == "partner":
        struct.pack_into("<I", encoded, 44, 4)
    elif part == "neighbor":
        struct.pack_into("<I", encoded, 48, 4)
    elif part == "truncated":
        encoded = encoded[:-1]
    else:
        encoded.extend(b"extra")
    with pytest.raises(ValueError):
        Engine.restore(bytes(encoded))


@pytest.mark.parametrize(
    "rows,partners,matched",
    [
        ([[1], [2], [], []], [1, 0, 0xFFFFFFFF, 0xFFFFFFFF], 1),  # asymmetry
        ([[1, 1], [0, 0], [], []], [1, 0, 0xFFFFFFFF, 0xFFFFFFFF], 1),  # duplicates
        (
            [[1], [0], [], []],
            [1, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF],
            1,
        ),  # partner symmetry
        ([[1], [0], [], []], [2, 0xFFFFFFFF, 0, 0xFFFFFFFF], 1),  # non-live partner
        ([[1], [0], [], []], [0xFFFFFFFF] * 4, 0),  # uncovered edge
        ([[1], [0], [], []], [1, 0, 0xFFFFFFFF, 0xFFFFFFFF], 0),  # matching count
    ],
)
def test_full_candidate_audit_rejects_invalid_graph_or_matching(
    rows: list, partners: list, matched: int
) -> None:
    with pytest.raises(ValueError, match="audit"):
        Engine.restore(image(4, rows, partners, matched))


def test_random_corrupt_inputs_either_reject_or_return_a_fully_audited_candidate() -> (
    None
):
    engine = Engine(65)
    engine.ring(16)
    encoded = engine.snapshot()
    rng = random.Random(644)
    for _ in range(500):
        altered = bytearray(encoded)
        for _ in range(rng.randrange(1, 5)):
            position = rng.randrange(len(altered))
            altered[position] ^= 1 << rng.randrange(8)
        try:
            restored = Engine.restore(bytes(altered), budget=1 << 20)
        except (ValueError, MemoryError):
            continue
        # Some changed versions/neighbor orders remain structurally valid; the
        # durable layer must additionally verify its cryptographic image checksum.
        assert restored.check()
    assert engine.check()
