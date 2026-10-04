"""Tests for the journal-backed phase-start graph projection."""

from __future__ import annotations

import pytest

from axiom.graph import Adjacency, PhaseBaseGraph, empty
from axiom.storage import Packed


def test_phase_base_graph_projects_endpoint_indexed_deltas() -> None:
    live = Adjacency(6)
    for edge in ((0, 1), (0, 4), (2, 3), (4, 5)):
        live.add_edge(*edge)
    inserted = {(0, 4)}
    deleted = {(1, 2)}
    inserted_at = {0: {(0, 4)}, 4: {(0, 4)}}
    deleted_at = {1: {(1, 2)}, 2: {(1, 2)}}
    phase = PhaseBaseGraph(live, inserted, deleted, inserted_at, deleted_at)

    assert list(phase.edges()) == [(0, 1), (1, 2), (2, 3), (4, 5)]
    assert list(phase.neighbors(0)) == [1]
    assert list(phase.neighbors(1)) == [0, 2]
    assert phase.degree(2) == 2
    assert phase.num_edges() == 4
    assert empty(phase).num_edges() == 0
    with pytest.raises(RuntimeError, match="read-only"):
        phase.add_edge(0, 2)

    # Restoring the journaled delta roots restores the exact phase topology.
    inserted.clear()
    inserted_at.clear()
    deleted.clear()
    deleted_at.clear()
    assert list(phase.edges()) == list(live.edges())


def test_phase_base_graph_reserves_bounded_packed_growth_budget() -> None:
    live = Packed(16, budget=96 << 20)
    live.ring()
    phase = PhaseBaseGraph(live, set(), set(), {}, {})

    working = empty(phase)

    assert isinstance(working, Packed)
    assert working.memory()["budget"] <= live.memory()["budget"]
    assert working.memory()["budget"] >= 64 << 20
