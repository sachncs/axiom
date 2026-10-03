"""Bounded accounting undo, source identity, and publication failure contracts."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.journal import Journal
from axiom.ledger import Ledger
from axiom.storage import Packed
from axiom.witness import Witness


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_invalid_capacity_rejects_before_source_change(capacity):
    ledger = Ledger()
    before = vars(ledger).copy()
    with pytest.raises(ValueError, match="positive integer"):
        Journal(ledger, capacity)
    assert vars(ledger) == before


def test_first_write_retains_original_and_capacity_failure_is_pre_mutation():
    ledger = Ledger(total_updates=7, total_insertions=3)
    journal = Journal(ledger, 1)
    journal.write("total_updates", 8)
    journal.write("total_updates", 100)
    assert journal.entries == {"total_updates": 7}
    with pytest.raises(MemoryError, match="capacity"):
        journal.write("total_insertions", 4)
    assert ledger.total_insertions == 3
    journal.rollback()
    assert ledger.total_updates == 7
    assert journal.entries == {} and not journal.active
    for operation in (journal.commit, journal.rollback, journal.check):
        with pytest.raises(RuntimeError, match="closed"):
            operation()


@pytest.mark.parametrize(
    "name,value", [("missing", 1), ("journal", 1), ("total_updates", True), (1, 2)]
)
def test_unsupported_write_cannot_change_source(name, value):
    ledger = Ledger()
    before = vars(ledger).copy()
    journal = Journal(ledger, 10)
    with pytest.raises((TypeError, AttributeError)):
        journal.write(name, value)
    assert vars(ledger) == before
    assert journal.entries == {}
    journal.rollback()


def test_descriptor_rejects_without_calling_its_setter():
    class Record:
        def __init__(self):
            self.__dict__["counter"] = 1

        @property
        def counter(self):
            return 1

        @counter.setter
        def counter(self, value):
            raise AssertionError("unsafe setter called")

    record = Record()
    journal = Journal(record, 1)
    with pytest.raises(TypeError, match="descriptor"):
        journal.write("counter", 2)
    assert vars(record) == {"counter": 1} and journal.entries == {}


def test_entry_allocation_failure_precedes_source_write():
    class Failure(dict):
        def __setitem__(self, key, value):
            raise MemoryError("undo allocation")

    ledger = Ledger(total_updates=9)
    journal = Journal(ledger, 1)
    journal.entries = Failure()
    with pytest.raises(MemoryError, match="undo allocation"):
        journal.write("total_updates", 10)
    assert ledger.total_updates == 9
    journal.rollback()


def test_owner_thread_nested_stale_and_replaced_tokens_reject():
    ledger = Ledger()
    journal = ledger.begin()
    with pytest.raises(RuntimeError, match="already active"):
        ledger.begin()
    with pytest.raises(RuntimeError, match="cannot be replaced"):
        ledger.journal = None
    with ThreadPoolExecutor(max_workers=1) as executor:
        for operation in (
            lambda: journal.write("total_updates", 99),
            journal.commit,
            journal.rollback,
        ):
            with pytest.raises(RuntimeError, match="another thread"):
                executor.submit(operation).result()
    assert ledger.total_updates == 0
    ledger.record_insertion()
    ledger.commit(journal)
    assert ledger.total_updates == 1 and ledger.journal is None
    with pytest.raises(RuntimeError, match="stale"):
        ledger.rollback(journal)
    other = Ledger()
    token = other.begin()
    with pytest.raises(RuntimeError, match="stale"):
        ledger.commit(token)
    other.rollback(token)


def test_all_ten_counter_cells_restore_without_replacing_ledger():
    ledger = Ledger()
    before = Witness().capture(ledger)
    journal = ledger.begin()
    ledger.record_insertion()
    ledger.record_deletion()
    ledger.record_phase_rebuild(5)
    ledger.record_subphase_rebuild(6)
    ledger.record_rematch_u_scan(7)
    ledger.record_rematch_b_scan(8)
    ledger.record_rematch_a_scan(9)
    ledger.record_stale_cleanup(10)
    assert len(journal.entries) == 10
    ledger.rollback(journal)
    assert Witness().capture(ledger) == before


@pytest.mark.parametrize("name", ["total_updates", "journal"])
def test_active_field_deletion_rejects_before_mutation(name):
    ledger = Ledger()
    before = Witness().capture(ledger)
    journal = ledger.begin()
    with pytest.raises(RuntimeError, match="cannot be deleted"):
        delattr(ledger, name)
    ledger.rollback(journal)
    assert Witness().capture(ledger) == before
    ledger.scratch = 1
    del ledger.scratch
    assert Witness().capture(ledger) == before


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
@pytest.mark.parametrize("backend", [Adjacency, Packed])
@pytest.mark.parametrize("stage", ["repair", "publish", "admission"])
def test_real_update_rolls_back_accounting_in_place(mode, backend, stage, monkeypatch):
    import axiom.core as core
    from axiom.clocks import Clocks

    matcher = Matcher(16, graph=backend(16), mode=mode)
    matcher.phase_length = 1
    ledger = matcher.accountant
    witness = Witness()
    before = witness.capture(matcher)
    original = Matcher._Matcher__advance_update_counter

    def repair(owner):
        original(owner)
        raise RuntimeError("injected repair")

    def fail(*args, **kwargs):
        raise MemoryError("injected publication or copy")

    with monkeypatch.context() as patch:
        if stage == "repair":
            patch.setattr(Matcher, "_Matcher__advance_update_counter", repair)
        elif stage == "publish":
            patch.setattr(core, "publish", fail)
        else:
            patch.setattr(Clocks, "__init__", fail)
        with pytest.raises((RuntimeError, MemoryError), match="injected"):
            matcher.insert(0, 1)
    assert matcher.accountant is ledger
    assert ledger.journal is None
    assert witness.capture(matcher) == before
    matcher.insert(0, 1)
    assert matcher.accountant is ledger and matcher.maximal()


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_accounting_is_not_deepcopied_on_success_or_failed_repair(mode, monkeypatch):
    def forbidden(*args):
        raise AssertionError("accounting copied")

    monkeypatch.setattr(Ledger, "__deepcopy__", forbidden, raising=False)
    matcher = Matcher(16, mode=mode, graph=Packed(16))
    matcher.insert(0, 1)
    matcher.delete(0, 1)
    matcher.delete(0, 1)
    assert matcher.accountant.total_deletions == 2
    assert matcher.accountant.journal is None


@pytest.mark.parametrize("mode", ["basic", "multilevel"])
def test_noop_deletion_failure_restores_every_counter_and_retry(mode, monkeypatch):
    matcher = Matcher(16, mode=mode, graph=Packed(16))
    ledger = matcher.accountant
    before = Witness().capture(matcher)
    write = Journal.write

    def failure(journal, name, value):
        if name == "phase_update_work":
            raise MemoryError("injected third accounting write")
        write(journal, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(Journal, "write", failure)
        with pytest.raises(MemoryError, match="third accounting write"):
            matcher.delete(0, 1)
    assert matcher.accountant is ledger
    assert Witness().capture(matcher) == before
    matcher.delete(0, 1)
    assert (
        ledger.total_deletions == ledger.total_updates == ledger.phase_update_work == 1
    )
    assert matcher.graph.version == 0


@pytest.mark.parametrize("backend", [Adjacency, Packed])
def test_post_publication_cleanup_failure_is_failstop_not_false_rollback(
    backend, monkeypatch
):
    matcher = Matcher(16, mode="multilevel", graph=backend(16))

    def failure(*args):
        raise MemoryError("cleanup")

    monkeypatch.setattr(Ledger, "commit", failure)
    with pytest.raises(RuntimeError, match="publication cleanup"):
        matcher.insert(0, 1)
    assert matcher.failed and matcher.graph.has_edge(0, 1)
    for operation in (
        matcher.matching,
        matcher.maximal,
        matcher.size,
        matcher.partners,
        matcher.stats,
        matcher.refresh,
        matcher.partition,
        lambda: matcher.partner(0),
        lambda: matcher.insert(2, 3),
        lambda: matcher.delete(0, 1),
        lambda: matcher.add_match(2, 3),
        lambda: matcher.drop_match(0, 1),
    ):
        with pytest.raises(RuntimeError, match="discard matcher"):
            operation()


def test_accounting_rollback_failure_is_failstop_for_absent_delete(monkeypatch):
    matcher = Matcher(8)

    def fail(*args):
        raise MemoryError("accounting failure")

    monkeypatch.setattr(Ledger, "record_deletion", fail)
    monkeypatch.setattr(Ledger, "rollback", fail)
    with pytest.raises(RuntimeError, match="accounting rollback failed"):
        matcher.delete(0, 1)
    assert matcher.failed
    with pytest.raises(RuntimeError, match="discard matcher"):
        matcher.insert(0, 1)


def test_insufficient_accounting_capacity_restores_real_update(monkeypatch):
    matcher = Matcher(16, graph=Packed(16))
    before = Witness().capture(matcher)
    begin = Ledger.begin

    def bounded(owner):
        journal = begin(owner)
        journal.capacity = 1
        return journal

    with monkeypatch.context() as patch:
        patch.setattr(Ledger, "begin", bounded)
        with pytest.raises(MemoryError, match="capacity"):
            matcher.insert(0, 1)
    assert Witness().capture(matcher) == before
    assert matcher.graph.memory()["active"] == 0
    matcher.insert(0, 1)
    assert matcher.maximal()


def test_replaced_accounting_owner_rejects_before_graph_publication(monkeypatch):
    matcher = Matcher(16, graph=Packed(16), mode="multilevel")
    ledger = matcher.accountant
    before = Witness().capture(matcher)
    advance = Matcher._Matcher__advance_update_counter

    def replace(owner):
        advance(owner)
        owner.accountant = Ledger()

    with monkeypatch.context() as patch:
        patch.setattr(Matcher, "_Matcher__advance_update_counter", replace)
        with pytest.raises(RuntimeError, match="accounting owner"):
            matcher.insert(0, 1)
    assert matcher.accountant is ledger
    assert Witness().capture(matcher) == before
    assert matcher.graph.version == 0


def test_unrelated_open_accounting_transaction_is_not_closed_by_rejected_update():
    matcher = Matcher(16, graph=Packed(16))
    ledger = matcher.accountant
    token = ledger.begin()
    with pytest.raises(RuntimeError, match="already active"):
        matcher.insert(0, 1)
    assert ledger.journal is token and token.active
    assert not matcher.failed and matcher.graph.memory()["active"] == 0
    ledger.rollback(token)
    matcher.insert(0, 1)
    assert matcher.maximal()


def test_real_update_rollback_failure_rejects_future_matching_queries(monkeypatch):
    matcher = Matcher(16, graph=Packed(16))

    def fail(*args):
        raise MemoryError("injected rollback failure")

    monkeypatch.setattr(Matcher, "_Matcher__advance_update_counter", fail)
    monkeypatch.setattr(Ledger, "rollback", fail)
    with pytest.raises(RuntimeError, match="rollback failed"):
        matcher.insert(0, 1)
    assert matcher.failed and matcher.graph.memory()["active"] == 0
    with pytest.raises(RuntimeError, match="discard matcher"):
        matcher.matching()
