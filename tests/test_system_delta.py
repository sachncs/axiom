"""Shared endpoint-cache deltas, union-free membership and rollback data flow."""

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.hierarchy import build_hierarchy as hierarchy
from axiom.hierarchy import update
from axiom.storage import Packed
from axiom.system import System, switch
from axiom.systems import Systems
from axiom.vertices import Vertices
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


def test_saturated_partition_scan_does_not_build_union():
    """Traversal and degree certification must not allocate a temporary set."""
    system = System(Adjacency(4), 0, A={0, 1}, B={2}, U={3})
    system.A = Union(system.A)
    system.B = Union(system.B)

    assert tuple(system.saturated()) == (0, 1, 2)
    assert system.check_bound()


def test_unreachable_switch_path_does_not_snapshot_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(7)
    edges = ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (1, 6))
    for edge in edges:
        graph.add_edge(*edge)
    # The surviving matching is a 2-regular cycle over B; every reachable
    # alternating state is saturated and no nonmatching B edge reaches slack.
    matching = {(1, 2), (1, 6), (2, 3), (3, 4), (4, 5), (5, 6)}
    degree = {0: 0, 1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2}
    beforematching = matching.copy()
    beforedegree = degree.copy()

    def reject_snapshot(value):
        raise AssertionError("unreachable switch copied graph-sized matching state")

    monkeypatch.setattr("axiom.system.set", reject_snapshot, raising=False)

    assert not switch(graph, matching, degree, 2, 0, [1])
    assert matching == beforematching
    assert degree == beforedegree


def switchcase(matchingtype=set):
    graph = Adjacency(7)
    edges = ((0, 1), (1, 2), (1, 4), (2, 3), (2, 5), (4, 6))
    for edge in edges:
        graph.add_edge(*edge)
    matching = matchingtype({(1, 2), (1, 4), (2, 5), (4, 6)})
    degree = {0: 0, 1: 2, 2: 2, 3: 0, 4: 2, 5: 1, 6: 1}
    return graph, matching, degree


def test_switch_success_uses_path_sized_state_and_preserves_degree_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph, matching, degree = switchcase()

    def reject_snapshot(value):
        raise AssertionError("switch copied graph-sized matching state")

    monkeypatch.setattr("axiom.system.set", reject_snapshot, raising=False)
    monkeypatch.setattr("axiom.system.dict", reject_snapshot, raising=False)

    assert switch(graph, matching, degree, 2, 0, [1])
    assert matching == {(1, 4), (2, 5), (4, 6), (0, 1), (2, 3)}
    assert degree == {0: 1, 1: 2, 2: 2, 3: 1, 4: 2, 5: 1, 6: 1}


def test_switch_mid_commit_failure_restores_exact_local_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSet(set):
        additions = 0

        def add(self, edge):
            self.additions += 1
            if self.additions == 2:
                raise RuntimeError("injected switch add failure")
            super().add(edge)

    graph, matching, degree = switchcase(FailingSet)
    beforematching = matching.copy()
    beforedegree = degree.copy()

    def reject_snapshot(value):
        raise AssertionError("switch copied graph-sized matching state")

    monkeypatch.setattr("axiom.system.set", reject_snapshot, raising=False)
    monkeypatch.setattr("axiom.system.dict", reject_snapshot, raising=False)

    with pytest.raises(RuntimeError, match="injected switch add failure"):
        switch(graph, matching, degree, 2, 0, [1])

    assert matching == beforematching
    assert degree == beforedegree


def test_switch_degree_commit_failure_restores_exact_local_state() -> None:
    class FailingDict(dict):
        writes = 0

        def __setitem__(self, vertex, value):
            self.writes += 1
            if self.writes == 2:
                raise RuntimeError("injected switch degree failure")
            super().__setitem__(vertex, value)

    graph, matching, initialdegree = switchcase()
    degree = FailingDict(initialdegree)
    beforematching = matching.copy()
    beforedegree = degree.copy()

    with pytest.raises(RuntimeError, match="injected switch degree failure"):
        switch(graph, matching, degree, 2, 0, [1])

    assert matching == beforematching
    assert degree == beforedegree


def test_dense_system_partitions_use_compact_set_semantics():
    """Dense A/B save hash storage while sparse partitions retain Python sets."""
    graph = Adjacency(128)
    left = set(range(40))
    right = set(range(40, 80))
    rest = set(range(80, 128))
    system = System(graph, 0, A=left, B=right, U=rest)

    assert type(system.A) is Vertices and type(system.B) is Vertices
    assert type(system.U) is Vertices
    assert tuple(system.A) == tuple(left)
    assert tuple(system.B) == tuple(right)
    assert system.check_partition() and system.check_bound()
    assert system.S == left | right
    system.A.add(80)
    system.A.discard(80)
    system.B.add(81)
    system.B.discard(81)
    assert system.check_partition()

    sparse = System(Adjacency(128), 0, A={0}, B={1}, U=set(range(2, 128)))
    assert type(sparse.A) is set and type(sparse.B) is set

    crossover = System(
        Adjacency(128),
        0,
        A=set(range(15)),
        B=set(range(15, 31)),
        U=set(range(31, 128)),
    )
    assert type(crossover.A) is set
    assert type(crossover.B) is Vertices


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
            assert original and not values
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
    assert list(system.lambda_lists[2]) == [1, 3]
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
