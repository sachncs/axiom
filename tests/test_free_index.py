"""Sparse global-free search retains exact deterministic matching and rollback."""

import pytest
from test_engine import snapshot

from axiom.engine import Engine


@pytest.mark.parametrize("n", [0, 1, 63, 64, 65, 4095, 4096, 4097])
def test_bitmap_boundaries_survive_ring_restore_and_budget_admission(n):
    engine = Engine(n)
    metadata = engine.memory()["allocated"]
    with pytest.raises(MemoryError):
        Engine(n, budget=metadata - 1)
    assert Engine(n, budget=metadata).check()
    engine.ring(2 if n >= 5 else 0)
    restored = Engine.restore(engine.snapshot())
    assert restored.check() and restored.snapshot() == engine.snapshot()


@pytest.mark.parametrize("commit", [False, True])
def test_repeated_hub_repairs_preserve_first_publication_and_exact_undo(commit):
    engine = Engine(512)
    engine.ring()
    for v in range(3, 120):
        engine.insert(0, v)
    engine.delete(128, 129)
    before = snapshot(engine)
    old = [engine.committed_partner(u) for u in range(512)]
    token = engine.begin()
    for _ in range(50):
        engine.delete(0, 1)
        assert engine.committed_partner(0) == old[0]
        engine.insert(0, 128)
        engine.delete(0, 128)
        engine.insert(0, 1)
        assert engine.check()
    if commit:
        engine.commit(token)
        assert engine.partner(0) == 1 and engine.partner(128) is None
        assert Engine.restore(engine.snapshot()).snapshot() == engine.snapshot()
    else:
        engine.rollback(token)
        assert snapshot(engine) == before
        assert [engine.committed_partner(u) for u in range(512)] == old
    assert engine.check()


def test_bad_edit_after_hub_repair_restores_derived_index_and_exact_snapshot():
    engine = Engine(512)
    engine.ring()
    for v in range(3, 120):
        engine.insert(0, v)
    before = snapshot(engine)
    engine.begin()
    engine.delete(0, 1)
    with pytest.raises(ValueError):
        engine.insert(512, 0)
    assert not engine.active and engine.check() and snapshot(engine) == before


def test_sparse_free_search_selects_minimum_neighbor_not_insertion_order():
    engine = Engine(512)
    engine.ring()
    for v in range(3, 120):
        engine.insert(0, v)
    engine.delete(128, 129)
    engine.insert(0, 129)
    engine.insert(0, 128)
    engine.delete(0, 1)
    assert engine.partner(0) == 128 and engine.partner(128) == 0
    assert engine.partner(1) is None and engine.partner(129) is None
    assert engine.check()
    restored = Engine.restore(engine.snapshot())
    assert snapshot(restored) == snapshot(engine) and restored.check()
