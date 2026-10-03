"""Exact bounded clock-cell undo across success, failure, and thread misuse."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.clocks import Clocks
from axiom.core import Matcher
from axiom.rebuild import Multilevel
from axiom.witness import Witness


def populated() -> Matcher:
    matcher = Matcher(32, mode="multilevel")
    matcher.level_phase_lengths[:] = [2, 4]
    matcher.level_phase_updates[:] = [0, 1]
    matcher.level_phase_indices[:] = [3, 5]
    return matcher


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_invalid_capacity_rejects_before_binding(capacity):
    matcher = populated()
    with pytest.raises(ValueError, match="capacity"):
        Clocks(matcher, capacity)
    assert matcher.clocks is None


def test_repeated_writes_retain_first_cell_value_and_restore_roots():
    matcher = populated()
    updates = matcher.level_phase_updates
    indices = matcher.level_phase_indices
    journal = Clocks(matcher, capacity=8)
    journal.write(updates, 0, 1)
    journal.write(updates, 0, 2)
    journal.write(indices, 1, 6)
    assert journal.cells == {(id(updates), 0): 0, (id(indices), 1): 5}
    journal.rollback()
    assert matcher.level_phase_updates is updates and updates == [0, 1]
    assert matcher.level_phase_indices is indices and indices == [3, 5]
    assert matcher.clocks is None


def test_cell_capacity_rejects_before_mutation_then_rollback_is_exact():
    matcher = populated()
    before = Witness().capture(matcher)
    journal = Clocks(matcher, capacity=1)
    journal.write(matcher.level_phase_updates, 0, 1)
    with pytest.raises(MemoryError, match="capacity"):
        journal.write(matcher.level_phase_indices, 0, 4)
    journal.rollback()
    assert Witness().capture(matcher) == before


def test_clock_schedule_failure_restores_advanced_cells_and_can_retry(monkeypatch):
    matcher = populated()
    before = Witness().capture(matcher)
    advance = Multilevel.advance_phase_clocks

    def fail(owner):
        advance(owner)
        raise RuntimeError("clock boundary failure")

    monkeypatch.setattr(Multilevel, "advance_phase_clocks", staticmethod(fail))
    with pytest.raises(RuntimeError, match="clock boundary"):
        matcher.insert(0, 1)
    assert Witness().capture(matcher) == before
    monkeypatch.setattr(Multilevel, "advance_phase_clocks", staticmethod(advance))
    matcher.insert(0, 1)
    assert matcher.maximal() and matcher.clocks is None


def test_clock_journal_rejects_foreign_thread_without_changing_cells():
    matcher = populated()
    journal = Clocks(matcher)
    before = list(matcher.level_phase_updates)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(journal.write, matcher.level_phase_updates, 0, 9)
        with pytest.raises(RuntimeError, match="another thread"):
            result.result()
    assert matcher.level_phase_updates == before
    journal.rollback()


def test_active_clock_handle_cannot_be_replaced_or_deleted():
    matcher = populated()
    journal = Clocks(matcher)
    with pytest.raises(RuntimeError, match="cannot be replaced"):
        matcher.clocks = None
    with pytest.raises(RuntimeError, match="cannot be deleted"):
        del matcher.clocks
    journal.rollback()
