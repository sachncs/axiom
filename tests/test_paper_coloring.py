from __future__ import annotations

import pytest

from axiom.graph import Adjacency
from axiom.paper_coloring import (
    PaperFanColorer,
    PartialColoring,
    SeparableFans,
    UFan,
    activate_fan,
    amplify,
    collect_direct_fans,
    color_blocks,
    extend_recursive,
    fan_is_social,
    relevant_paths,
    shift_edge_to_fan,
    small_extend,
)


def test_separable_fans_enforce_edge_and_vertex_color_disjointness() -> None:
    fans = SeparableFans()
    first = UFan(0, 1, 2, 0, 1, 1)
    fans.add(first)
    fans.assert_valid()
    assert fans.find(0, 0) == first
    assert fans.find(1, 1) == first

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


def test_small_extend_activates_deterministic_common_type() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(1, 3)
    coloring = PartialColoring(graph, 2)
    coloring.assign((1, 3), 0)
    fans = SeparableFans()
    fan = UFan(0, 1, 2, 0, 1, 1)
    fans.add(fan)

    assert small_extend(coloring, fans) == 1
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


def test_amplify_keeps_small_collection_explicitly_bounded() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = PartialColoring(graph, 100)
    fans = SeparableFans()
    fans.add(UFan(0, 1, 2, 0, 10, 10))

    groups, social = amplify(coloring, fans, 10)

    assert len(groups) == 10
    assert len(social) == 0


def test_amplify_socializes_a_full_deterministic_batch() -> None:
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

    groups, social = amplify(coloring, fans, 10)

    assert len(groups) == 10
    assert len(social) == fan_count
    assert all(fan_is_social(fan, color_blocks(100, 10)[0]) for fan in social)
    coloring.validate()


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
