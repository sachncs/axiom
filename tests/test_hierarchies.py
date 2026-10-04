"""Identity-preserving transaction tests for recursive hierarchy roots."""

import random
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.hierarchies import Hierarchies
from axiom.hierarchy import Hierarchy, build_hierarchy, project, refine_hierarchy
from axiom.paper_coloring import Paper
from axiom.rebuild import copy as copysystem
from axiom.storage import Packed
from axiom.system import build as buildsystem
from axiom.vertices import Vertices
from axiom.witness import Witness


def populated():
    graph = Packed(16)
    for vertex in range(16):
        graph.add_edge(vertex, (vertex + 1) % 16)
    return Matcher(16, graph=graph, mode="multilevel")


@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_ordered_projection_stream_builds_compact_isolated_graph(backend):
    source = backend(8)
    for edge in ((0, 4), (1, 3), (2, 7)):
        source.add_edge(*edge)
    edges = tuple(source.edges())
    visited = []

    def stream():
        for edge in edges:
            visited.append(edge)
            yield edge

    child = project(source, stream(), ordered=True)

    assert isinstance(child, Packed)
    assert list(child.edges()) == list(edges)
    assert tuple(visited) == edges
    child.remove_edge(*edges[0])
    assert source.has_edge(*edges[0])
    if isinstance(source, Packed):
        assert child.memory()["budget"] == source.memory()["budget"]


def test_ordered_projection_rejects_an_unsorted_stream():
    source = Packed(4)
    source.add_edge(0, 1)

    with pytest.raises(ValueError, match="strictly increasing"):
        project(source, iter(((1, 2), (0, 1))), ordered=True)


def test_unordered_custom_projection_retains_sorted_reference_fallback():
    class Custom:
        def __init__(self, graph: Adjacency) -> None:
            self.graph = graph

        def __getattr__(self, name: str):
            return getattr(self.graph, name)

    backing = Adjacency(6)
    for edge in ((1, 5), (0, 4), (2, 3)):
        backing.add_edge(*edge)
    source = Custom(backing)
    child = project(source, set(backing.edges()))

    assert isinstance(child, Adjacency)
    assert list(child.edges()) == sorted(backing.edges())


def test_refinement_does_not_materialize_old_saturated_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(64)
    for vertex in range(64):
        for neighbor in (vertex + 1, vertex + 7):
            if neighbor < 64:
                graph.add_edge(vertex, neighbor)
    hierarchy = build_hierarchy(graph, [8, 4])
    previous = hierarchy.levels[-1]
    assert isinstance(previous.A, Vertices)
    assert isinstance(previous.B, Vertices)

    def reject_union(self, other):
        raise AssertionError("refinement materialized A union B")

    monkeypatch.setattr(Vertices, "__or__", reject_union)
    refined = refine_hierarchy(hierarchy, 2)

    assert refined.check()


def test_refinement_compares_coloring_keys_without_copying_edge_sets() -> None:
    """Successful completeness validation must not iterate/copy all color keys."""

    class KeyViewOnly(dict):
        def __iter__(self):
            raise AssertionError("refinement copied the full coloring key set")

    class KeyViewColorer(Paper):
        @classmethod
        def color(cls, graph, delta):
            coloring = super().color(graph, delta)
            return KeyViewOnly(coloring.items())

    graph = Packed(16)
    for vertex in range(16):
        graph.add_edge(vertex, (vertex + 1) % 16)
    hierarchy = build_hierarchy(graph, [4])

    refined = refine_hierarchy(hierarchy, 2, colorer=KeyViewColorer())

    assert refined.check()


@pytest.mark.parametrize("delete_count", [0, 1, 3, 11, 36])
def test_refinement_color_count_scans_match_reference_with_ties_and_empty_colors(
    delete_count: int,
) -> None:
    """The count-row path preserves class order and the deferred-edge budget."""
    graph = Adjacency(16)
    for left in range(16):
        for right in range(left + 1, 16):
            graph.add_edge(left, right)
    base = build_hierarchy(graph, [8])
    previous = base.levels[-1]
    deleted_matching = set(sorted(previous.M)[:delete_count])
    nonmatching = next(edge for edge in sorted(graph.edges()) if edge not in previous.M)
    deleted = deleted_matching | {nonmatching}

    coloring = Paper.color(project(graph, previous.M), previous.z)
    retained = deleted & previous.M
    classes = {color: set() for color in range(previous.z + 1)}
    for edge, color in coloring.items():
        classes[color].add(edge)
    order = sorted(
        classes,
        key=lambda color: (len(classes[color] & retained), color),
    )
    selected = set(order[:4])
    expected = {
        edge for color in selected for edge in classes[color] if edge in retained
    }

    refined = refine_hierarchy(base, 4, deleted=deleted)

    assert refined.deferred_deletions == expected
    assert len(expected) <= len(retained) * 4 // previous.z
    assert refined.check()


def test_sparse_hierarchy_check_does_not_allocate_vertex_degree_arrays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Packed(1024)
    graph.add_edge(0, 1)
    hierarchy = build_hierarchy(graph, [1])

    def reject_dense_counts(size: int):
        raise AssertionError(f"sparse matching allocated {size} degree counters")

    monkeypatch.setattr("axiom.hierarchy.degrees", reject_dense_counts)

    assert hierarchy.check()


def test_sparse_hierarchy_refinement_does_not_allocate_universe_degrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Packed(1024)
    for vertex in range(1, 5):
        graph.add_edge(0, vertex)
    hierarchy = build_hierarchy(graph, [4])
    assert hierarchy.levels[-1].M

    def reject_dense_counts(size: int):
        raise AssertionError(f"sparse refinement allocated {size} degree counters")

    def reject_cycle_snapshots(values):
        raise AssertionError("refinement materialized a full cycle-key snapshot")

    monkeypatch.setattr("axiom.hierarchy.degrees", reject_dense_counts)
    monkeypatch.setattr(
        "axiom.hierarchy.frozenset", reject_cycle_snapshots, raising=False
    )

    refined = refine_hierarchy(hierarchy, 2)

    assert refined.check()
    assert len(refined.levels[-1].M) == 2


def test_hierarchy_degree_counts_use_dense_storage_for_dense_matchings() -> None:
    graph = Packed(64)
    hierarchy = build_hierarchy(graph, [1])
    matching = {(vertex, vertex + 1) for vertex in range(0, 32, 2)}

    counts = hierarchy.counts(matching, 1)

    assert counts is not None
    assert not isinstance(counts, dict)
    assert counts[0] == counts[1] == 1
    assert counts[32] == 0


def test_derived_hierarchy_partitions_share_exact_roots_when_possible():
    """Avoid copies of A1/N1 and a single upper A partition."""
    graphs = []
    ring = Adjacency(64)
    for vertex in range(64):
        ring.add_edge(vertex, (vertex + 1) % 64)
        ring.add_edge(vertex, (vertex + 7) % 64)
    graphs.append(ring)

    source = random.Random(0)
    varied = Adjacency(32)
    for left in range(32):
        for right in range(left + 1, 32):
            if source.random() < 0.08:
                varied.add_edge(left, right)
    graphs.append(varied)

    for graph in graphs:
        hierarchy = build_hierarchy(graph, [8, 4, 2])
        assert hierarchy.check()
        assert hierarchy.A1 is hierarchy.A_levels[0]
        assert hierarchy.N1 is hierarchy.N_levels[0]
        assert hierarchy.A_levels[0] is hierarchy.levels[0].A
        assert hierarchy.N_levels[0] is hierarchy.levels[0].B
        assert hierarchy.R_levels[-1] is hierarchy.levels[-1].U
        assert all(
            isinstance(region, Vertices)
            for region in hierarchy.R_levels[:-1]
            if len(region) * 8 >= graph.n
        )
        assert all(
            type(partition) is Vertices
            for partition in hierarchy.A_levels
            if len(partition) * 4 >= graph.n
        )
        upper = [level for level in hierarchy.A_levels[1:] if level]
        assert hierarchy.A2 == set().union(*upper)
        if len(upper) == 1:
            assert hierarchy.A2 is upper[0]
        else:
            assert all(hierarchy.A2 is not level for level in upper)


def test_hierarchy_builder_refines_a_detached_level_one_system():
    graph = Adjacency(64)
    for vertex in range(64):
        graph.add_edge(vertex, (vertex + 1) % 64)
        graph.add_edge(vertex, (vertex + 7) % 64)

    baseline = build_hierarchy(graph, [8, 4, 2])
    preserved = buildsystem(graph, 8)
    roots = (preserved.A, preserved.B, preserved.U, preserved.M)
    candidate = copysystem(preserved, graph)
    hierarchy = build_hierarchy(graph, [8, 4, 2], first=candidate)

    assert hierarchy.check()
    assert preserved.check()
    assert all(
        current is original
        for current, original in zip(
            (preserved.A, preserved.B, preserved.U, preserved.M), roots, strict=True
        )
    )
    assert [level.M for level in hierarchy.levels] == [
        level.M for level in baseline.levels
    ]
    assert [set(level.A) for level in hierarchy.levels] == [
        set(level.A) for level in baseline.levels
    ]


def test_hierarchy_builder_rejects_incompatible_initial_system():
    graph = Adjacency(8)
    other = Adjacency(8)
    valid = buildsystem(graph, 4)

    with pytest.raises(ValueError, match="match the graph and z"):
        build_hierarchy(graph, [4, 2], first=copysystem(valid, other))
    with pytest.raises(ValueError, match="match the graph and z"):
        build_hierarchy(graph, [2, 1], first=valid)

    busy = copysystem(valid, graph)
    busy.journal = object()  # type: ignore[assignment]
    with pytest.raises(ValueError, match="idle"):
        build_hierarchy(graph, [4, 2], first=busy)


def test_partition_union_and_region_certificates_are_exact_without_materializing():
    hierarchy = Hierarchy(Adjacency(6), k=1)

    assert hierarchy.unionequals({0, 1, 2, 3}, [{0, 1}, {2, 3}])
    assert not hierarchy.unionequals({0, 1, 2, 3}, [{0, 1}, {2}])
    assert not hierarchy.unionequals({0, 1, 2}, [{0, 1}, {1, 2}])
    assert hierarchy.regionequals({0, 2}, [{0, 1}, {2, 3}], {1, 3})
    assert not hierarchy.regionequals({0, 1, 2}, [{0, 1}, {2, 3}], {1, 3})
    assert not hierarchy.regionequals({0}, [{0, 1}, {2}], {1})

    sparse = Hierarchy(Adjacency(128), k=1)
    assert sparse.unionequals({1, 4}, [{1}, {4}])
    assert not sparse.unionequals({1, 4}, [{1}, {5}])
    assert sparse.regionequals({1}, [{1, 2}], {2})
    assert not sparse.regionequals({1, 2}, [{1, 2}], {2})


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


def test_endpoint_certificate_detects_corrupt_system_cache():
    matcher = populated()
    root = matcher.multi
    assert root is not None
    level = root.levels[0]
    vertex = next(iter(level.U))
    level.lambda_lists[vertex] = [-1]
    left, right = sorted((vertex, (vertex + 1) % matcher.n))

    assert not root.certify(left, right)


def test_endpoint_certificate_reads_each_high_degree_row_once_across_levels():
    class CountedAdjacency(Adjacency):
        def __init__(self, n: int) -> None:
            super().__init__(n)
            self.reads: dict[int, int] = {}

        def neighbors(self, vertex: int) -> Iterator[int]:
            self.reads[vertex] = self.reads.get(vertex, 0) + 1
            return super().neighbors(vertex)

    graph = CountedAdjacency(64)
    for vertex in range(1, graph.n):
        graph.add_edge(0, vertex)
    hierarchy = build_hierarchy(graph, [32, 16, 8])

    # Refinement normally compacts projections into Packed. Rebind the
    # equivalent adjacency graph to expose neighbor-row traversal counts.
    hierarchy.graph = graph
    for level in hierarchy.levels:
        level.graph = graph
    graph.reads.clear()

    assert hierarchy.diagnose(0, 1) is None
    assert graph.reads == {0: 1, 1: 1}


def test_endpoint_certificate_failure_rolls_back_exact_matcher_state(monkeypatch):
    matcher = populated()
    root = matcher.multi
    assert root is not None
    before = Witness().capture(matcher)

    def reject(self, left, right):
        return False

    monkeypatch.setattr(Hierarchy, "certify", reject)
    with pytest.raises(RuntimeError, match="endpoint certificate failed"):
        matcher.insert(0, 4)

    assert matcher.multi is root
    assert matcher.hierarchies is None
    assert root.journal is None
    assert Witness().capture(matcher) == before


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
