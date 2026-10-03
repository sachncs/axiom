from __future__ import annotations

import gc
import random
from concurrent.futures import ThreadPoolExecutor

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.paper_coloring import Paper
from axiom.storage import Packed, publish
from axiom.types import Graph


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_phase_overlay_allocates_only_live_incident_buckets(
    mode: str, backend: type
) -> None:
    matcher = Matcher(64, graph=backend(64), mode=mode)
    assert matcher.inserted_incident_edges == {}
    assert matcher.inserted_incident_counts == {}
    rng = random.Random(599)
    for _ in range(160):
        u, v = rng.sample(range(64), 2)
        if matcher.graph.has_edge(u, v):
            matcher.delete(u, v)
        else:
            matcher.insert(u, v)
        endpoints = {vertex for edge in matcher.inserted_edges for vertex in edge}
        assert set(matcher.inserted_incident_edges) == endpoints
        assert all(matcher.inserted_incident_edges.values())
        assert all(count > 0 for count in matcher.inserted_incident_counts.values())
        assert len(matcher.inserted_incident_edges) <= 2 * len(matcher.inserted_edges)
        assert matcher._Matcher__check_auxiliary_indexes()
        assert matcher.maximal()
        if mode == "basic":
            assert (
                matcher.inserted_incident_edges
                == matcher.inserted_incident_counts
                == {}
            )


def test_sparse_overlay_validator_rejects_empty_and_extraneous_buckets() -> None:
    matcher = Matcher(64, mode="multilevel")
    matcher.insert(0, 1)
    matcher.inserted_incident_edges[63] = set()
    assert not matcher._Matcher__check_auxiliary_indexes()
    del matcher.inserted_incident_edges[63]
    matcher.inserted_incident_edges[63] = {(0, 1)}
    assert not matcher._Matcher__check_auxiliary_indexes()
    del matcher.inserted_incident_edges[63]
    assert matcher._Matcher__check_auxiliary_indexes()


def test_group_publication_validates_all_tokens_before_committing_any() -> None:
    left, right = Packed(4), Packed(4)
    first, second = left.begin(), right.begin()
    left.add_edge(0, 1)
    right.add_edge(2, 3)
    with pytest.raises(RuntimeError, match="stale"):
        publish([(left, first), (right, second + 1)])
    assert left.memory()["active"] == right.memory()["active"] == 1
    left.rollback(first)
    right.rollback(second)
    assert left.num_edges() == right.num_edges() == 0
    first, second = left.begin(), right.begin()
    left.add_edge(0, 1)
    right.add_edge(2, 3)
    publish([(left, first), (right, second)])
    assert left.memory()["active"] == right.memory()["active"] == 0
    assert left.version == right.version == 1
    assert left.check() and right.check()


def test_native_contract_cannot_be_overridden() -> None:
    with pytest.raises(TypeError):
        type("MutablePacked", (Packed,), {})
    with pytest.raises(TypeError):
        Packed.add_edge = lambda *args: None  # type: ignore[method-assign]


def test_native_high_degree_paper_coloring_and_euler_projection() -> None:
    graph = Packed(35)
    graph.ring(16)
    original, version = set(graph.edges()), graph.version
    parts = Paper.partition(graph)
    assert all(isinstance(part, Packed) and part.check() for part in parts)
    assert set(parts[0].edges()).isdisjoint(parts[1].edges())
    assert set(parts[0].edges()) | set(parts[1].edges()) == original
    coloring = Paper.color(graph, 32)
    assert set(coloring) == original
    for vertex in range(graph.n):
        colors = [
            coloring[min(vertex, neighbor), max(vertex, neighbor)]
            for neighbor in graph.neighbors(vertex)
        ]
        assert len(colors) == len(set(colors))
        assert all(0 <= color <= 32 for color in colors)
    assert graph.version == version and set(graph.edges()) == original
    assert graph.check()


@pytest.mark.parametrize("publish", ["compact", "ring"])
def test_candidate_publication_does_not_reuse_stale_tokens(publish: str) -> None:
    graph = Packed(16)
    stale = graph.begin()
    graph.commit(stale)
    getattr(graph, publish)()
    current = graph.begin()
    assert current > stale
    with pytest.raises(RuntimeError, match="stale"):
        graph.commit(stale)
    graph.rollback(current)


def test_journal_admission_failure_closes_native_journals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from axiom.clocks import Clocks

    graph = Packed(16)
    graph.ring()
    matcher = Matcher(16, graph=graph, mode="multilevel")
    before = list(graph.edges()), graph.version

    def failure(*args: object, **kwargs: object) -> object:
        raise MemoryError("injected clock journal admission failure")

    monkeypatch.setattr(Clocks, "__init__", failure)
    with pytest.raises(MemoryError, match="injected clock"):
        matcher.insert(0, 4)
    assert (list(graph.edges()), graph.version) == before
    for part in (graph, matcher.phase_graph, matcher.phase_base_graph):
        assert isinstance(part, Packed)
        assert part.memory()["active"] == 0 and part.check()


def test_journal_restores_promotions_contents_and_version() -> None:
    graph = Packed(160)
    for hub in range(4):
        for leaf in range(10, 41):
            graph.add_edge(hub, leaf)
    original = list(graph.edges())
    version = graph.version
    iterator = graph.neighbors(0)
    token = graph.begin()
    for hub in range(4):
        graph.add_edge(hub, 41)
    for leaf in range(10, 42):
        graph.remove_edge(0, leaf)
    graph.add_edge(0, 100)
    transient = graph.neighbors(0)
    graph.rollback(token)
    assert list(graph.edges()) == original
    assert graph.version == version
    assert graph.check()
    for cursor in (iterator, transient):
        with pytest.raises(RuntimeError, match="changed"):
            next(cursor)
    token = graph.begin()
    graph.add_edge(0, 100)
    graph.commit(token)
    assert graph.version == version + 1
    assert graph.check()


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.tuples(st.booleans(), st.integers(0, 64), st.integers(0, 64)), max_size=300
    )
)
def test_random_journal_rollback(updates: list[tuple[bool, int, int]]) -> None:
    graph = Packed(65)
    graph.ring(16)
    original = list(graph.edges())
    version = graph.version
    token = graph.begin()
    for adding, u, v in updates:
        if adding:
            graph.add_edge(u, v)
        else:
            graph.remove_edge(u, v)
    assert graph.check()
    graph.rollback(token)
    assert graph.version == version
    assert list(graph.edges()) == original
    assert graph.check()


def test_journal_rejects_stale_nested_and_foreign_thread_access() -> None:
    graph = Packed(4)
    token = graph.begin()
    with pytest.raises(RuntimeError, match="nested"):
        graph.begin()
    with pytest.raises(RuntimeError, match="stale"):
        graph.commit(token + 1)
    with pytest.raises(RuntimeError, match="transaction"):
        graph.compact()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(graph.add_edge, 0, 1)
        with pytest.raises(RuntimeError, match="another thread"):
            future.result()
    graph.add_edge(0, 1)
    graph.rollback(token)
    with pytest.raises(RuntimeError, match="stale"):
        graph.rollback(token)
    assert graph.version == graph.num_edges() == 0
    assert graph.check()


def test_journal_budget_failure_leaves_original_edge_and_can_rollback() -> None:
    metadata = Packed(4).memory()["metadata"]
    graph = Packed(4, budget=metadata + 56)
    graph.add_edge(0, 1)
    token = graph.begin()
    with pytest.raises(MemoryError, match="journal"):
        graph.remove_edge(0, 1)
    assert graph.has_edge(0, 1)
    graph.rollback(token)
    assert graph.version == 1
    assert graph.check()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("adding", [False, True])
def test_matcher_native_rollback_restores_version_and_remains_usable(
    mode: str, adding: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = Packed(16)
    graph.ring()
    matcher = Matcher(16, graph=graph, mode=mode)
    matcher.phase_length = 1
    managed = [matcher.phase_graph]
    if matcher.multi is not None:
        managed.extend(
            [matcher.multi.graph, *(level.graph for level in matcher.multi.levels)]
        )
    originals = [
        (part, list(part.edges()), part.version) for part in managed if part is not None
    ]
    assert all(isinstance(part, Packed) for part, _, _ in originals)
    before = (
        list(graph.edges()),
        graph.version,
        matcher.matching(),
        matcher.stats(),
    )
    edge = (0, 4) if adding else (0, 1)
    method = "_Matcher__advance_update_counter"
    original = getattr(matcher, method)

    def failure() -> None:
        original()
        raise RuntimeError("injected after repair")

    monkeypatch.setattr(matcher, method, failure)
    update = matcher.insert if adding else matcher.delete
    with pytest.raises(RuntimeError, match="injected"):
        update(*edge)
    assert matcher.graph is graph
    assert (
        list(graph.edges()),
        graph.version,
        matcher.matching(),
        matcher.stats(),
    ) == before
    assert graph.check() and matcher.maximal()
    assert graph.memory()["active"] == 0
    for part, edges, version in originals:
        assert list(part.edges()) == edges
        assert part.version == version
        assert part.check() and part.memory()["active"] == 0
    monkeypatch.setattr(matcher, method, original)
    update(*edge)
    assert graph.version == before[1] + 1
    assert graph.check() and matcher.maximal()


@pytest.mark.parametrize("vertices", [0, 1, 2, 33, 128])
def test_empty_storage_implements_graph_contract(vertices: int) -> None:
    graph = Packed(vertices)
    assert isinstance(graph, Graph)
    assert graph.n == vertices
    assert graph.num_edges() == graph.version == 0
    assert list(graph.edges()) == []
    assert graph.check()
    assert graph.memory()["allocated"] <= graph.memory()["budget"]
    if vertices:
        assert graph.degree(0) == 0
        assert list(graph.neighbors(0)) == []


@settings(max_examples=50, deadline=None)
@given(
    st.lists(
        st.tuples(st.booleans(), st.integers(0, 64), st.integers(0, 64)),
        min_size=1,
        max_size=300,
    )
)
def test_native_updates_differentially_match_reference(
    updates: list[tuple[bool, int, int]],
) -> None:
    graph = Packed(65)
    reference = Adjacency(65)
    version = 0
    for adding, left, right in updates:
        present = reference.has_edge(left, right)
        changed = left != right and present != adding
        if adding:
            graph.add_edge(left, right)
            reference.add_edge(left, right)
        else:
            graph.remove_edge(left, right)
            reference.remove_edge(left, right)
        version += changed
        assert graph.version == version
        assert graph.num_edges() == reference.num_edges()
        assert graph.check()
        assert list(graph.neighbors(left)) == list(reference.neighbors(left))
    assert list(graph.edges()) == list(reference.edges())


def test_high_degree_index_crossings_and_tombstone_rehashes() -> None:
    graph = Packed(257)
    reference = Adjacency(257)
    rng = random.Random(19)
    for repetition in range(12):
        order = list(range(1, 257))
        rng.shuffle(order)
        for vertex in order:
            graph.add_edge(0, vertex)
            reference.add_edge(0, vertex)
        assert graph.memory()["index"] > 0
        assert graph.check()
        rng.shuffle(order)
        for vertex in order:
            graph.remove_edge(vertex, 0)
            reference.remove_edge(vertex, 0)
            assert graph.has_edge(0, vertex) is False
        assert graph.check()
        assert graph.num_edges() == 0
        assert graph.memory()["liveblocks"] == 0
        if repetition == 0:
            allocated = graph.memory()["allocated"]
        else:
            assert graph.memory()["allocated"] <= allocated
    assert list(graph.edges()) == list(reference.edges())


def test_budget_failure_is_atomic_and_freed_blocks_remain_usable() -> None:
    metadata = Packed(4).memory()["metadata"]
    graph = Packed(4, budget=metadata + 2 * 28)
    graph.add_edge(0, 1)
    before = list(graph.edges()), graph.version, [graph.degree(v) for v in range(4)]
    with pytest.raises(MemoryError, match="budget"):
        graph.add_edge(1, 2)
    assert (
        list(graph.edges()),
        graph.version,
        [graph.degree(v) for v in range(4)],
    ) == before
    assert graph.check()
    graph.remove_edge(0, 1)
    graph.add_edge(2, 3)
    assert list(graph.edges()) == [(2, 3)]
    assert graph.check()


def test_budget_failure_at_high_degree_promotion_preserves_both_rows() -> None:
    metadata = Packed(257).memory()["metadata"]
    graph = Packed(257, budget=metadata + 384 * 28)
    for vertex in range(1, 128):
        graph.add_edge(0, vertex)
    before = list(graph.edges()), graph.version
    with pytest.raises(MemoryError, match="index.*budget"):
        graph.add_edge(0, 128)
    assert (list(graph.edges()), graph.version) == before
    assert graph.degree(128) == 0
    assert graph.check()
    graph.remove_edge(0, 1)
    graph.add_edge(0, 128)
    assert graph.check()


def test_degree64_ring_avoids_global_index_and_preserves_exact_rollback() -> None:
    graph = Packed(256, budget=200 << 10)
    graph.ring(32)
    before = list(graph.edges()), graph.version
    assert graph.memory()["index"] == 0
    assert graph.memory()["allocated"] < 200 << 10
    assert all(graph.degree(vertex) == 64 for vertex in range(256))
    for vertex in range(256):
        expected = sorted(
            {(vertex + offset) % 256 for offset in range(-32, 33) if offset}
        )
        assert list(graph.neighbors(vertex)) == expected
    token = graph.begin()
    graph.remove_edge(0, 1)
    graph.remove_edge(80, 81)
    graph.add_edge(0, 80)
    graph.rollback(token)
    assert (list(graph.edges()), graph.version) == before
    assert graph.memory()["index"] == 0
    assert graph.check()


def test_compaction_publishes_identical_contents_and_reclaims_native_capacity() -> None:
    graph = Packed(100)
    for vertex in range(1, 100):
        graph.add_edge(0, vertex)
    for vertex in range(2, 100):
        graph.remove_edge(0, vertex)
    before = list(graph.edges()), graph.version
    allocated = graph.memory()["allocated"]
    iterator = graph.edges()
    graph.compact()
    assert (list(graph.edges()), graph.version) == before
    assert graph.memory()["allocated"] < allocated
    assert list(iterator) == before[0]
    assert graph.check()


def test_compaction_respects_peak_budget_without_partial_publication() -> None:
    metadata = Packed(4).memory()["metadata"]
    graph = Packed(4, budget=metadata + 56)
    graph.add_edge(0, 1)
    before = list(graph.edges()), graph.version, graph.memory()
    with pytest.raises(MemoryError, match="compaction peak"):
        graph.compact()
    assert (list(graph.edges()), graph.version, graph.memory()) == before
    assert graph.check()


@pytest.mark.parametrize("iterator", ["edges", "neighbors"])
def test_mutation_invalidates_native_iterators_and_noops_do_not(iterator: str) -> None:
    graph = Packed(8)
    graph.ring()
    stream = graph.edges() if iterator == "edges" else graph.neighbors(0)
    graph.add_edge(0, 1)
    next(stream)
    graph.remove_edge(0, 1)
    with pytest.raises(RuntimeError, match="changed"):
        next(stream)
    assert list(stream) == []


def test_iterators_retain_storage_lifetime_without_type_reference_leaks() -> None:
    graph = Packed(5)
    graph.add_edge(0, 4)
    iterator = graph.edges()
    del graph
    gc.collect()
    assert list(iterator) == [(0, 4)]


@pytest.mark.parametrize("vertices,width", [(0, 0), (1, 0), (5, 1), (33, 16), (100, 2)])
def test_ring_construction_and_independent_native_copy(
    vertices: int, width: int
) -> None:
    graph = Packed(vertices)
    graph.ring(width)
    assert graph.num_edges() == vertices * width
    assert graph.check()
    assert all(graph.degree(v) == 2 * width for v in range(vertices))
    copied = graph.copy()
    assert copied.check()
    assert list(copied.edges()) == list(graph.edges())
    assert copied.empty().num_edges() == 0
    if width:
        copied.remove_edge(0, 1)
        assert graph.has_edge(0, 1)


@pytest.mark.parametrize("invalid", [-1, True, 1.5, "4", 2**32])
def test_native_constructor_rejects_invalid_universe_without_allocation(
    invalid: object,
) -> None:
    with pytest.raises(ValueError):
        Packed(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "operation", ["add_edge", "remove_edge", "has_edge", "degree", "neighbors"]
)
@pytest.mark.parametrize("invalid", [-1, 5, True, 1.5, "1", 2**80])
def test_invalid_endpoint_cannot_change_native_graph(
    operation: str, invalid: object
) -> None:
    graph = Packed(5)
    graph.add_edge(0, 1)
    arguments = (invalid,) if operation in {"degree", "neighbors"} else (0, invalid)
    with pytest.raises(ValueError):
        getattr(graph, operation)(*arguments)
    assert list(graph.edges()) == [(0, 1)]
    assert graph.version == 1
    assert graph.check()


def test_native_construction_and_strict_noops_are_safe() -> None:
    graph = Packed(4)
    graph.add_edge(0, 1)
    with pytest.raises(ValueError):
        graph.add_edge(0, 1, strict=True)
    with pytest.raises(ValueError):
        graph.remove_edge(0, 2, strict=True)
    with pytest.raises(ValueError):
        graph.add_edge(2, 2, strict=True)
    with pytest.raises(TypeError):
        Packed.__new__(Packed)
    with pytest.raises(RuntimeError, match="reinitialized"):
        graph.__init__(8)
    assert graph.n == 4
    assert graph.check()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_matcher_preserves_caller_native_storage_through_phase_boundaries(
    mode: str,
) -> None:
    graph = Packed(16)
    graph.ring()
    matcher = Matcher(16, graph=graph, mode=mode)
    reference = set(graph.edges())
    for index in range(128):
        edge = (0, 1) if index % 2 == 0 else (0, 2)
        if edge in reference:
            matcher.delete(*edge)
            reference.remove(edge)
        else:
            matcher.insert(*edge)
            reference.add(edge)
        assert matcher.graph is graph
        assert set(graph.edges()) == reference
        assert graph.check() and matcher.maximal()
