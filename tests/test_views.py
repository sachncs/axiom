"""Matching-container identity, bounded cells, candidates and exact undo."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.storage import Packed
from axiom.views import Views
from axiom.witness import Witness


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_bad_capacity_cannot_open_or_mutate_matching(capacity):
    matcher = Matcher(8)
    before = Witness().capture(matcher)
    with pytest.raises(ValueError, match="positive integer"):
        Views(matcher, capacity)
    assert Witness().capture(matcher) == before


def test_original_cells_are_recorded_once_and_restore_container_identity():
    graph = Packed(8)
    graph.add_edge(0, 1)
    matcher = Matcher(8, graph=graph)
    edges, vertices, partners = (
        matcher.matched_edges,
        matcher.matched_vertices,
        matcher.partner_map,
    )
    journal = Views(matcher, 3)
    matcher.drop_match(0, 1)
    matcher.add_match(0, 1)
    matcher.drop_match(0, 1)
    assert journal.edge == {(0, 1): True}
    assert journal.vertex == {0: (True, True, 1), 1: (True, True, 0)}
    journal.rollback()
    assert matcher.matched_edges is edges and matcher.matched_vertices is vertices
    assert matcher.partner_map is partners
    assert edges == {(0, 1)} and vertices == {0, 1} and partners == {0: 1, 1: 0}
    assert matcher.views is None


def test_nested_thread_replaced_deleted_and_closed_handles_reject():
    matcher = Matcher(8)
    journal = Views(matcher)
    with pytest.raises(RuntimeError, match="already active"):
        Views(matcher)
    with pytest.raises(RuntimeError, match="cannot be replaced"):
        matcher.views = None
    with pytest.raises(RuntimeError, match="cannot be deleted"):
        del matcher.views
    with ThreadPoolExecutor(max_workers=1) as executor:
        for operation in (
            lambda: journal.record(0, 1),
            journal.commit,
            journal.rollback,
        ):
            with pytest.raises(RuntimeError, match="thread|here"):
                executor.submit(operation).result()
    journal.commit()
    assert matcher.views is None
    with pytest.raises(RuntimeError, match="closed"):
        journal.record(0, 1)
    with pytest.raises(RuntimeError, match="here"):
        journal.rollback()
    matcher.extra = 1
    del matcher.extra


@pytest.mark.parametrize("location", ["seed", "system", "nested"])
def test_alias_precondition_fails_before_graph_or_accounting_changes(location):
    matcher = Matcher(8, graph=Packed(8))
    if location == "seed":
        matcher.seed_matching = matcher.matched_edges
    elif location == "system":
        matcher.system.M = matcher.matched_edges
    else:
        matcher.matchings = [matcher.matched_edges]
    before = Witness().capture(matcher)
    with pytest.raises(ValueError, match="aliases"):
        matcher.insert(0, 1)
    assert Witness().capture(matcher) == before
    assert matcher.views is None and matcher.accountant.journal is None
    assert matcher.graph.memory()["active"] == 0


def test_alias_preflight_handles_owned_cycles_without_losing_nested_aliases():
    matcher = Matcher(8)
    cycle = []
    cycle.append(cycle)
    matcher.matchings = cycle
    journal = Views(matcher)
    journal.rollback()
    cycle.append(matcher.partner_map)
    with pytest.raises(ValueError, match="aliases"):
        Views(matcher)
    assert matcher.views is None


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
@pytest.mark.parametrize("stage", ["repair", "refresh", "publish"])
def test_failure_restores_full_state_and_every_external_matching_alias(
    mode, backend, stage, monkeypatch
):
    import axiom.core as core

    graph = backend(16)
    for vertex in range(16):
        graph.add_edge(vertex, (vertex + 1) % 16)
    matcher = Matcher(16, graph=graph, mode=mode)
    matcher.phase_length = 1 if stage == "refresh" else 1000
    edges, vertices, partners = (
        matcher.matched_edges,
        matcher.matched_vertices,
        matcher.partner_map,
    )
    before = Witness().capture(matcher)
    advance = Matcher._Matcher__advance_update_counter

    def failure(owner):
        advance(owner)
        raise RuntimeError("after forward mutation")

    def reject(*args):
        raise RuntimeError("publication rejected")

    with monkeypatch.context() as patch:
        if stage == "publish":
            patch.setattr(core, "publish", reject)
        else:
            patch.setattr(Matcher, "_Matcher__advance_update_counter", failure)
        with pytest.raises(RuntimeError, match="forward mutation|publication rejected"):
            matcher.delete(0, 1)
    assert matcher.matched_edges is edges and matcher.matched_vertices is vertices
    assert matcher.partner_map is partners
    assert Witness().capture(matcher) == before
    matcher.delete(0, 1)
    assert matcher.maximal() and matcher.views is None


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_matching_views_are_reused_not_deepcopied(mode, monkeypatch):
    import axiom.core as core

    matcher = Matcher(16, mode=mode, graph=Packed(16))
    original = core.copy.deepcopy
    held = (matcher.matched_edges, matcher.matched_vertices, matcher.partner_map)
    observed = set()

    def audited(value, memo):
        if any(value is container for container in held):
            assert memo[id(value)] is value
            observed.add(id(value))
        return original(value, memo)

    monkeypatch.setattr(core.copy, "deepcopy", audited)
    matcher.insert(0, 1)
    assert observed == {id(container) for container in held}
    assert all(
        current is original
        for current, original in zip(
            (matcher.matched_edges, matcher.matched_vertices, matcher.partner_map),
            held,
            strict=True,
        )
    )


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("capacity", [1, 2])
def test_capacity_rejection_restores_graph_and_every_view_then_retries(
    mode, capacity, monkeypatch
):
    matcher = Matcher(16, mode=mode, graph=Packed(16))
    before = Witness().capture(matcher)
    reserve = Views.reserve

    def bounded(journal):
        journal.capacity = capacity
        reserve(journal)

    with monkeypatch.context() as patch:
        patch.setattr(Views, "reserve", bounded)
        with pytest.raises(MemoryError, match="capacity"):
            matcher.insert(0, 1)
    assert Witness().capture(matcher) == before
    matcher.insert(0, 1)
    assert matcher.partner(0) == 1


def test_partial_candidate_assignment_is_undoable_without_a_forward_certificate():
    matcher = Matcher(8)
    edges = matcher.matched_edges
    journal = Views(matcher)
    matcher.matched_edges = set()
    with pytest.raises(RuntimeError, match="partially replaced"):
        journal.validate()
    journal.rollback()
    assert matcher.matched_edges is edges


@pytest.mark.parametrize("corruption", ["vertex", "partner", "edge", "candidate"])
def test_coupled_certificate_rejects_corruption_before_commit(corruption):
    graph = Packed(8)
    graph.add_edge(0, 1)
    matcher = Matcher(8, graph=graph)
    journal = Views(matcher)
    journal.record(0, 1)
    if corruption == "vertex":
        matcher.matched_vertices.discard(0)
    elif corruption == "partner":
        matcher.partner_map[0] = 2
    elif corruption == "edge":
        matcher.matched_edges.discard((0, 1))
    else:
        matcher.matched_edges = {(0, 1)}
        matcher.matched_vertices = set()
        matcher.partner_map = {}
    with pytest.raises(RuntimeError, match="disagree|inconsistent"):
        journal.validate()
    journal.rollback()
    assert matcher.matching() == {(0, 1)} and matcher.partner(0) == 1


def test_matching_cleanup_failure_after_publication_is_failstop(monkeypatch):
    matcher = Matcher(16, graph=Packed(16))

    def failure(*args):
        raise MemoryError("matching cleanup failed")

    monkeypatch.setattr(Views, "commit", failure)
    with pytest.raises(RuntimeError, match="publication cleanup"):
        matcher.insert(0, 1)
    assert matcher.failed and matcher.graph.has_edge(0, 1)
    with pytest.raises(RuntimeError, match="discard matcher"):
        matcher.partner(0)


@pytest.mark.parametrize("field", ["matched_edges", "matched_vertices", "partner_map"])
def test_nonplain_matching_containers_reject_before_binding(field):
    matcher = Matcher(8)
    setattr(matcher, field, [])
    with pytest.raises(TypeError, match="plain sets"):
        Views(matcher)
    assert matcher.views is None


def test_shared_edge_and_vertex_container_rejects_before_binding():
    matcher = Matcher(8)
    matcher.matched_vertices = matcher.matched_edges
    with pytest.raises(ValueError, match="share a container"):
        Views(matcher)
    assert matcher.views is None


def test_stale_matching_handle_cannot_edit_or_close_a_different_binding():
    matcher = Matcher(8)
    journal = Views(matcher)
    object.__setattr__(matcher, "views", None)
    with pytest.raises(RuntimeError, match="stale"):
        journal.record(0, 1)
    object.__setattr__(matcher, "views", journal)
    journal.rollback()


def test_candidate_extra_vertices_are_not_an_exact_matching_view():
    graph = Packed(8)
    graph.add_edge(0, 1)
    matcher = Matcher(8, graph=graph)
    journal = Views(matcher)
    matcher.matched_edges = {(0, 1)}
    matcher.matched_vertices = {0, 1, 7}
    matcher.partner_map = {0: 1, 1: 0}
    with pytest.raises(RuntimeError, match="candidate matching views"):
        journal.validate()
    journal.rollback()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_old_edits_then_candidate_edits_restore_only_original_views(mode, monkeypatch):
    graph = Packed(16)
    graph.ring()
    matcher = Matcher(16, mode=mode, graph=graph)
    matcher.phase_length = 1
    before = Witness().capture(matcher)
    original = matcher.matched_edges
    advance = Matcher._Matcher__advance_update_counter

    def fail(owner):
        advance(owner)
        assert owner.matched_edges is not original
        candidate = min(owner.matched_edges)
        retained = len(owner.views.edge), len(owner.views.vertex)
        owner.drop_match(*candidate)
        owner.add_match(*candidate)
        assert (len(owner.views.edge), len(owner.views.vertex)) == retained
        raise RuntimeError("failure after candidate edits")

    with monkeypatch.context() as patch:
        patch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
        with pytest.raises(RuntimeError, match="after candidate edits"):
            matcher.delete(0, 1)
    assert Witness().capture(matcher) == before
    assert matcher.matched_edges is original


def test_matching_rollback_failure_never_exposes_a_certified_query(monkeypatch):
    graph = Packed(16)
    graph.ring()
    matcher = Matcher(16, graph=graph)

    def fail(*args):
        raise MemoryError("matching undo unavailable")

    monkeypatch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
    monkeypatch.setattr(Views, "rollback", fail)
    with pytest.raises(RuntimeError, match="rollback failed"):
        matcher.delete(0, 1)
    assert matcher.failed and graph.has_edge(0, 1) and graph.memory()["active"] == 0
    with pytest.raises(RuntimeError, match="discard matcher"):
        matcher.matching()


@pytest.mark.parametrize("corruption", ["partner", "vertex", "key", "float"])
def test_boolean_and_float_candidate_labels_cannot_pass_integer_equality(corruption):
    graph = Packed(8)
    graph.add_edge(0, 1)
    matcher = Matcher(8, graph=graph)
    journal = Views(matcher)
    matcher.matched_edges = {(0, 1)}
    matcher.matched_vertices = {0, 1}
    matcher.partner_map = {0: 1, 1: 0}
    if corruption == "partner":
        matcher.partner_map[0] = True
    elif corruption == "vertex":
        matcher.matched_vertices = {0, True}
    elif corruption == "key":
        matcher.partner_map = {False: 1, True: 0}
    else:
        matcher.matched_vertices = {0.0, 1.0}
    with pytest.raises(RuntimeError, match="value types"):
        journal.validate()
    journal.rollback()
    assert matcher.partner(0) == 1 and type(matcher.partner(0)) is int


def test_changed_partner_boolean_rejects_before_using_it_as_a_vertex():
    graph = Packed(8)
    graph.add_edge(0, 1)
    matcher = Matcher(8, graph=graph)
    journal = Views(matcher)
    journal.record(0, 1)
    matcher.partner_map[0] = True
    with pytest.raises(RuntimeError, match="partner value type"):
        journal.validate()
    journal.rollback()
    assert type(matcher.partner(0)) is int
