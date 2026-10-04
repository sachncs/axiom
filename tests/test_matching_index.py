from __future__ import annotations

from typing import Any

import pytest

from axiom.matching_index import MatchingIndex


def test_empty_and_zero_vertex_index() -> None:
    index = MatchingIndex(0)
    assert len(index) == 0
    assert not index
    assert list(index) == []
    assert set(index) == set()


def test_add_membership_canonical_iteration_and_duplicate_semantics() -> None:
    index = MatchingIndex(8)
    index.add((5, 1))
    index.add((1, 5))
    index.add((0, 7))
    index.add((2, 3))

    assert len(index) == 3
    assert index
    assert (1, 5) in index and (5, 1) in index
    assert set(index) == {(0, 7), (1, 5), (2, 3)}
    assert list(index) == [(0, 7), (1, 5), (2, 3)]


def test_overlapping_edges_are_stored_without_matching_constraints() -> None:
    index = MatchingIndex(5)
    index.add((0, 1))
    index.add((0, 2))
    index.add((0, 3))

    assert len(index) == 3
    assert set(index) == {(0, 1), (0, 2), (0, 3)}


def test_full_small_universe_contains_every_simple_edge() -> None:
    index = MatchingIndex(7)
    expected = {(left, right) for left in range(7) for right in range(left + 1, 7)}
    for edge in expected:
        index.add(edge)

    assert len(index) == 21
    assert set(index) == expected
    assert all(edge in index for edge in expected)


def test_disconnected_edges_mutate_and_clear() -> None:
    index = MatchingIndex(10)
    for edge in [(0, 1), (4, 7), (8, 9)]:
        index.add(edge)
    index.discard((7, 4))
    index.discard((2, 6))
    assert set(index) == {(0, 1), (8, 9)}

    index.clear()
    assert len(index) == 0
    assert not index
    assert set(index) == set()


def test_equality_and_subset_superset_are_orientation_independent() -> None:
    index = MatchingIndex(8)
    index.add((0, 4))
    index.add((2, 7))
    same = {(4, 0), (7, 2)}
    subset = {(4, 0)}

    assert index == same
    assert index <= same
    assert index >= subset
    assert not (index <= subset)
    assert not (index >= {(1, 3)})


@pytest.mark.parametrize("edge", [(), (0,), (0, 1, 2), "01", None])
def test_rejects_malformed_edges(edge: Any) -> None:
    index = MatchingIndex(4)
    with pytest.raises(TypeError):
        index.add(edge)


@pytest.mark.parametrize("edge", [(True, 2), (1.0, 2), ("1", 2), (None, 2)])
def test_rejects_non_integer_edge_labels(edge: tuple[Any, Any]) -> None:
    index = MatchingIndex(4)
    with pytest.raises(TypeError):
        index.add(edge)


@pytest.mark.parametrize("edge", [(-1, 2), (0, 4)])
def test_rejects_out_of_bounds_edge_labels(edge: tuple[int, int]) -> None:
    index = MatchingIndex(4)
    with pytest.raises(ValueError):
        index.add(edge)


def test_rejects_self_loops_for_mutation_and_membership() -> None:
    index = MatchingIndex(4)
    with pytest.raises(ValueError, match="self-loops"):
        index.add((2, 2))
    with pytest.raises(ValueError, match="self-loops"):
        _ = (2, 2) in index


def test_native_storage_obeys_optional_budget() -> None:
    index = MatchingIndex(12, budget=2_000_000)
    assert index.graph.memory()["budget"] == 2_000_000


def test_clear_does_not_replace_graph_during_native_transaction() -> None:
    index = MatchingIndex(8)
    index.add((0, 1))
    graph = index.graph
    token = graph.begin()
    with pytest.raises(RuntimeError, match="during a native journal"):
        index.clear()
    assert index.graph is graph and (0, 1) in index
    graph.rollback(token)


@pytest.mark.parametrize(
    "n,budget,error",
    [
        (True, 1, TypeError),
        (4, True, TypeError),
        (-1, 1, ValueError),
        (4, -1, ValueError),
    ],
)
def test_rejects_invalid_universe_or_budget(
    n: int, budget: int, error: type[Exception]
) -> None:
    with pytest.raises(error):
        MatchingIndex(n, budget=budget)
