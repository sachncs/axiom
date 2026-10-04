"""Incremental multilevel I3 boundary-index behavior and rollback."""

from __future__ import annotations

import pytest

from axiom.core import Matcher
from axiom.hierarchy import Hierarchy
from axiom.storage import Packed
from axiom.witness import Witness


def test_multilevel_local_updates_do_not_scan_the_full_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matcher = Matcher(128, mode="multilevel")
    matcher.multi.A1 = {0}
    matcher.multi.R1 = {1}
    assert matcher.i3_crossings == set()

    def reject_full_scan(*args: object, **kwargs: object) -> bool:
        raise AssertionError("ordinary update invoked the full I3 matching scan")

    monkeypatch.setattr(Hierarchy, "check_i3", reject_full_scan)
    matcher.insert(0, 1)
    assert matcher.i3_crossings == {(0, 1)}
    matcher.delete(0, 1)

    assert matcher.i3_crossings == matcher.multi.crossing_edges(matcher.matched_edges)
    assert matcher.maximal()


def test_crossing_index_update_rolls_back_with_matching_and_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Packed(128)
    graph.add_edge(0, 1)
    matcher = Matcher(128, mode="multilevel", graph=graph)
    edge = (0, 1)
    matcher.multi.A1 = {0}
    matcher.multi.R1 = {1}
    matcher.i3_crossings = {edge}
    original = Matcher.update_i3_index

    def fail_after_index_edit(
        owner: Matcher, changed: tuple[int, int], added: bool
    ) -> None:
        original(owner, changed, added)
        if changed == edge and not added:
            raise RuntimeError("injected after I3 index edit")

    monkeypatch.setattr(Matcher, "update_i3_index", fail_after_index_edit)
    with pytest.raises(RuntimeError, match="after I3 index edit"):
        matcher.delete(*edge)

    assert matcher.graph.has_edge(*edge)
    assert edge in matcher.matched_edges
    assert matcher.i3_crossings == {edge}
    assert matcher.multi.A1 == {0} and matcher.multi.R1 == {1}
    assert matcher.maximal()


def test_i3_count_matches_full_certificate_at_threshold_edges() -> None:
    graph = Packed(8)
    hierarchy = Hierarchy(graph=graph, k=1, A1={0, 1, 2}, R1={5, 6, 7})
    matching = {(0, 5), (1, 6), (2, 7), (3, 4)}
    crossings = hierarchy.crossing_edges(matching)

    assert len(crossings) == 3
    assert hierarchy.check_i3_count(2, r=1, z=32)
    assert hierarchy.check_i3(set(sorted(crossings)[:2]), r=1, z=32)
    assert not hierarchy.check_i3_count(3, r=1, z=32)
    assert not hierarchy.check_i3(crossings, r=1, z=32)
    assert hierarchy.check_i3_count(10**9, r=1, z=0)


def test_incremental_crossing_index_handles_both_orientations_and_non_crossings() -> (
    None
):
    graph = Packed(8)
    graph.add_edge(0, 1)
    graph.add_edge(2, 3)
    matcher = Matcher(8, mode="multilevel", graph=graph)
    assert matcher.multi is not None
    matcher.multi.A1 = {0}
    matcher.multi.R1 = {1}
    matcher.i3_crossings.clear()

    matcher.update_i3_index((0, 1), True)
    matcher.update_i3_index((1, 0), True)
    matcher.update_i3_index((2, 3), True)
    assert matcher.i3_crossings == {(0, 1)}

    matcher.update_i3_index((1, 0), False)
    assert matcher.i3_crossings == set()


def test_indexed_i3_repair_rejects_a_stale_non_crossing_entry() -> None:
    graph = Packed(8)
    hierarchy = Hierarchy(graph=graph, k=1, A1={0}, R1={7})
    matching = {(0, 7), (1, 2)}

    with pytest.raises(RuntimeError, match="crossing index is stale"):
        hierarchy.maintain_i3(
            matching,
            r=1,
            z=128,
            partner_of=lambda _vertex: None,
            rematch=lambda _vertex: None,
            crossing_edges={(1, 2)},
        )


def test_successful_multilevel_rebuild_rebases_the_crossing_index() -> None:
    graph = Packed(16)
    for vertex in range(15):
        graph.add_edge(vertex, vertex + 1)
    matcher = Matcher(16, mode="multilevel", graph=graph)
    assert matcher.multi is not None

    edge = next(iter(matcher.matched_edges))
    matcher.multi.A1 = {edge[0]}
    matcher.multi.R1 = {edge[1]}
    matcher.i3_crossings = matcher.multi.crossing_edges(matcher.matched_edges)
    assert matcher.i3_crossings == {edge}
    matcher.i3_crossings.clear()

    matcher.policy.rebuild(matcher)

    assert matcher.multi is not None
    assert matcher.i3_crossings == matcher.multi.crossing_edges(matcher.matched_edges)


def test_failed_crossing_index_insertion_restores_exact_witness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matcher = Matcher(128, mode="multilevel")
    assert matcher.multi is not None
    matcher.multi.A1 = {0}
    matcher.multi.R1 = {1}
    before = Witness().capture(matcher)
    original = Matcher.update_i3_index

    def fail_after_crossing_add(
        owner: Matcher, edge: tuple[int, int], added: bool
    ) -> None:
        original(owner, edge, added)
        if edge == (0, 1) and added:
            raise RuntimeError("injected after crossing-index insertion")

    monkeypatch.setattr(Matcher, "update_i3_index", fail_after_crossing_add)
    with pytest.raises(RuntimeError, match="after crossing-index insertion"):
        matcher.insert(0, 1)

    assert Witness().capture(matcher) == before
    assert not matcher.graph.has_edge(0, 1)
