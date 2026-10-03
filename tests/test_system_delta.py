"""Shared endpoint-cache deltas, union-free membership and rollback data flow."""

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.hierarchy import build_hierarchy as hierarchy
from axiom.hierarchy import update
from axiom.storage import Packed
from axiom.system import System
from axiom.systems import Systems
from axiom.witness import Witness


class Union(set):
    """Fail if a point-membership operation materializes a partition union."""

    def __or__(self, other):
        raise AssertionError("partition union allocated")


def indexed(backend=Packed):
    graph = backend(6)
    for edge in ((0, 1), (0, 2), (2, 3), (1, 4)):
        graph.add_edge(*edge)
    system = System(graph, 1, A={0}, B={1}, U={2, 3, 4, 5}, M={(0, 1)})
    system.index()
    return system


@pytest.mark.parametrize("backend", [Adjacency, Packed])
@pytest.mark.parametrize("edge", [(0, 3), (1, 2), (3, 4), (0, 1), (0, 2)])
def test_delta_matches_full_index_and_retains_unaffected_rows(backend, edge):
    system = indexed(backend)
    rows = {
        (name, vertex): (values, list(values))
        for name in ("lambda_lists", "L_lists")
        for vertex, values in getattr(system, name).items()
    }
    existed = system.graph.has_edge(*edge)
    mutate = system.graph.remove_edge if existed else system.graph.add_edge
    mutate(*edge)
    system.update(*edge, not existed)
    assert system.check_lambda() and system.check_L()
    for (name, vertex), (values, original) in rows.items():
        current = getattr(system, name).get(vertex)
        if vertex in edge and current is None:
            assert original and values == []
        else:
            assert current is values
    previous = Witness().capture(system)
    system.update(*edge, not existed)
    assert Witness().capture(system) == previous
    reverse = system.graph.add_edge if existed else system.graph.remove_edge
    reverse(*edge)
    system.update(*edge, existed)
    assert system.check_lambda() and system.check_L()


def test_deleting_last_cached_neighbor_prunes_row_and_rollback_restores_alias():
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    owner = Matcher(4, graph=graph)
    system = System(graph, 1, A={0}, B=set(), U={1, 2, 3})
    system.index()
    owner.system = system
    row = system.L_lists[0]
    journal = Systems(owner)

    graph.remove_edge(0, 1)
    system.update(0, 1, False)
    assert 0 not in system.L_lists
    assert row == []

    journal.rollback()
    graph.add_edge(0, 1)
    assert system.L_lists[0] is row
    assert row == [1]
    assert system.check_L()


@pytest.mark.parametrize(
    "values,value,added,expected",
    [
        ([], 2, True, [2]),
        ([2, 4], 1, True, [1, 2, 4]),
        ([2, 4], 3, True, [2, 3, 4]),
        ([2, 4], 5, True, [2, 4, 5]),
        ([2, 4], 2, True, [2, 4]),
        ([2, 4], 3, False, [2, 4]),
        ([2, 4], 2, False, [4]),
        ([2, 4], 4, False, [2]),
        ([], 2, False, []),
    ],
)
def test_sorted_delta_and_legacy_alias(values, value, added, expected):
    assert update is System.change
    identity = id(values)
    System.change(values, value, added)
    assert values == expected and id(values) == identity


@pytest.mark.parametrize(
    "left,right,added",
    [
        (-1, 2, True),
        (0, 6, True),
        (True, 2, True),
        (0, 2.0, True),
        (2, 2, True),
        (0, 3, 1),
        (0, 3, False),
        (0, 2, True),
    ],
)
def test_invalid_or_unapplied_delta_rejects_before_any_cache_mutation(
    left, right, added
):
    system = indexed()
    # Last two cases deliberately request the opposite of current graph state.
    if (left, right, added) == (0, 3, False):
        system.graph.add_edge(0, 3)
    elif (left, right, added) == (0, 2, True):
        system.graph.remove_edge(0, 2)
    before = Witness().capture(system)
    with pytest.raises(ValueError, match="delta"):
        system.update(left, right, added)
    assert Witness().capture(system) == before


def test_endpoint_membership_uses_original_partitions_without_union():
    system = indexed()
    system.A = Union(system.A)
    system.B = Union(system.B)
    system.U = Union(system.U)
    system.graph.add_edge(1, 2)
    system.update(1, 2, True)
    assert system.lambda_lists[2] == [1, 3]
    assert system.check_p2()
    system.M.add((0, 2))
    assert not system.check_p2()


def test_incremental_hierarchy_routes_each_level_through_shared_system_delta(
    monkeypatch,
):
    graph = Packed(8)
    graph.ring(1)
    owner = hierarchy(graph, [2])
    live = graph.copy()
    calls = []
    original = System.update

    def audited(system, left, right, added):
        calls.append((system, left, right, added))
        return original(system, left, right, added)

    monkeypatch.setattr(System, "update", audited)
    live.add_edge(0, 4)
    owner.sync_graph(live, changed_edge=(0, 4))
    assert len(calls) == len(owner.levels)
    assert all(
        call[0] is level for call, level in zip(calls, owner.levels, strict=True)
    )
    assert all(call[1:] == (0, 4, True) for call in calls)
    assert all(level.check_lambda() and level.check_L() for level in owner.levels)
    assert owner.check()
    live.remove_edge(0, 4)
    owner.sync_graph(live, changed_edge=(0, 4))
    assert all(level.check_lambda() and level.check_L() for level in owner.levels)
    assert owner.check()


def test_hierarchy_certificate_checks_edges_without_materializing_saturated_sets(
    monkeypatch,
):
    graph = Packed(8)
    for left in range(8):
        for right in range(left + 1, 8):
            graph.add_edge(left, right)
    owner = hierarchy(graph, [8, 4, 2])
    assert owner.check() and any(level.A and level.M for level in owner.levels)

    def reject(system):
        raise AssertionError("saturated partition materialized for edge lookup")

    monkeypatch.setattr(System, "S", property(reject))
    assert owner.check()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_endpoint_cache_failure_restores_full_state_before_retry(
    mode, backend, monkeypatch
):
    graph = backend(16)
    graph.add_edge(0, 1)
    matcher = Matcher(16, mode=mode, graph=graph)
    before = Witness().capture(matcher)
    method = System.update

    def reject(system, left, right, added):
        method(system, left, right, added)
        raise RuntimeError("after cache delta")

    with monkeypatch.context() as patch:
        patch.setattr(System, "update", reject)
        # Basic edits its live caches. The multilevel case is deliberately a
        # malformed tombstone pointing at a non-phase edge, forcing the phase
        # visibility/cache path; it is fault recovery, not valid-workload evidence.
        if mode == "basic":
            with pytest.raises(RuntimeError, match="cache delta"):
                matcher.insert(0, 2)
        else:
            matcher.deleted_edges.add((0, 2))
            before = Witness().capture(matcher)
            with pytest.raises(RuntimeError, match="cache delta"):
                matcher.insert(0, 2)
    assert Witness().capture(matcher) == before
    matcher.insert(0, 2)
    assert matcher.maximal()
