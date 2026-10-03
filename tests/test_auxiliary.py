"""Bounded cell-level rollback for paper Matcher auxiliary indexes."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.auxiliary import Auxiliary
from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.storage import Packed
from axiom.witness import Witness


def populated(mode="multilevel", backend=Packed):
    graph = backend(16)
    for vertex in range(16):
        graph.add_edge(vertex, (vertex + 1) % 16)
    return Matcher(16, graph=graph, mode=mode)


def test_old_map_and_nested_set_cells_restore_with_original_roots():
    matcher = populated(mode="basic")
    bucket = {2, 3}
    matcher.H[0] = {1, 4}
    matcher.H_reverse[1] = bucket
    matcher.inserted_incident_edges[0] = {(0, 1)}
    roots = {
        name: getattr(matcher, name) for name in (*Auxiliary.maps, *Auxiliary.sets)
    }
    before = Witness().capture(matcher)
    journal = Auxiliary(matcher)

    journal.member(matcher.H_tilde, (0, 1), True)
    journal.member(matcher.H_tilde, (0, 1), False)
    journal.assign(matcher.H, 0, {8})
    journal.remove(matcher.H_reverse, 1)
    journal.add(matcher.H_reverse, 1, 4)
    journal.discard(matcher.H_reverse, 1, 4, empty=True)
    journal.add(matcher.inserted_incident_edges, 0, (0, 2))
    journal.discard(matcher.inserted_incident_edges, 0, (0, 1), empty=True)
    journal.assign(matcher.inserted_incident_counts, 7, 4)
    journal.member(matcher.bad_vertices, 5, True)
    journal.clear(matcher.deleted_edges)
    journal.clear(matcher.S_hat)
    journal.rollback()

    assert all(getattr(matcher, name) is value for name, value in roots.items())
    assert matcher.H_reverse[1] is bucket
    assert Witness().capture(matcher) == before


def test_missing_map_keys_and_repeated_bucket_edits_rollback():
    matcher = populated(mode="basic")
    before = Witness().capture(matcher)
    journal = Auxiliary(matcher)
    edge = (2, 9)

    journal.add(matcher.inserted_incident_edges, 2, edge)
    values = matcher.inserted_incident_edges[2]
    journal.add(matcher.inserted_incident_edges, 2, (2, 10))
    journal.discard(matcher.inserted_incident_edges, 2, edge)
    journal.discard(matcher.inserted_incident_edges, 2, (2, 10), empty=True)
    assert matcher.inserted_incident_edges == {}
    assert values == set()
    journal.rollback()

    assert matcher.inserted_incident_edges == {}
    assert Witness().capture(matcher) == before


def test_clear_capacity_failure_precedes_map_mutation():
    matcher = populated(mode="basic")
    matcher.H.update({0: {1}, 2: {3}})
    before = Witness().capture(matcher)
    journal = Auxiliary(matcher, capacity=len(Auxiliary.maps) + len(Auxiliary.sets))

    with pytest.raises(MemoryError, match="capacity exceeded"):
        journal.clear(matcher.H)

    assert matcher.H == {0: {1}, 2: {3}}
    journal.rollback()
    assert Witness().capture(matcher) == before


@pytest.mark.parametrize("stage", ["repair", "rebuild"])
def test_failed_real_update_restores_all_auxiliary_state_and_retries(
    stage, monkeypatch
):
    matcher = populated()
    if stage == "rebuild":
        matcher.phase_length = 1
    roots = {
        name: getattr(matcher, name) for name in (*Auxiliary.maps, *Auxiliary.sets)
    }
    before = Witness().capture(matcher)
    advance = Matcher._Matcher__advance_update_counter

    def fail(owner):
        advance(owner)
        raise RuntimeError("injected after auxiliary mutation")

    with monkeypatch.context() as patch:
        patch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
        with pytest.raises(RuntimeError, match="after auxiliary mutation"):
            if stage == "repair":
                matcher.insert(0, 4)
            else:
                matcher.delete(0, 1)

    assert all(getattr(matcher, name) is value for name, value in roots.items())
    assert matcher.auxiliary is None
    assert Witness().capture(matcher) == before
    assert matcher.maximal()
    if stage == "repair":
        matcher.insert(0, 4)
    else:
        matcher.delete(0, 1)
    assert matcher.maximal()


def test_auxiliary_journal_rejects_cross_thread_use():
    matcher = populated(mode="basic")
    journal = Auxiliary(matcher)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(journal.member, matcher.H_tilde, (0, 1), True)
        with pytest.raises(RuntimeError, match="another thread"):
            future.result()
    assert not matcher.H_tilde
    journal.rollback()


@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_parent_rebuild_undoes_auxiliary_clear_on_both_graph_backends(backend):
    matcher = populated(backend=backend)
    matcher.phase_length = 1
    matcher.delete(0, 1)
    assert matcher.maximal() and matcher.multi is not None and matcher.multi.check()


def test_affected_edge_certificate_rejects_missing_incident_delta_and_rolls_back(
    monkeypatch,
):
    matcher = Matcher(16, mode="multilevel", graph=Packed(16))
    before = Witness().capture(matcher)
    add = Auxiliary.add

    def omit_incident(journal, container, key, item):
        if container is matcher.inserted_incident_edges:
            return
        add(journal, container, key, item)

    monkeypatch.setattr(Auxiliary, "add", omit_incident)
    with pytest.raises(RuntimeError, match="auxiliary index delta certificate"):
        matcher.insert(0, 1)

    assert Witness().capture(matcher) == before
    assert matcher.auxiliary is None
    assert matcher._Matcher__check_auxiliary_indexes()
