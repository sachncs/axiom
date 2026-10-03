"""Incremental multilevel I3 boundary-index behavior and rollback."""

from __future__ import annotations

import pytest

from axiom.core import Matcher
from axiom.hierarchy import Hierarchy
from axiom.storage import Packed


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
