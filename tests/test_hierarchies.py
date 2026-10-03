"""Identity-preserving transaction tests for recursive hierarchy roots."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.hierarchies import Hierarchies
from axiom.storage import Packed
from axiom.witness import Witness


def populated():
    graph = Packed(16)
    for vertex in range(16):
        graph.add_edge(vertex, (vertex + 1) % 16)
    return Matcher(16, graph=graph, mode="multilevel")


def test_hierarchy_transactions_run_without_recursive_deepcopy(monkeypatch):
    matcher = populated()
    root = matcher.multi
    assert root is not None
    before = Witness().capture(matcher)
    import copy

    def reject(*args, **kwargs):
        raise AssertionError("Matcher update invoked deepcopy")

    monkeypatch.setattr(copy, "deepcopy", reject)
    matcher.insert(0, 4)

    assert matcher.multi is root
    assert matcher.hierarchies is None and root.journal is None
    assert Witness().capture(matcher) != before


def test_failed_deletion_restores_hierarchy_and_partition_identities(monkeypatch):
    matcher = populated()
    root = matcher.multi
    assert root is not None
    roots = (
        root.levels,
        root.A1,
        root.A2,
        root.N1,
        root.R1,
        root.A_levels,
        root.N_levels,
        root.R_levels,
        root.L_levels,
        root.deferred_deletions,
    )
    before = Witness().capture(matcher)

    def fail(self):
        raise RuntimeError("injected post-repair failure")

    monkeypatch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
    with pytest.raises(RuntimeError, match="injected post-repair failure"):
        matcher.delete(0, 1)

    assert matcher.multi is root
    restored = (
        root.levels,
        root.A1,
        root.A2,
        root.N1,
        root.R1,
        root.A_levels,
        root.N_levels,
        root.R_levels,
        root.L_levels,
        root.deferred_deletions,
    )
    assert all(before is after for before, after in zip(roots, restored, strict=True))
    assert matcher.hierarchies is None and root.journal is None
    assert Witness().capture(matcher) == before
    assert matcher.graph.check() and matcher.multi.check()


@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_failed_phase_rebuild_restores_original_hierarchy_and_retries(
    backend, monkeypatch
):
    graph = backend(16)
    for vertex in range(16):
        graph.add_edge(vertex, (vertex + 1) % 16)
    matcher = Matcher(16, graph=graph, mode="multilevel")
    matcher.phase_length = 1
    root = matcher.multi
    assert root is not None
    state = dict(vars(root))
    before = Witness().capture(matcher)
    advance = Matcher._Matcher__advance_update_counter

    def fail(owner):
        advance(owner)
        raise RuntimeError("injected after hierarchy rebuild")

    with monkeypatch.context() as patch:
        patch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
        with pytest.raises(RuntimeError, match="after hierarchy rebuild"):
            matcher.delete(0, 1)

    assert matcher.multi is root
    assert all(vars(root)[name] is value for name, value in state.items())
    assert matcher.hierarchies is None and root.journal is None
    assert Witness().capture(matcher) == before
    assert matcher.maximal() and root.check()
    matcher.delete(0, 1)
    assert matcher.maximal() and matcher.multi is not root


def test_deferred_edges_restore_exactly_after_candidate_failure(monkeypatch):
    matcher = populated()
    root = matcher.multi
    assert root is not None
    original = root.deferred_deletions
    before = Witness().capture(matcher)

    def fail(self):
        raise RuntimeError("injected post-repair failure")

    monkeypatch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
    with pytest.raises(RuntimeError, match="injected post-repair failure"):
        matcher.delete(0, 1)

    assert matcher.multi is root and root.deferred_deletions is original
    assert not original
    assert Witness().capture(matcher) == before


def test_capacity_failure_during_clear_leaves_deferred_edges_unchanged():
    matcher = populated()
    root = matcher.multi
    assert root is not None
    root.deferred_deletions.update({(0, 1), (1, 2)})
    before = Witness().capture(matcher)
    journal = Hierarchies(matcher, capacity=1)

    with pytest.raises(MemoryError, match="capacity exceeded"):
        journal.clear()

    assert root.deferred_deletions == {(0, 1), (1, 2)}
    journal.rollback()
    assert matcher.multi is root and root.journal is None
    assert Witness().capture(matcher) == before


def test_repeated_defer_undefer_and_clear_restore_first_membership():
    matcher = populated()
    root = matcher.multi
    assert root is not None
    edge = (0, 1)
    before = Witness().capture(matcher)
    journal = Hierarchies(matcher)
    root.defer(edge)
    root.undefer(edge)
    root.defer(edge)
    assert root.deferred_deletions == {edge}
    journal.rollback()
    assert Witness().capture(matcher) == before


def test_hierarchy_journal_rejects_cross_thread_use_and_detachment():
    matcher = populated()
    root = matcher.multi
    assert root is not None
    journal = Hierarchies(matcher)
    with ThreadPoolExecutor(max_workers=1) as executor:
        outcome = executor.submit(root.defer, (0, 1))
        with pytest.raises(RuntimeError, match="another thread"):
            outcome.result()
    with pytest.raises(RuntimeError, match="cannot be replaced"):
        root.journal = None
    with pytest.raises(RuntimeError, match="cannot be deleted"):
        del root.journal
    journal.rollback()
    assert matcher.hierarchies is None and root.journal is None
