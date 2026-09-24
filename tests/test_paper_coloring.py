from __future__ import annotations

import random

import pytest

from axiom.graph import Adjacency
from axiom.paper_coloring import (
    PaperFanColorer,
    PartialColoring,
    SeparableFans,
    UFan,
    _paper_eta,
    activate_fan,
    classify_type_sparsification,
    collect_direct_fans,
    collect_separable_fans,
    color_blocks,
    color_small,
    extend_recursive,
    fan_is_social,
    modify_types,
    relevant_paths,
    shift_edge_to_fan,
    sparsify_types,
)


def test_paper_eta_selects_only_a_valid_recursive_regime() -> None:
    assert _paper_eta(128, 129) is None
    assert _paper_eta(1024, 1025) == 90
    assert _paper_eta(1024, 99) is None


def test_separable_fans_enforce_edge_and_vertex_color_disjointness() -> None:
    fans = SeparableFans()
    first = UFan(0, 1, 2, 0, 1, 1)
    fans.add(first)
    fans.assert_valid()
    assert fans.find(0, 0) == first
    assert fans.find(1, 1) == first
    assert fans.by_type(first.type) == (first,)
    assert fans.type_counts() == {first.type: 1}
    assert fans.missing(PartialColoring(Adjacency(3), 3), 0) == 1

    with pytest.raises(ValueError, match="edge-disjoint"):
        fans.add(UFan(0, 1, 3, 2, 3, 3))
    with pytest.raises(ValueError, match="colors must be distinct"):
        fans.add(UFan(0, 4, 5, 0, 2, 2))


def test_partial_coloring_flip_preserves_properness() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(1, 2)
    graph.add_edge(2, 3)
    coloring = PartialColoring(graph, 3)
    coloring.assign((1, 2), 1)
    coloring.assign((2, 3), 0)

    path = coloring.alternating_path(1, 0, 1)
    assert path == [1, 2, 3]
    coloring.flip(path, 0, 1)
    assert coloring[(1, 2)] == 0
    assert coloring[(2, 3)] == 1
    assert coloring.missing(1) == [1, 2]


def test_activate_fan_extends_one_uncolored_spoke() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(1, 3)
    coloring = PartialColoring(graph, 2)
    coloring.assign((1, 3), 0)
    fans = SeparableFans()
    fan = UFan(0, 1, 2, 0, 1, 1)
    fans.add(fan)

    extended = activate_fan(coloring, fans, fan)

    assert extended == (0, 1)
    assert coloring[(0, 1)] == 0
    assert (0, 1) in coloring
    assert len(fans) == 0
    fans.assert_valid()


def test_color_small_activates_deterministic_common_type() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(1, 3)
    coloring = PartialColoring(graph, 2)
    coloring.assign((1, 3), 0)
    fans = SeparableFans()
    fan = UFan(0, 1, 2, 0, 1, 1)
    fans.add(fan)

    assert color_small(coloring, fans) == 1
    assert coloring[(0, 1)] == 0
    assert len(fans) == 0


def test_collect_direct_fans_uses_only_supplied_uncolored_edges() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(0, 3)
    coloring = PartialColoring(graph, 3)

    fans = collect_direct_fans(coloring, {(0, 1), (0, 2), (0, 3)})

    fans.assert_valid()
    assert len(fans) == 1
    assert next(iter(fans)).edges == {(0, 1), (0, 2)}


def test_collect_separable_fans_uses_witness_shifts_for_remaining_edges() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = PartialColoring(graph, 3)
    coloring.assign((0, 2), 1)

    fans = collect_separable_fans(coloring, {(0, 1)})

    assert len(fans) == 1
    assert next(iter(fans)).edges == {(0, 1), (0, 2)}
    assert (0, 2) not in coloring
    coloring.validate()
    fans.assert_valid()


def test_extend_recursive_uses_small_base_case() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(1, 3)
    coloring = PartialColoring(graph, 2)
    coloring.assign((1, 3), 0)
    fans = SeparableFans()
    fans.add(UFan(0, 1, 2, 0, 1, 1))

    assert extend_recursive(coloring, fans, 10) == 1
    coloring.validate()
    assert coloring[(0, 1)] == 0


def test_color_blocks_are_ordered_and_disjoint() -> None:
    blocks, pairs = color_blocks(100, 10)

    assert len(blocks) == 20
    assert len(pairs) == 10
    assert all(len(block) == 5 for block in blocks)
    assert set().union(*blocks) == set(range(100))
    assert all(len(pair) == 10 for pair in pairs)


def test_type_sparsification_certificate_is_deterministic_and_non_mutating() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(2, 3)
    coloring = PartialColoring(graph, 4)
    coloring.assign((0, 1), 0)
    before = dict(coloring.items())

    first = classify_type_sparsification(coloring, {(2, 3)}, 2)
    second = classify_type_sparsification(coloring, {(2, 3)}, 2)

    assert first == second
    assert first.blocks == (frozenset({0, 1}), frozenset({2, 3}))
    assert first.diagonal_edges == {(2, 3)}
    assert first.diagonal_fraction == 1.0
    assert dict(coloring.items()) == before
    with pytest.raises(TypeError):
        first.edge_types[(2, 3)] = frozenset()  # type: ignore[index]


def test_type_sparsification_rejects_non_matching_uncolored_edges() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(1, 2)
    coloring = PartialColoring(graph, 2)

    with pytest.raises(ValueError, match="matching"):
        classify_type_sparsification(coloring, {(0, 1), (1, 2)}, 2)


def test_relevant_paths_use_matching_color_offsets() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = PartialColoring(graph, 100)
    fan = UFan(0, 1, 2, 0, 10, 10)
    blocks, _ = color_blocks(100, 10)

    assert not fan_is_social(fan, blocks)
    paths = relevant_paths(coloring, fan, blocks, 1)

    assert [path for path, _, _ in paths] == [(0,), (1,), (2,)]
    assert [source for _, source, _ in paths] == [0, 10, 10]
    assert [target for _, _, target in paths] == [15, 10, 10]


def test_sparsify_types_relabels_small_collection_deterministically() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = PartialColoring(graph, 100)
    fans = SeparableFans()
    fans.add(UFan(0, 1, 2, 0, 10, 10))

    groups, social = sparsify_types(coloring, fans, 10)

    assert len(groups) == 10
    assert len(social) == 1
    assert next(iter(social)).type == frozenset({0, 1})


def test_modify_types_flips_one_batch_and_reindexes_fans() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = PartialColoring(graph, 100)
    fans = SeparableFans()
    fan = UFan(0, 1, 2, 0, 10, 10)
    fans.add(fan)
    blocks, _ = color_blocks(100, 10)

    modify_types(coloring, fans, (fan,), blocks, 0)

    assert len(fans) == 1
    transformed = next(iter(fans))
    assert transformed.type == frozenset({0, 5})
    assert fan_is_social(transformed, blocks)
    coloring.validate()
    fans.assert_valid()


def test_modify_types_restores_state_on_explicit_failure() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = PartialColoring(graph, 100)
    fans = SeparableFans()
    fan = UFan(0, 1, 2, 0, 10, 10)
    fans.add(fan)
    blocks, _ = color_blocks(100, 10)
    colors_before = dict(coloring.items())
    fans_before = tuple(fans)

    with pytest.raises(IndexError):
        modify_types(coloring, fans, (fan,), blocks, 10)

    assert dict(coloring.items()) == colors_before
    assert tuple(fans) == fans_before
    coloring.validate()
    fans.assert_valid()


def test_sparsify_types_socializes_a_full_deterministic_batch() -> None:
    fan_count = 100
    graph = Adjacency(3 * fan_count)
    fans = SeparableFans()
    for index in range(fan_count):
        center = 3 * index
        first_leaf = center + 1
        second_leaf = center + 2
        graph.add_edge(center, first_leaf)
        graph.add_edge(center, second_leaf)
        fans.add(UFan(center, first_leaf, second_leaf, 0, 10, 10))
    coloring = PartialColoring(graph, 100)

    groups, social = sparsify_types(coloring, fans, 10)

    assert len(groups) == 10
    assert len(social) == fan_count
    assert all(fan_is_social(fan, color_blocks(100, 10)[0]) for fan in social)
    coloring.validate()


def test_sparsify_types_preserves_invariants_on_cross_block_batches() -> None:
    blocks, _ = color_blocks(100, 10)
    for seed in range(5):
        rng = random.Random(seed)
        fan_count = 120
        graph = Adjacency(3 * fan_count)
        fans = SeparableFans()
        for index in range(fan_count):
            center = 3 * index
            graph.add_edge(center, center + 1)
            graph.add_edge(center, center + 2)
            center_color = rng.randrange(100)
            leaf_color = rng.randrange(100)
            if center_color == leaf_color:
                leaf_color = (leaf_color + 1) % 100
            fans.add(
                UFan(
                    center,
                    center + 1,
                    center + 2,
                    center_color,
                    leaf_color,
                    leaf_color,
                )
            )
        coloring = PartialColoring(graph, 100)
        colored_before = coloring.edges()

        _, social = sparsify_types(coloring, fans, 10)

        assert len(social) >= 2
        assert all(fan_is_social(fan, blocks) for fan in social)
        assert coloring.edges() == colored_before
        coloring.validate()
        social.assert_valid()


def test_sparsify_types_restores_state_on_batch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import axiom.paper_coloring as paper_coloring

    fan_count = 100
    graph = Adjacency(3 * fan_count)
    fans = SeparableFans()
    for index in range(fan_count):
        center = 3 * index
        graph.add_edge(center, center + 1)
        graph.add_edge(center, center + 2)
        low = index % 50
        high = low + 50
        fans.add(UFan(center, center + 1, center + 2, low, high, high))
    coloring = PartialColoring(graph, 100)
    colors_before = dict(coloring.items())
    fans_before = tuple(fans)

    def fail_batch(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected sparsification failure")

    monkeypatch.setattr(paper_coloring, "modify_types", fail_batch)
    with pytest.raises(RuntimeError, match="injected sparsification failure"):
        sparsify_types(coloring, fans, 10)

    assert dict(coloring.items()) == colors_before
    assert tuple(fans) == fans_before
    coloring.validate()
    fans.assert_valid()


def test_shift_edge_to_fan_preserves_partial_coloring() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = PartialColoring(graph, 3)
    coloring.assign((0, 2), 1)
    fans = SeparableFans()

    fan = shift_edge_to_fan(coloring, (0, 1), fans)

    assert fan == UFan(0, 1, 2, 0, 1, 1)
    assert (0, 2) not in coloring
    fans.assert_valid()


def test_paper_fan_colorer_colors_complete_graphs() -> None:
    for n in range(0, 9):
        graph = Adjacency(n)
        for left in range(n):
            for right in range(left + 1, n):
                graph.add_edge(left, right)
        coloring = PaperFanColorer().color(graph, max(0, n - 1))
        assert set(coloring) == set(graph.edges())
        for vertex in range(n):
            incident = [
                coloring[tuple(sorted((vertex, neighbor)))]
                for neighbor in graph.neighbors(vertex)
            ]
            assert len(incident) == len(set(incident))


def test_paper_fan_colorer_runs_extend_for_large_fan_batches() -> None:
    graph = Adjacency(201)
    for leaf in range(1, 201):
        graph.add_edge(0, leaf)

    coloring = PaperFanColorer().color(graph, 200)

    assert set(coloring) == set(graph.edges())
    assert len({coloring[(0, leaf)] for leaf in range(1, 201)}) == 200
