"""Full logical-state differential checks for the paper migration."""

import random

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.paper_coloring import Fan, Fans, Partial
from axiom.storage import Packed
from axiom.witness import Witness


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_every_replayed_prefix_restores_full_paper_state(mode, backend):
    rng = random.Random(599)
    matcher = Matcher(8, mode=mode, graph=backend(8))
    trace = []
    witness = Witness()
    for _ in range(45):
        left, right = rng.sample(range(8), 2)
        method = "insert" if rng.random() < 0.6 else "delete"
        trace.append((method, left, right))
        getattr(matcher, method)(left, right)
        replay = Matcher(8, mode=mode, graph=backend(8))
        for operation, u, v in trace:
            getattr(replay, operation)(u, v)
        assert witness.capture(matcher) == witness.capture(replay)
        assert matcher.maximal() and replay.maximal()
        assert matcher.partner_map == replay.partner_map
        if matcher.multi is not None:
            assert matcher.multi.check()
        elif matcher.update_count == 0:
            # Basic keeps its phase partition between rebuilds; the static
            # saturated-degree certificate is a rebuild boundary invariant.
            assert matcher.system.check()
    assert matcher.accountant.phase_rebuilds > 1


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
@pytest.mark.parametrize("adding", [False, True])
def test_failure_after_rebuild_restores_full_state_and_retry(
    mode, backend, adding, monkeypatch
):
    graph = backend(16)
    for vertex in range(16):
        graph.add_edge(vertex, (vertex + 1) % 16)
    matcher = Matcher(16, mode=mode, graph=graph)
    matcher.phase_length = 1
    witness = Witness()
    before = witness.capture(matcher)
    original = Matcher._Matcher__advance_update_counter

    def fail(owner):
        original(owner)
        raise RuntimeError("after rebuild")

    with monkeypatch.context() as patch:
        patch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
        with pytest.raises(RuntimeError, match="after rebuild"):
            getattr(matcher, "insert" if adding else "delete")(0, 4 if adding else 1)
    assert witness.capture(matcher) == before
    assert matcher.graph is graph
    assert matcher.maximal()
    getattr(matcher, "insert" if adding else "delete")(0, 4 if adding else 1)
    assert witness.capture(matcher) != before
    assert matcher.maximal()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_noop_deletion_is_accounted_state_not_only_topology(mode):
    matcher = Matcher(8, mode=mode, graph=Packed(8))
    witness = Witness()
    before = witness.capture(matcher)
    version = matcher.graph.version
    matcher.delete(0, 1)
    assert witness.capture(matcher) != before
    assert matcher.graph.version == version
    assert matcher.matching() == set()
    assert matcher.accountant.total_deletions == 1


def test_aliases_are_preserved_but_process_addresses_are_not():
    left, right = [], []
    witness = Witness()
    assert witness.capture([left, left]) == witness.capture([right, right])
    assert witness.capture([left, left]) != witness.capture([left, right])
    left.append(left)
    right.append(right)
    assert witness.capture(left) == witness.capture(right)
    assert witness.objects == [] and witness.references == {}


def test_cached_indexes_and_phase_work_cannot_be_silently_recomputed():
    matcher = Matcher(8, mode="multilevel")
    witness = Witness()
    before = witness.capture(matcher)
    matcher.accountant.phase_update_work += 1
    assert witness.capture(matcher) != before
    matcher.accountant.phase_update_work -= 1
    assert witness.capture(matcher) == before
    matcher.H[0] = {1}
    assert witness.capture(matcher) != before


def test_equal_cardinality_valid_matchings_are_not_exact_recovery():
    graph = Adjacency(4)
    for edge in ((0, 1), (1, 2), (2, 3), (0, 3)):
        graph.add_edge(*edge)
    matcher = Matcher(4, graph=graph)
    witness = Witness()
    before = witness.capture(matcher)
    initial = matcher.matching()
    matching = {(0, 1), (2, 3)}
    matcher.seed_matching = matching if initial != matching else {(0, 3), (1, 2)}
    matcher.refresh()
    assert matcher.maximal() and len(matcher.matching()) == len(initial) == 2
    assert matcher.matching() != initial
    assert witness.capture(matcher) != before


def test_native_versions_and_hierarchy_graph_aliases_are_observable():
    graph = Packed(4)
    empty = Packed(4)
    graph.add_edge(0, 1)
    graph.remove_edge(0, 1)
    witness = Witness()
    assert list(graph.edges()) == list(empty.edges()) == []
    assert witness.capture(graph) != witness.capture(empty)
    assert witness.capture(empty) != witness.capture(Packed(4, budget=1 << 20))
    matcher = Matcher(8, mode="multilevel", graph=Packed(8))
    assert matcher.system is matcher.multi.levels[-1]
    before = witness.capture(matcher)
    original = matcher.system.graph
    matcher.system.graph = original.copy()
    assert list(matcher.system.graph.edges()) == list(original.edges())
    assert matcher.system.graph.version == original.version
    assert witness.capture(matcher) != before
    matcher.system.graph = original
    assert witness.capture(matcher) == before


def test_reference_adjacency_captures_redundant_rows_and_count():
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    witness = Witness()
    before = witness.capture(graph)
    graph.adj[1].clear()
    assert list(graph.edges()) == [(0, 1)]
    assert witness.capture(graph) != before
    graph.adj[1].add(0)
    assert witness.capture(graph) == before
    graph.edge_count += 1
    assert witness.capture(graph) != before


def test_ordering_and_type_tags_are_unambiguous():
    witness = Witness()
    assert witness.capture({1: [2], 3: [4]}) == witness.capture({3: [4], 1: [2]})
    assert witness.capture({Fan(0, 1, 2, 0, 1, 1), (1, 2)}) == witness.capture(
        {(1, 2), Fan(0, 1, 2, 0, 1, 1)}
    )
    assert len({witness.capture(value) for value in (True, 1, "1", 1.0)}) == 4
    assert witness.capture(-0.0) != witness.capture(0.0)


@pytest.mark.parametrize("limit", ["nodes", "depth", "capacity"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_limits_are_rejected(limit, value):
    with pytest.raises(ValueError, match="positive integers"):
        Witness(**{limit: value})


@pytest.mark.parametrize("limit", ["nodes", "depth", "capacity"])
def test_limit_failure_leaves_source_unchanged_and_capture_reusable(limit):
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    witness = Witness(**{limit: 1})
    before = Witness().capture(graph)
    with pytest.raises(ValueError, match="limit exceeded"):
        witness.capture(graph)
    assert Witness().capture(graph) == before
    assert witness.objects == [] and witness.references == {}
    setattr(witness, limit, 100_000)
    assert witness.capture(graph) == before


def test_unknown_strategies_fields_and_atoms_fail_closed():
    witness = Witness()
    matcher = Matcher(4)
    matcher.extra = 1
    with pytest.raises(TypeError, match="fields"):
        witness.capture(matcher)
    del matcher.extra
    matcher.colorer = object()
    with pytest.raises(TypeError, match="atom"):
        witness.capture(matcher)
    for value in (object(), float("nan"), float("inf")):
        with pytest.raises(TypeError, match="atom"):
            witness.capture(value)


def test_fan_and_coloring_redundant_indexes_are_included():
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring, fans = Partial(graph, 2), Fans()
    fan = Fan(0, 1, 2, 0, 1, 1)
    fans.add(fan)
    fans.compatible(coloring)
    witness = Witness()
    before = witness.capture((coloring, fans))
    fans.types[fan.type].clear()
    assert witness.capture((coloring, fans)) != before
    fans.types[fan.type].add(fan)
    assert witness.capture((coloring, fans)) == before
    coloring.incident[0].add(1)
    assert witness.capture((coloring, fans)) != before
