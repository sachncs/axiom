"""Bounded paper update batches and exact rollback across both modes."""

import copy
import threading

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.storage import Packed
from axiom.witness import Witness


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_batch_commits_multiple_updates_once_and_keeps_maximality(mode, backend):
    matcher = Matcher(16, mode=mode, graph=backend(16))
    callbacks = []

    with matcher.batch(before_publish=lambda: callbacks.append("publish")) as batch:
        batch.insert(0, 1)
        batch.insert(2, 3)
        batch.delete(0, 1)
        batch.insert(0, 1)

    assert callbacks == ["publish"]
    assert matcher.graph.num_edges() == 2
    assert matcher.graph.has_edge(0, 1)
    assert matcher.graph.has_edge(2, 3)
    assert matcher.maximal()
    assert matcher.accountant.total_insertions == 3
    assert matcher.accountant.total_deletions == 1


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("failure_update", [2, 3])
def test_later_update_failure_restores_full_state_and_original_aliases(
    mode, failure_update, monkeypatch
):
    graph = Packed(16)
    for vertex in range(16):
        graph.add_edge(vertex, (vertex + 1) % 16)
    matcher = Matcher(16, mode=mode, graph=graph)
    matcher.phase_length = 1
    witness = Witness()
    before = witness.capture(matcher)
    aliases = (
        matcher.graph,
        matcher.matched_edges,
        matcher.matched_vertices,
        matcher.partner_map,
        matcher.seed_matching,
        matcher.matchings,
        matcher.system,
        matcher.multi,
    )
    original = Matcher._Matcher__advance_update_counter
    calls = 0

    def fail_on_update(owner):
        nonlocal calls
        calls += 1
        original(owner)
        if calls == failure_update:
            raise RuntimeError("injected later update failure")

    monkeypatch.setattr(Matcher, "_Matcher__advance_update_counter", fail_on_update)
    with (
        pytest.raises(RuntimeError, match="injected later update failure"),
        matcher.batch(max_operations=3),
    ):
        matcher.insert(0, 2)
        matcher.insert(4, 6)
        matcher.insert(8, 10)

    assert witness.capture(matcher) == before
    assert (
        matcher.graph,
        matcher.matched_edges,
        matcher.matched_vertices,
        matcher.partner_map,
        matcher.seed_matching,
        matcher.matchings,
        matcher.system,
        matcher.multi,
    ) == aliases
    assert graph.check()
    assert matcher.maximal()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_absent_delete_uses_outer_ledger_on_success_and_body_rollback(mode):
    matcher = Matcher(8, mode=mode, graph=Packed(8))
    witness = Witness()
    before = witness.capture(matcher)

    with pytest.raises(RuntimeError, match="abort batch body"), matcher.batch():
        matcher.delete(0, 1)
        matcher.insert(2, 3)
        raise RuntimeError("abort batch body")

    assert witness.capture(matcher) == before
    assert matcher.accountant.total_deletions == 0
    assert matcher.graph.num_edges() == 0

    with matcher.batch():
        matcher.delete(0, 1)
        matcher.insert(2, 3)
    assert matcher.accountant.total_deletions == 1
    assert matcher.graph.has_edge(2, 3)
    assert matcher.maximal()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_caught_validation_failure_aborts_and_rolls_back_the_batch(mode):
    matcher = Matcher(8, mode=mode, graph=Packed(8))
    witness = Witness()
    before = witness.capture(matcher)

    with pytest.raises(RuntimeError, match="batch was aborted"), matcher.batch():
        matcher.insert(0, 1)
        with pytest.raises(ValueError, match="vertex"):
            matcher.insert(8, 2)

    assert witness.capture(matcher) == before
    assert matcher.graph.num_edges() == 0


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_cross_thread_batch_mutation_is_rejected_without_poisoning_owner(mode):
    matcher = Matcher(8, mode=mode, graph=Packed(8))
    errors = []

    with matcher.batch():
        thread = threading.Thread(
            target=lambda: _capture_error(errors, lambda: matcher.insert(2, 3))
        )
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        matcher.insert(0, 1)

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "another thread" in str(errors[0])
    assert set(matcher.graph.edges()) == {(0, 1)}
    assert matcher.maximal()


def _capture_error(errors, operation):
    try:
        operation()
    except BaseException as error:
        errors.append(error)


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_batch_limit_is_hard_and_rolls_back_prior_updates(mode):
    matcher = Matcher(8, mode=mode, graph=Packed(8))
    witness = Witness()
    before = witness.capture(matcher)

    with (
        pytest.raises(MemoryError, match="operation limit"),
        matcher.batch(max_operations=1),
    ):
        matcher.insert(0, 1)
        matcher.insert(2, 3)

    assert witness.capture(matcher) == before


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_before_publish_failure_rolls_back_paper_state(mode):
    matcher = Matcher(8, mode=mode, graph=Packed(8))
    witness = Witness()
    before = witness.capture(matcher)

    def fail_persistence():
        raise OSError("injected persistence failure")

    with (
        pytest.raises(OSError, match="persistence failure"),
        matcher.batch(before_publish=fail_persistence),
    ):
        matcher.insert(0, 1)
        matcher.insert(2, 3)

    assert witness.capture(matcher) == before
    assert not matcher.failed
    assert matcher.maximal()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_cleanup_failure_after_persistence_callback_fail_stops_matcher(
    mode, monkeypatch
):
    matcher = Matcher(8, mode=mode, graph=Packed(8))
    callbacks = []

    def fail_cleanup(owner):
        raise RuntimeError("injected post-publication cleanup failure")

    monkeypatch.setattr("axiom.core.Views.commit", fail_cleanup)
    with (
        pytest.raises(RuntimeError, match="publication cleanup failed"),
        matcher.batch(before_publish=lambda: callbacks.append("committed")),
    ):
        matcher.insert(0, 1)
        matcher.insert(2, 3)

    assert callbacks == ["committed"]
    assert matcher.failed
    with pytest.raises(RuntimeError, match="has failed"):
        matcher.insert(4, 5)


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_batch_uses_sparse_undo_without_deepcopy(mode, backend, monkeypatch):
    matcher = Matcher(32, mode=mode, graph=backend(32))

    def reject_copy(value):
        raise AssertionError(f"deepcopy reached for {type(value).__name__}")

    monkeypatch.setattr(copy, "deepcopy", reject_copy)
    with matcher.batch():
        matcher.insert(0, 1)
        matcher.insert(2, 3)
        matcher.delete(0, 1)
        matcher.insert(4, 5)

    assert matcher.maximal()
    assert matcher.graph.num_edges() == 2


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("width", [1, 2, 4, 7])
def test_batch_boundaries_do_not_change_deterministic_paper_state(mode, width):
    operations = [
        ("insert", 0, 1),
        ("insert", 1, 2),
        ("insert", 2, 3),
        ("delete", 0, 1),
        ("insert", 3, 4),
        ("delete", 1, 2),
        ("insert", 0, 4),
    ]
    expected = Matcher(16, mode=mode)
    for operation, left, right in operations:
        getattr(expected, operation)(left, right)

    actual = Matcher(16, mode=mode)
    for offset in range(0, len(operations), width):
        with actual.batch(max_operations=width):
            for operation, left, right in operations[offset : offset + width]:
                getattr(actual, operation)(left, right)

    witness = Witness()
    assert witness.capture(actual) == witness.capture(expected)
