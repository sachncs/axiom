from __future__ import annotations

import pytest

from axiom.graph import Adjacency
from axiom.paper_coloring import (
    PartialColoring,
    SeparableFans,
    UFan,
    activate_fan,
    collect_direct_fans,
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
