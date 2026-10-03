"""System identity, aliased rows, refinement cuts and exact transactional undo."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.storage import Packed
from axiom.system import System
from axiom.systems import Systems
from axiom.witness import Witness


def populated(mode="basic", backend=Packed, dense=False):
    graph = backend(16)
    if dense:
        for left in range(16):
            for right in range(left + 1, 16):
                graph.add_edge(left, right)
    else:
        for vertex in range(16):
            graph.add_edge(vertex, (vertex + 1) % 16)
    return Matcher(16, mode=mode, graph=graph)


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_bad_capacity_leaves_owner_and_system_idle(capacity):
    matcher = populated()
    before = Witness().capture(matcher)
    with pytest.raises(ValueError, match="positive integer"):
        Systems(matcher, capacity)
    assert matcher.systems is None and matcher.system.journal is None
    assert Witness().capture(matcher) == before


@pytest.mark.parametrize("configuration", [True, -1, "1", None])
@pytest.mark.parametrize("stage", ["admission", "candidate"])
def test_invalid_system_configuration_rejects_before_publication(configuration, stage):
    matcher = populated()
    before = Witness().capture(matcher)
    journal = Systems(matcher) if stage == "candidate" else None
    if configuration is None:
        matcher.system.graph = Packed(8)
    else:
        matcher.system.z = configuration
    with pytest.raises(ValueError, match="System.*configuration"):
        if journal is None:
            Systems(matcher)
        else:
            journal.validate()
    if journal is not None:
        journal.rollback()
        assert Witness().capture(matcher) == before
    assert matcher.systems is None and matcher.system.journal is None


def test_shared_rows_have_one_first_write_record_and_restore_all_external_aliases():
    matcher = populated()
    system = matcher.system
    original = system.lambda_lists
    values = original[0]
    before = Witness().capture(matcher)
    journal = Systems(matcher)
    journal.edit(original, 0, 4, True)
    alias = {0: values}
    journal.edit(alias, 0, 5, True)
    journal.edit(original, 0, 4, False)
    assert len(journal.rows) == 1 and values == [1, 5, 15]
    system.index()
    assert system.lambda_lists is not original
    journal.rollback()
    assert matcher.system is system and system.lambda_lists is original
    assert original[0] is alias[0] is values
    assert Witness().capture(matcher) == before


def test_missing_cache_keys_and_repeated_edits_restore_original_key_absence():
    matcher = populated()
    system = matcher.system
    system.lambda_lists.pop(0)
    original = system.lambda_lists
    before = Witness().capture(matcher)
    journal = Systems(matcher)
    journal.edit(original, 0, 4, True)
    journal.edit(original, 0, 5, True)
    journal.rollback()
    assert 0 not in original and system.lambda_lists is original
    assert Witness().capture(matcher) == before


def test_root_replacements_and_matching_cuts_restore_original_system_state():
    matcher = populated(dense=True)
    system = matcher.system
    roots = dict(vars(system))
    before = Witness().capture(matcher)
    journal = Systems(matcher)
    allowed = set(sorted(system.M)[2:])
    system.restrict(allowed)
    system.restrict(allowed)
    assert len(journal.edges) == 2
    system.graph = Packed(16)
    system.z = 0
    system.A, system.B, system.U, system.M = set(), set(), set(range(16)), set()
    system.index()
    journal.rollback()
    assert all(vars(system)[name] is value for name, value in roots.items())
    assert Witness().capture(matcher) == before


def test_row_capacity_rejects_before_edit_and_restores_graph_on_retry():
    matcher = populated()
    system = matcher.system
    before = Witness().capture(matcher)
    journal = Systems(matcher, 10)
    with pytest.raises(MemoryError, match="capacity"):
        journal.edit(system.lambda_lists, 0, 4, True)
    assert system.lambda_lists[0] == [1, 15]
    journal.rollback()
    assert Witness().capture(matcher) == before
    journal = Systems(matcher)
    journal.edit(system.lambda_lists, 0, 4, True)
    journal.rollback()
    assert Witness().capture(matcher) == before


def test_partial_matching_cut_capacity_failure_restores_each_removed_edge():
    matcher = populated(dense=True)
    before = Witness().capture(matcher)
    journal = Systems(matcher, 10)
    with pytest.raises(MemoryError, match="capacity"):
        matcher.system.restrict(set())
    assert len(journal.edges) == 1
    journal.rollback()
    assert Witness().capture(matcher) == before


@pytest.mark.parametrize("shape", ["fields", "partition", "map", "row", "nested"])
def test_unsupported_or_bound_system_rejects_before_any_handle_is_bound(shape):
    matcher = populated()
    system = matcher.system
    if shape == "fields":
        system.extra = 1
    elif shape == "partition":
        system.A = frozenset(system.A)
    elif shape == "map":
        system.L_lists = []
    elif shape == "row":
        system.lambda_lists[0] = ()
    else:
        object.__setattr__(system, "journal", object())
    with pytest.raises(TypeError, match="System|system"):
        Systems(matcher)
    assert matcher.systems is None
    if shape != "nested":
        assert system.journal is None


@pytest.mark.parametrize("shape", ["configuration", "record", "valid", "foreign"])
def test_candidate_system_configuration_and_record_are_checked_before_publish(shape):
    matcher = populated()
    original = matcher.system
    before = Witness().capture(matcher)
    journal = Systems(matcher)
    candidate = System(
        original.graph,
        original.z,
        set(original.A),
        set(original.B),
        set(original.U),
        set(original.M),
    )
    matcher.system = candidate
    if shape == "configuration":
        candidate.z = True
        message = "configuration"
    elif shape == "record":
        candidate.extra = None
        message = "fields"
    elif shape == "foreign":
        object.__setattr__(candidate, "journal", journal)
        message = "already journaled"
    if shape == "valid":
        journal.validate()
        matcher.system = original
        journal.rollback()
        assert Witness().capture(matcher) == before
        return
    with pytest.raises((TypeError, ValueError, RuntimeError), match=message):
        journal.validate()
    matcher.system = original
    journal.rollback()
    assert Witness().capture(matcher) == before


def test_nested_stale_thread_and_active_handle_replacement_guards():
    matcher = populated()
    system = matcher.system
    journal = Systems(matcher)
    with pytest.raises(RuntimeError, match="already active"):
        Systems(matcher)
    for owner, name in ((matcher, "systems"), (matcher.system, "journal")):
        with pytest.raises(RuntimeError, match="cannot be replaced"):
            setattr(owner, name, None)
        with pytest.raises(RuntimeError, match="cannot be deleted"):
            delattr(owner, name)
    with ThreadPoolExecutor(max_workers=1) as executor:
        for operation in (journal.validate, journal.commit, journal.rollback):
            with pytest.raises(RuntimeError, match="another thread"):
                executor.submit(operation).result()
        with pytest.raises(RuntimeError, match="another thread"):
            executor.submit(journal.reserve, 1).result()
    object.__setattr__(system, "journal", None)
    with pytest.raises(RuntimeError, match="binding changed"):
        journal.validate()
    object.__setattr__(system, "journal", journal)
    matcher.system = object()
    with pytest.raises(TypeError, match="System candidate record"):
        journal.validate()
    matcher.system = system
    candidate = System(matcher.graph, 1)
    object.__setattr__(candidate, "journal", journal)
    matcher.system = candidate
    with pytest.raises(RuntimeError, match="already journaled"):
        journal.validate()
    matcher.system = system
    object.__setattr__(system, "journal", None)
    with pytest.raises(RuntimeError, match="binding changed"):
        journal.validate()
    object.__setattr__(system, "journal", journal)
    object.__setattr__(matcher, "systems", None)
    with pytest.raises(RuntimeError, match="not active"):
        journal.validate()
    with pytest.raises(RuntimeError, match="not active"):
        journal.reserve(1)
    object.__setattr__(matcher, "systems", journal)
    journal.commit()
    assert matcher.systems is None and system.journal is None
    assert not journal.roots and not journal.maps
    with pytest.raises(RuntimeError, match="not active"):
        journal.reserve(1)
    for operation in (journal.validate, journal.commit, journal.rollback):
        with pytest.raises(RuntimeError, match="not active"):
            operation()


@pytest.mark.parametrize("count", [-1, True, 0.5])
def test_invalid_reservation_cannot_reduce_the_bound(count):
    matcher = populated()
    journal = Systems(matcher)
    original = journal.size
    with pytest.raises(ValueError, match="nonnegative integer"):
        journal.reserve(count)
    assert journal.size == original
    journal.rollback()
    with pytest.raises(RuntimeError, match="not active"):
        journal.reserve(1)


@pytest.mark.parametrize("shape", ["fields", "partition", "map", "row"])
def test_invalid_candidate_roots_reject_then_restore_exact_state(shape):
    matcher = populated()
    before = Witness().capture(matcher)
    journal = Systems(matcher)
    if shape == "fields":
        matcher.system.extra = 1
    elif shape == "partition":
        matcher.system.A = ()
    elif shape == "map":
        matcher.system.L_lists = ()
    else:
        matcher.system.lambda_lists = {0: ()}
    with pytest.raises(TypeError, match="System"):
        journal.validate()
    journal.rollback()
    assert Witness().capture(matcher) == before


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
@pytest.mark.parametrize("stage", ["repair", "subphase", "rebuild", "publish"])
def test_real_failure_retains_system_roots_rows_full_state_then_retries(
    mode, backend, stage, monkeypatch
):
    import axiom.core as core

    matcher = populated(mode, backend, dense=stage == "rebuild")
    matcher.phase_length = 1 if stage == "rebuild" else 1000
    matcher.subphase_length = 1 if stage == "subphase" else 1000
    before = Witness().capture(matcher)
    system = matcher.system
    roots = dict(vars(system))
    rows = {
        id(row): row
        for container in (system.lambda_lists, system.L_lists)
        for row in container.values()
    }
    content = {address: tuple(row) for address, row in rows.items()}
    advance = Matcher._Matcher__advance_update_counter

    def fail(owner):
        advance(owner)
        raise RuntimeError("after System mutation")

    def reject(*args):
        raise RuntimeError("System boundary rejected")

    with monkeypatch.context() as patch:
        if stage == "publish":
            patch.setattr(core, "publish", reject)
        else:
            patch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
        with pytest.raises(RuntimeError, match="System mutation|boundary rejected"):
            matcher.delete(0, 1)
    assert matcher.system is system
    assert all(vars(system)[name] is value for name, value in roots.items())
    assert all(tuple(row) == content[address] for address, row in rows.items())
    assert Witness().capture(matcher) == before
    assert matcher.systems is None and system.journal is None
    matcher.delete(0, 1)
    assert matcher.maximal()


@pytest.mark.parametrize("stage", ["commit", "rollback"])
def test_uncertain_system_cleanup_fail_stops_owner(stage, monkeypatch):
    matcher = populated()

    def reject(*args):
        raise RuntimeError("System cleanup failed")

    monkeypatch.setattr(Systems, stage, reject)
    if stage == "rollback":
        monkeypatch.setattr(Matcher, "_Matcher__advance_update_counter", reject)
    with pytest.raises(RuntimeError, match="discard matcher"):
        matcher.delete(0, 1)
    assert matcher.failed
    for operation in (matcher.matching, lambda: matcher.insert(0, 4)):
        with pytest.raises(RuntimeError, match="has failed"):
            operation()
