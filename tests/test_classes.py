"""Class-cell data flow, ownership, failure and real paper update rollback."""

import sys
import sysconfig
from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.auxiliary import Auxiliary
from axiom.classes import Classes
from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.storage import Packed
from axiom.witness import Witness


def populated(mode="basic", backend=Packed):
    graph = backend(16)
    for vertex in range(16):
        for neighbor in range(vertex + 1, 16):
            graph.add_edge(vertex, neighbor)
    return Matcher(16, mode=mode, graph=graph)


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_invalid_capacity_leaves_owner_unchanged(capacity):
    matcher = populated()
    before = Witness().capture(matcher)
    with pytest.raises(ValueError, match="positive integer"):
        Classes(matcher, capacity)
    assert Witness().capture(matcher) == before


def test_first_write_restores_seed_sharing_list_slots_and_external_set_aliases():
    matcher = populated()
    shared = {(0, 1), (2, 3)}
    other = {(4, 5)}
    matcher.matchings = [shared, other, shared]
    matcher.seed_matching = shared
    original = matcher.matchings
    journal = Classes(matcher)
    journal.remove(shared, (0, 1))
    journal.remove(shared, (0, 1))
    journal.remove(other, (4, 5))
    journal.remove(other, (6, 7))
    matcher.matchings[0] = {(8, 9)}
    matcher.seed_matching = {(10, 11)}
    journal.remove(matcher.seed_matching, (10, 11))
    assert len(journal.entries) == 2
    journal.rollback()
    assert matcher.matchings is original and matcher.seed_matching is shared
    assert original == [shared, other, shared]
    assert original[0] is original[2] is shared
    assert shared == {(0, 1), (2, 3)} and other == {(4, 5)}
    assert matcher.classes is None


@pytest.mark.skipif(
    sys.implementation.name != "cpython" or sysconfig.get_config_var("Py_GIL_DISABLED"),
    reason="uniqueness proof requires GIL-enabled CPython",
)
@pytest.mark.parametrize("sharing", ["shared", "independent", "repeated"])
def test_uniqueness_proof_accounts_for_seed_and_repeated_class_references(sharing):
    class Trap:
        @property
        def __dict__(self):
            raise RuntimeError("global walk executed")

    matcher = populated()
    if sharing == "independent":
        matcher.seed_matching = set(matcher.seed_matching)
    elif sharing == "repeated":
        matcher.matchings.append(matcher.matchings[0])
    matcher.trap = Trap()
    journal = Classes(matcher)
    journal.rollback()
    external = matcher.seed_matching
    with pytest.raises(RuntimeError, match="global walk executed"):
        Classes(matcher)
    assert matcher.seed_matching is external and matcher.classes is None


def test_disabled_gil_build_retains_alias_walk(monkeypatch):
    class Trap:
        @property
        def __dict__(self):
            raise RuntimeError("conservative walk executed")

    matcher = populated()
    matcher.trap = Trap()
    monkeypatch.setattr(sysconfig, "get_config_var", lambda name: 1)
    with pytest.raises(RuntimeError, match="conservative walk"):
        Classes(matcher)
    assert matcher.classes is None


def test_new_partition_candidate_is_discarded_without_changing_original_sets():
    matcher = populated()
    original = matcher.matchings
    seed = matcher.seed_matching
    before = Witness().capture(matcher)
    journal = Classes(matcher)
    matcher.partition()
    assert matcher.matchings is not original
    journal.validate()
    journal.rollback()
    assert matcher.matchings is original and matcher.seed_matching is seed
    assert Witness().capture(matcher) == before


def test_class_capacity_rejects_before_mutating_the_next_cell_and_permits_retry():
    matcher = populated()
    matcher.matchings = [{(0, 1), (2, 3)}]
    matcher.seed_matching = matcher.matchings[0]
    journal = Classes(matcher, 2)
    journal.remove(matcher.seed_matching, (0, 1))
    with pytest.raises(MemoryError, match="capacity"):
        journal.remove(matcher.seed_matching, (2, 3))
    assert matcher.seed_matching == {(2, 3)}
    journal.rollback()
    assert matcher.seed_matching == {(0, 1), (2, 3)}
    journal = Classes(matcher, 3)
    journal.remove(matcher.seed_matching, (0, 1))
    journal.remove(matcher.seed_matching, (2, 3))
    journal.commit()
    assert matcher.seed_matching == set() and matcher.classes is None


def test_class_delete_journals_only_membership_cells_and_rolls_back_exactly():
    matcher = populated()
    edge = (0, 1)
    seed = {edge, (2, 3)}
    classes = [{edge}, *(set() for _ in range(100))]
    matcher.matchings = classes
    matcher.seed_matching = seed
    before = Witness().capture(matcher)
    roots = matcher.matchings
    journal = Classes(matcher, capacity=len(classes) + 4)

    journal.remove(seed, edge)
    for matching in matcher.matchings:
        journal.remove(matching, edge)

    assert len(journal.entries) == 2
    assert edge not in seed and edge not in classes[0]
    journal.rollback()

    assert matcher.matchings is roots
    assert matcher.seed_matching is seed
    assert edge in seed and edge in classes[0]
    assert all(edge not in matching for matching in classes[1:])
    assert Witness().capture(matcher) == before


@pytest.mark.parametrize("location", ["system", "matching", "nested", "list"])
def test_owned_alias_precondition_rejects_before_graph_or_accounting_edit(location):
    matcher = populated()
    if location == "system":
        matcher.system.M = matcher.seed_matching
    elif location == "matching":
        matcher.matched_edges = matcher.seed_matching
    elif location == "list":
        matcher.level_zs = matcher.matchings
    else:
        cycle = []
        cycle.append(cycle)
        cycle.append(matcher.seed_matching)
        matcher.level_zs = cycle
    with pytest.raises(ValueError, match="aliases"):
        matcher.delete(0, 1)
    assert matcher.graph.has_edge(0, 1)
    assert matcher.classes is None and matcher.views is None
    assert matcher.accountant.total_deletions == 0
    assert matcher.graph.memory()["active"] == 0


@pytest.mark.parametrize("root", ["list", "seed", "element"])
def test_nonplain_containers_reject_admission_without_binding(root):
    matcher = populated()
    if root == "list":
        matcher.matchings = tuple(matcher.matchings)
    elif root == "seed":
        matcher.seed_matching = frozenset(matcher.seed_matching)
    else:
        matcher.matchings[0] = frozenset(matcher.matchings[0])
    with pytest.raises(TypeError, match="plain"):
        Classes(matcher)
    assert matcher.classes is None


def test_constructor_limit_lifecycle_stale_thread_and_handle_guards():
    matcher = populated()
    with pytest.raises(MemoryError, match="capacity"):
        Classes(matcher, 1)
    journal = Classes(matcher)
    with pytest.raises(RuntimeError, match="already active"):
        Classes(matcher)
    with pytest.raises(RuntimeError, match="cannot be replaced"):
        matcher.classes = None
    with pytest.raises(RuntimeError, match="cannot be deleted"):
        del matcher.classes
    with ThreadPoolExecutor(max_workers=1) as executor:
        for operation in (journal.validate, journal.commit, journal.rollback):
            with pytest.raises(RuntimeError, match="another thread"):
                executor.submit(operation).result()
    object.__setattr__(matcher, "classes", None)
    with pytest.raises(RuntimeError, match="not active"):
        journal.validate()
    object.__setattr__(matcher, "classes", journal)
    journal.commit()
    for operation in (journal.validate, journal.commit, journal.rollback):
        with pytest.raises(RuntimeError, match="not active"):
            operation()


@pytest.mark.parametrize("root", ["list", "seed", "element"])
def test_invalid_candidate_roots_reject_and_restore_originals(root):
    matcher = populated()
    before = Witness().capture(matcher)
    journal = Classes(matcher)
    if root == "list":
        matcher.matchings = ()
    elif root == "seed":
        matcher.seed_matching = ()
    else:
        matcher.matchings[0] = ()
    with pytest.raises(TypeError, match="plain"):
        journal.validate()
    journal.rollback()
    assert Witness().capture(matcher) == before


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
@pytest.mark.parametrize("stage", ["repair", "subphase", "rebuild", "publish"])
def test_real_deletion_failure_restores_class_identity_full_state_then_retries(
    mode, backend, stage, monkeypatch
):
    import axiom.core as core

    matcher = populated(mode, backend)
    matcher.phase_length = 1 if stage == "rebuild" else 1000
    matcher.subphase_length = 1 if stage == "subphase" else 1000
    original = matcher.matchings
    seed = matcher.seed_matching
    held = tuple(original)
    edge = min(seed)
    before = Witness().capture(matcher)
    import copy

    def forbid_copy(*args, **kwargs):
        raise AssertionError("Matcher transaction invoked deepcopy")

    monkeypatch.setattr(copy, "deepcopy", forbid_copy)
    advance = Matcher._Matcher__advance_update_counter

    def fail(owner):
        advance(owner)
        raise RuntimeError("after class mutations")

    def reject(*args):
        raise RuntimeError("publication rejected")

    with monkeypatch.context() as patch:
        if stage == "publish":
            patch.setattr(core, "publish", reject)
        else:
            patch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
        with pytest.raises(RuntimeError, match="class mutations|publication rejected"):
            matcher.delete(*edge)
    assert matcher.matchings is original and matcher.seed_matching is seed
    assert all(left is right for left, right in zip(held, original, strict=True))
    assert Witness().capture(matcher) == before
    matcher.delete(*edge)
    assert matcher.maximal() and matcher.classes is None


def test_class_transactions_run_without_recursive_deepcopy(monkeypatch):
    matcher = populated()
    import copy

    def reject(*args, **kwargs):
        raise AssertionError("Matcher update invoked deepcopy")

    monkeypatch.setattr(copy, "deepcopy", reject)
    matcher.delete(*min(matcher.seed_matching))
    assert matcher.maximal()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("stage", ["capacity", "admission"])
def test_admission_and_snapshot_failures_restore_full_state_then_retry(
    mode, stage, monkeypatch
):
    matcher = populated(mode)
    before = Witness().capture(matcher)
    remove = Classes.remove
    edge = min(matcher.seed_matching)

    def bounded(journal, matching, edge):
        journal.capacity = len(journal.sets)
        remove(journal, matching, edge)

    def reject(*args):
        raise MemoryError("journal admission failed")

    with monkeypatch.context() as patch:
        if stage == "capacity":
            patch.setattr(Classes, "remove", bounded)
        else:
            patch.setattr(Auxiliary, "__init__", reject)
        with pytest.raises(MemoryError, match="capacity|admission"):
            matcher.delete(*edge)
    assert Witness().capture(matcher) == before
    assert matcher.classes is None and matcher.views is None
    assert matcher.graph.memory()["active"] == 0
    matcher.delete(*edge)
    assert matcher.maximal()


@pytest.mark.parametrize("stage", ["rollback", "commit"])
def test_uncertain_class_cleanup_fail_stops_queries_and_updates(stage, monkeypatch):
    matcher = populated()

    def reject(*args):
        raise RuntimeError("class cleanup failed")

    monkeypatch.setattr(Classes, stage, reject)
    if stage == "rollback":
        monkeypatch.setattr(Matcher, "_Matcher__advance_update_counter", reject)
    with pytest.raises(RuntimeError, match="discard matcher"):
        matcher.delete(*min(matcher.seed_matching))
    assert matcher.failed
    for operation in (matcher.matching, lambda: matcher.insert(0, 4)):
        with pytest.raises(RuntimeError, match="has failed"):
            operation()
