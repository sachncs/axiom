"""Coupled old-publication partner reads, not private intermediate state."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.engine import Engine


@pytest.mark.parametrize("rollback", [False, True])
def test_first_write_view_survives_repeated_partner_changes_and_publication(rollback):
    engine = Engine(16)
    engine.ring()
    before = [engine.committed_partner(u) for u in range(16)]
    token = engine.begin()
    for _ in range(10):
        engine.delete(0, 1)
        engine.insert(0, 4)
        engine.delete(0, 4)
        engine.insert(0, 1)
        with ThreadPoolExecutor(max_workers=1) as worker:
            observed = worker.submit(
                lambda: [engine.committed_partner(u) for u in range(16)]
            ).result(timeout=5)
        assert observed == before
        with pytest.raises(RuntimeError, match="unpublished"):
            engine.partner(0)
    if rollback:
        engine.rollback(token)
        assert [engine.committed_partner(u) for u in range(16)] == before
    else:
        engine.commit(token)
        assert all(
            engine.committed_partner(u) == (engine.version, engine.partner(u))
            for u in range(16)
        )
    assert engine.check()
    restored = Engine.restore(engine.snapshot())
    assert [restored.committed_partner(u) for u in range(16)] == [
        engine.committed_partner(u) for u in range(16)
    ]


def test_failed_edit_discards_old_view_indexes_and_preserves_exact_published_state():
    engine = Engine(16)
    engine.ring()
    before = [engine.committed_partner(u) for u in range(16)]
    engine.begin()
    engine.delete(0, 1)
    with pytest.raises(ValueError):
        engine.insert(16, 0)
    assert not engine.active and engine.check()
    assert [engine.committed_partner(u) for u in range(16)] == before
    engine.delete(0, 1)
    assert engine.committed_partner(0) == (engine.version, engine.partner(0))


@pytest.mark.parametrize("vertex", [-1, 16, True, 1.5, "1"])
def test_bad_committed_query_does_not_abort_owner_transaction(vertex):
    engine = Engine(16)
    token = engine.begin()
    engine.insert(0, 1)
    with pytest.raises(ValueError):
        engine.committed_partner(vertex)
    assert engine.active and engine.committed_partner(0) == (0, None)
    engine.commit(token)
    assert engine.committed_partner(0) == (1, 1)


def test_new_metadata_is_counted_before_allocation_and_undo_rejection_is_reusable():
    metadata = Engine(16).memory()["allocated"]
    with pytest.raises(MemoryError):
        Engine(16, budget=metadata - 1)
    engine = Engine(16, budget=metadata)
    with pytest.raises(MemoryError):
        engine.insert(0, 1)
    assert engine.committed_partner(0) == (0, None)
    assert not engine.active and engine.check()
