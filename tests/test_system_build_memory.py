"""Bounded allocation regressions for paper-system reconstruction."""

import tracemalloc

from axiom.graph import Adjacency
from axiom.storage import Packed
from axiom.system import build


def test_build_streams_u_u_removal_without_graph_sized_temporary_set():
    """A dense U partition must not duplicate M while building its indexes."""
    vertices = 40_000
    graph = Adjacency(vertices)
    for vertex in range(vertices):
        graph.add_edge(vertex, (vertex + 1) % vertices)

    tracemalloc.start()
    try:
        system = build(graph, vertices)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 14 * 1024 * 1024
    assert len(system.U) == vertices
    assert system.M == set()
    assert system.lambda_lists[0] == [1, vertices - 1]
    assert system.check()


def test_degree_below_paper_cap_builds_exact_empty_matching_state_directly():
    graph = Packed(64)
    graph.ring(2)

    system = build(graph, 5)

    assert system.A == set()
    assert system.B == set()
    assert system.U == set(range(64))
    assert system.M == set()
    assert len(system.lambda_lists) == 64
    assert system.check()
