"""Bounded allocation regressions for paper-system reconstruction."""

import tracemalloc
from array import array

from axiom.graph import Adjacency
from axiom.storage import Packed
from axiom.system import System, build


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


def test_packed_index_builds_final_lambda_arrays_without_temporary_rows(monkeypatch):
    """Recovery indexing must not stage Python lists before compact rows."""
    graph = Packed(64)
    graph.ring(2)

    def reject_staged_row(self, values):
        raise AssertionError("Packed indexing staged a temporary Python row")

    monkeypatch.setattr(System, "cache_row", reject_staged_row)
    system = build(graph, 5)

    assert len(system.lambda_lists) == 64
    assert all(
        type(row) is array and row.typecode == "I"
        for row in system.lambda_lists.values()
    )
    assert list(system.lambda_lists[0]) == [1, 2, 62, 63]
    assert system.check()
