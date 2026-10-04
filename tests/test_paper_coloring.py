from __future__ import annotations

import random
from copy import deepcopy

import pytest

from axiom.graph import Adjacency
from axiom.paper_coloring import (
    Chain,
    ColorIndex,
    ColorJournal,
    Construction,
    Event,
    Extension,
    Fan,
    FanJournal,
    Fans,
    Paper,
    Partial,
    Pruning,
    Spectrum,
    Spoke,
    Vizing,
)
from axiom.storage import Packed
from axiom.types import Edge, Vertex
from axiom.witness import Witness


class Cases:
    """Small, explicit graphs whose missing colors force paper operations."""

    @staticmethod
    def collisions(
        count: int, chain: bool = False
    ) -> tuple[Partial, set[tuple[int, int]]]:
        graph = Adjacency(8 * count + 11)
        assignments = []
        pending = set()
        for index in range(count):
            offset = 8 * index
            for left, right in ((0, 1), (0, 4), (1, 5), (2, 3), (2, 4), (3, 6), (3, 7)):
                graph.add_edge(offset + left, offset + right)
            for edge, color in (
                ((0, 4), 1),
                ((1, 5), 0),
                ((2, 4), 2),
                ((3, 6), 0),
                ((3, 7), 1),
            ):
                assignments.append(((offset + edge[0], offset + edge[1]), color))
            pending.update({(offset, offset + 1), (offset + 2, offset + 3)})
        if chain:
            offset = 8 * count
            for left, right in ((0, 1), (0, 2), (0, 3), (1, 4), (2, 5), (3, 7)):
                graph.add_edge(offset + left, offset + right)
            for edge, color in (
                ((1, 4), 0),
                ((0, 2), 1),
                ((2, 5), 0),
                ((0, 3), 2),
                ((3, 7), 0),
            ):
                assignments.append(((offset + edge[0], offset + edge[1]), color))
            pending.add((offset, offset + 1))
        coloring = Partial(graph, 3)
        for edge, color in assignments:
            coloring.assign(edge, color)
        return coloring, pending

    @staticmethod
    def multialpha() -> tuple[Partial, set[tuple[int, int]]]:
        """Build two independent uncolored edges with distinct seed colors."""
        graph = Adjacency(8)
        for edge in ((0, 1), (0, 2), (0, 3), (4, 5), (4, 6), (4, 7)):
            graph.add_edge(*edge)
        coloring = Partial(graph, 3)
        for edge, color in (
            ((0, 2), 0),
            ((0, 3), 1),
            ((4, 6), 0),
            ((4, 7), 2),
        ):
            coloring.assign(edge, color)
        return coloring, {(0, 1), (4, 5)}

    @staticmethod
    def multialphafans() -> tuple[Partial, set[tuple[int, int]]]:
        """Build two collision gadgets whose primed edges use distinct colors."""
        coloring, pending = Cases.collisions(2)
        coloring.unassign((8, 12))
        coloring.assign((8, 12), 0)
        return coloring, pending


@pytest.mark.parametrize("count", [2, 3, 8])
def test_routing_prunes_multiple_groups_and_performs_chain_flips(count: int) -> None:
    coloring, pending = Cases.collisions(count, chain=True)

    class Tracing(Vizing):
        paths = []

        @classmethod
        def activate(cls, coloring, chain):
            cls.paths.append(chain.path)
            return super().activate(coloring, chain)

    class Counting(Pruning):
        vizing = Tracing
        selections = 0

        @classmethod
        def choose(cls, coloring, fans, vertex, blocked):
            cls.selections += 1
            return super().choose(coloring, fans, vertex, blocked)

    class Routing(Construction):
        pruning = Counting

    fans = Routing.collect(coloring, pending)
    assert Counting.selections == count
    assert len(fans) == count
    assert (8 * count, 8 * count + 2, 8 * count + 5) in Tracing.paths
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)
    assert all(fan.center == 8 * index + 4 for index, fan in enumerate(fans))
    assert Routing.small(coloring, fans) == count
    completed = Paper.complete(coloring, set(coloring.graph.edges()), 3)
    Paper.certify(coloring.graph, 3, set(coloring.graph.edges()), completed)
    assert not fans


def test_construct_uses_one_admission_and_one_final_full_coloring_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coloring, pending = Cases.multialphafans()
    assert len({item.alpha for item in Pruning.seed(coloring, pending)}) == 2
    originalvalidate = Partial.validate
    originalcertify = Partial.certify
    originalfanvalidate = Fans.validate
    originalcompatible = Fans.compatible
    audits = 0
    fanaudits = 0
    compatibilityaudits = 0
    localcertificates = 0
    localcompatibility = 0
    certificates = []

    def count_audit(candidate: Partial) -> None:
        nonlocal audits
        audits += 1
        originalvalidate(candidate)

    def count_certificate(candidate: Partial, edges) -> None:
        certificates.append(tuple(sorted(edges)))
        originalcertify(candidate, certificates[-1])

    def count_fan_audit(candidate: Fans) -> None:
        nonlocal fanaudits
        fanaudits += 1
        originalfanvalidate(candidate)

    def count_compatibility(candidate: Fans, partial: Partial, vertices=None) -> None:
        nonlocal compatibilityaudits, localcompatibility
        if vertices is None:
            compatibilityaudits += 1
        else:
            localcompatibility += 1
        originalcompatible(candidate, partial, vertices)

    originalfancertify = Fans.certify

    def count_fan_certificate(candidate: Fans, vertices) -> None:
        nonlocal localcertificates
        localcertificates += 1
        originalfancertify(candidate, vertices)

    monkeypatch.setattr(Partial, "validate", count_audit)
    monkeypatch.setattr(Partial, "certify", count_certificate)
    monkeypatch.setattr(Fans, "validate", count_fan_audit)
    monkeypatch.setattr(Fans, "compatible", count_compatibility)
    monkeypatch.setattr(Fans, "certify", count_fan_certificate)
    parentjournal = ColorJournal(coloring)
    fans = Pruning.construct(coloring, pending, journal=parentjournal)

    assert audits == 2
    assert fanaudits == 2
    assert compatibilityaudits == 2
    assert localcertificates > 0
    assert localcompatibility > 0
    assert not parentjournal.admitted
    assert certificates
    assert pending <= set(coloring.assignments) | fans.spokes
    originalvalidate(coloring)
    fans.validate()
    fans.compatible(coloring)
    assert len(fans) == 1

    repeated, repeatedpending = Cases.multialphafans()
    repeatedfans = Pruning.construct(repeated, repeatedpending)
    assert dict(coloring.items()) == dict(repeated.items())
    assert tuple(fans) == tuple(repeatedfans)


def test_unadmitted_reduction_keeps_both_full_coloring_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coloring, pending = Cases.multialpha()
    journal = ColorJournal(coloring)
    originalvalidate = Partial.validate
    audits = 0

    def count_audit(candidate: Partial) -> None:
        nonlocal audits
        audits += 1
        originalvalidate(candidate)

    monkeypatch.setattr(Partial, "validate", count_audit)
    fans = Fans()
    Pruning.reduce(coloring, fans, Pruning.seed(coloring, pending), journal=journal)

    assert audits == 2
    assert pending <= set(coloring.assignments)
    originalvalidate(coloring)


def test_final_fan_audit_failure_restores_coloring_and_discards_partial_fans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coloring, pending = Cases.multialphafans()
    before = Witness().capture(coloring)
    collections = []
    originaladd = Fans.add
    originalvalidate = Fans.validate
    audits = 0

    def capture_collection(candidate: Fans, fan: Fan) -> None:
        collections.append(candidate)
        originaladd(candidate, fan)

    def corrupt_at_final_boundary(candidate: Fans) -> None:
        nonlocal audits
        audits += 1
        if audits == 2 and candidate.members:
            vertex = next(iter(candidate.assigned))
            candidate.assigned[vertex].pop()
        originalvalidate(candidate)

    monkeypatch.setattr(Fans, "add", capture_collection)
    monkeypatch.setattr(Fans, "validate", corrupt_at_final_boundary)
    with pytest.raises(AssertionError, match="assigned-color index is stale"):
        Pruning.construct(coloring, pending)

    assert audits == 3
    assert collections
    assert all(not candidate.members for candidate in collections)
    for candidate in collections:
        originalvalidate(candidate)
        candidate.compatible(coloring)
    assert Witness().capture(coloring) == before
    coloring.validate()


def test_construct_does_not_leak_admission_to_caller_journal() -> None:
    coloring, pending = Cases.multialpha()
    journal = ColorJournal(coloring)
    Pruning.construct(coloring, pending, journal=journal)

    assert not journal.admitted
    edge, color = next(iter(coloring.items()))
    coloring.index.pop((edge[0], color), None)
    with pytest.raises(AssertionError, match="stale|certificate"):
        Pruning.reduce(coloring, Fans(), (), journal=journal)


def test_admitted_local_certificate_failure_rolls_back_coloring_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coloring, pending = Cases.multialpha()
    witness = Witness()
    before = witness.capture(coloring)
    roots = (coloring.assignments, coloring.incident, coloring.index)
    originalcertify = Partial.certify
    rejected = False

    def reject_corrupt_touched_cell(candidate: Partial, edges) -> None:
        nonlocal rejected
        if not rejected:
            for edge in edges:
                color = candidate.assignments.get(edge)
                if color is not None:
                    candidate.index.pop((edge[0], color), None)
                    rejected = True
                    break
        originalcertify(candidate, edges)

    monkeypatch.setattr(Partial, "certify", reject_corrupt_touched_cell)
    with pytest.raises(
        AssertionError, match="coloring edge certificate failed|local index is stale"
    ):
        Pruning.construct(coloring, pending)

    assert rejected
    assert witness.capture(coloring) == before
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            roots,
            strict=True,
        )
    )
    originalcertify(coloring, pending)
    coloring.validate()


def test_partial_replace_cycles_colors_and_rolls_back_failed_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(3)
    for edge in ((0, 1), (1, 2), (0, 2)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((0, 1), 0)
    coloring.assign((1, 2), 1)
    coloring.assign((0, 2), 2)

    coloring.replace({(0, 1): 1, (1, 2): 0})
    assert coloring.assignments == {(0, 1): 1, (1, 2): 0, (0, 2): 2}
    coloring.validate()

    before = deepcopy(
        {key: value for key, value in vars(coloring).items() if key != "graph"}
    )

    def fail(candidate: Partial, edges) -> None:
        raise RuntimeError("injected local coloring certificate failure")

    monkeypatch.setattr(Partial, "certify", fail)
    with pytest.raises(
        RuntimeError, match="injected local coloring certificate failure"
    ):
        coloring.replace({(0, 1): 0, (1, 2): 1})
    assert {
        key: value for key, value in vars(coloring).items() if key != "graph"
    } == before


def test_partial_relabel_stages_indexes_and_reuses_assignment_storage() -> None:
    graph = Adjacency(4)
    for edge in ((0, 1), (0, 2), (2, 3)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((0, 1), 0)
    coloring.assign((0, 2), 1)
    coloring.assign((2, 3), 0)
    assignments = coloring.assignments

    coloring.relabel({0: 2, 1: 0, 2: 1})

    assert coloring.assignments is assignments
    assert dict(coloring.items()) == {
        (0, 1): 2,
        (0, 2): 0,
        (2, 3): 2,
    }
    coloring.validate()


@pytest.mark.parametrize(
    ("mapping", "removeedge"),
    [({0: 1, 1: 0}, False), ({0: 2, 1: 1, 2: 0}, True)],
)
def test_partial_relabel_failure_preserves_all_state(
    mapping: dict[int, int], removeedge: bool
) -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(1, 2)
    coloring = Partial(graph, 3)
    coloring.assign((0, 1), 0)
    coloring.assign((1, 2), 1)
    if removeedge:
        graph.remove_edge(1, 2)
    contents = (
        dict(coloring.assignments),
        {vertex: set(colors) for vertex, colors in coloring.incident.items()},
        dict(coloring.index),
    )
    roots = (coloring.assignments, coloring.incident, coloring.index)

    with pytest.raises((AssertionError, ValueError)):
        coloring.relabel(mapping)

    assert dict(coloring.assignments) == contents[0]
    assert coloring.incident == contents[1]
    assert coloring.index == contents[2]
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            roots,
            strict=True,
        )
    )


def test_partial_coloring_incidence_rows_scale_with_touched_vertices() -> None:
    graph = Adjacency(100_000)
    graph.add_edge(10, 11)
    coloring = Partial(graph, 3)

    assert coloring.incident == {}
    assert coloring.available(99_999, 0)
    assert coloring.incident == {}

    coloring.assign((10, 11), 2)
    assert coloring.incident == {10: {2}, 11: {2}}
    coloring.validate()

    coloring.unassign((10, 11))
    assert coloring.incident == {}
    coloring.reindex()
    coloring.validate()


def test_pruning_restores_every_index_after_a_later_collision_failure() -> None:
    coloring, pending = Cases.collisions(3)
    graph = coloring.graph
    for leaf in (33, 34):
        graph.add_edge(32, leaf)
    fans = Fans()
    sentinel = Fan(32, 33, 34, 0, 1, 1)
    fans.add(sentinel)
    colors = deepcopy(
        {key: value for key, value in vars(coloring).items() if key != "graph"}
    )
    snapshot = deepcopy(vars(fans))
    witness = Witness()
    before = witness.capture((coloring, fans))

    class Failure(Pruning):
        collisions = 0

        @classmethod
        def choose(cls, coloring, fans, vertex, blocked):
            cls.collisions += 1
            if cls.collisions == 2:
                assert len(fans) == 2
                raise RuntimeError("failed center-color precondition")
            return super().choose(coloring, fans, vertex, blocked)

    with pytest.raises(RuntimeError, match="failed center-color precondition"):
        Failure.prune(coloring, fans, Pruning.seed(coloring, pending))
    assert coloring.graph is graph
    assert {
        key: value for key, value in vars(coloring).items() if key != "graph"
    } == colors
    assert vars(fans) == snapshot
    assert witness.capture((coloring, fans)) == before
    assert tuple(fans) == (sentinel,)
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_fan_relabel_failure_preserves_every_index() -> None:
    fans = Fans()
    fans.add(Fan(0, 1, 2, 0, 1, 1))
    fans.add(Fan(3, 4, 5, 1, 0, 0))
    snapshot = deepcopy(vars(fans))
    roots = tuple(vars(fans).values())

    with pytest.raises(ValueError, match="colors must differ"):
        fans.relabel({0: 0, 1: 0})

    assert vars(fans) == snapshot
    assert all(
        actual is original
        for actual, original in zip(vars(fans).values(), roots, strict=True)
    )
    fans.validate()


def test_fan_relabel_publishes_a_complete_color_permutation() -> None:
    fans = Fans()
    first = Fan(0, 1, 2, 0, 1, 1)
    second = Fan(3, 4, 5, 1, 0, 0)
    fans.add(first)
    fans.add(second)

    fans.relabel({0: 1, 1: 0})

    assert set(fans) == {
        Fan(0, 1, 2, 1, 0, 0),
        Fan(3, 4, 5, 0, 1, 1),
    }
    fans.validate()


def test_fan_relabel_staging_failure_does_not_publish_partial_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fans = Fans()
    fans.add(Fan(0, 1, 2, 0, 1, 1))
    fans.add(Fan(3, 4, 5, 1, 0, 0))
    snapshot = deepcopy(vars(fans))
    roots = tuple(vars(fans).values())
    original = Fans.add
    builds = 0

    def fail_on_second(candidate: Fans, fan: Fan) -> None:
        nonlocal builds
        if candidate is not fans:
            builds += 1
            if builds == 2:
                raise RuntimeError("injected staged fan-index failure")
        original(candidate, fan)

    monkeypatch.setattr(Fans, "add", fail_on_second)
    with pytest.raises(RuntimeError, match="injected staged fan-index failure"):
        fans.relabel({0: 1, 1: 0})

    assert vars(fans) == snapshot
    assert all(
        actual is original
        for actual, original in zip(vars(fans).values(), roots, strict=True)
    )
    fans.validate()


def test_fan_update_changes_only_the_target_fan_indexes() -> None:
    fans = Fans()
    original = Fan(0, 1, 2, 0, 1, 1)
    unrelated = Fan(3, 4, 5, 2, 0, 0)
    fans.add(original)
    fans.add(unrelated)
    roots = vars(fans).copy()

    replacement = fans.update(original, 0, 2)

    assert replacement == Fan(0, 1, 2, 2, 1, 1)
    assert original not in fans.members and replacement in fans.members
    assert unrelated in fans.members
    assert all(vars(fans)[name] is value for name, value in roots.items())
    fans.validate()


def test_nested_fan_journal_restores_updates_relabel_and_membership() -> None:
    fans = Fans()
    original = Fan(0, 1, 2, 0, 1, 1)
    unrelated = Fan(3, 4, 5, 0, 1, 1)
    added = Fan(6, 7, 8, 0, 1, 1)
    fans.add(original)
    fans.add(unrelated)
    statebefore = Witness().capture(fans)
    roots = vars(fans).copy()

    outer = FanJournal(fans)
    fans.journal = outer
    assert fans.update(original, 0, 2) == Fan(0, 1, 2, 2, 1, 1)

    inner = FanJournal(fans, outer)
    fans.journal = inner
    fans.relabel({0: 1, 1: 2, 2: 0})
    inner.commit()
    fans.add(added)
    outer.rollback()

    assert fans.journal is None
    assert Witness().capture(fans) == statebefore
    assert all(vars(fans)[name] is value for name, value in roots.items())
    fans.validate()


def test_fan_clear_swaps_roots_and_nested_rollback_restores_exact_state() -> None:
    fans = Fans()
    original = Fan(0, 1, 2, 0, 1, 1)
    other = Fan(3, 4, 5, 0, 1, 1)
    replacement = Fan(6, 7, 8, 0, 1, 1)
    fans.add(original)
    fans.add(other)
    before = Witness().capture(fans)
    roots = vars(fans).copy()

    outer = FanJournal(fans)
    fans.journal = outer
    inner = FanJournal(fans, outer)
    fans.journal = inner
    fans.clear()
    assert not fans
    assert all(
        not getattr(fans, name)
        for name in (
            "members",
            "spokes",
            "assignments",
            "assigned",
            "vertices",
            "types",
        )
    )
    assert all(
        vars(fans)[name] is not value
        for name, value in roots.items()
        if name != "journal"
    )
    fans.add(replacement)
    inner.commit()
    outer.rollback()

    assert fans.journal is None
    assert Witness().capture(fans) == before
    assert all(vars(fans)[name] is value for name, value in roots.items())
    fans.validate()


def test_fan_clear_without_journal_leaves_a_valid_empty_collection() -> None:
    class NonIteratingFans(Fans):
        def __iter__(self):
            raise AssertionError("clear must not enumerate fan members")

    fans = NonIteratingFans()
    fans.add(Fan(0, 1, 2, 0, 1, 1))

    fans.clear()

    assert len(fans) == 0
    assert not fans.spokes
    assert not fans.assignments
    assert not fans.assigned
    assert not fans.vertices
    assert not fans.types
    fans.validate()


def test_fan_update_staging_failure_restores_partial_reservations() -> None:
    class FailingColors(set[int]):
        def add(self, value: int) -> None:
            raise RuntimeError("injected fan color-index allocation failure")

    fans = Fans()
    original = Fan(0, 1, 2, 0, 1, 1)
    fans.add(original)
    colors = fans.assigned[0]
    fans.assigned[0] = FailingColors(colors)
    snapshot = deepcopy(vars(fans))
    roots = vars(fans).copy()

    with pytest.raises(RuntimeError, match="injected fan color-index allocation"):
        fans.update(original, 0, 2)

    assert vars(fans) == snapshot
    assert all(vars(fans)[name] is value for name, value in roots.items())
    fans.assigned[0] = colors
    fans.validate()


def test_fan_update_drops_replacement_on_separability_collision() -> None:
    fans = Fans()
    original = Fan(0, 1, 2, 0, 1, 1)
    blocker = Fan(3, 0, 4, 1, 2, 2)
    fans.add(original)
    fans.add(blocker)

    assert fans.update(original, 0, 2) is None

    assert original not in fans.members
    assert blocker in fans.members
    fans.validate()


def test_fan_flip_rolls_back_coloring_and_prior_endpoint_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(6)
    for edge in ((0, 1), (0, 2), (0, 3), (1, 4), (1, 5)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((0, 1), 1)
    fans = Fans()
    fans.add(Fan(0, 2, 3, 0, 1, 1))
    fans.add(Fan(1, 4, 5, 0, 2, 2))
    fans.compatible(coloring)
    before = Witness().capture((coloring, fans))
    update = Fans.update
    calls = 0

    def fail_on_second_update(
        collection: Fans, fan: Fan, vertex: int, color: int
    ) -> Fan | None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second-endpoint update failure")
        return update(collection, fan, vertex, color)

    with monkeypatch.context() as patcher:
        patcher.setattr(Fans, "update", fail_on_second_update)
        with pytest.raises(RuntimeError, match="second-endpoint update failure"):
            fans.flip(coloring, [0, 1], 0, 1)

    assert Witness().capture((coloring, fans)) == before
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


@pytest.mark.parametrize("size", [0, 1, 2, 5, 12, 33])
@pytest.mark.parametrize("family", ["path", "cycle", "star", "clique", "bipartite"])
def test_paper_certifies_graph_families(size: int, family: str) -> None:
    graph = Adjacency(size)
    for left in range(size):
        for right in range(left + 1, size):
            include = {
                "path": right == left + 1,
                "cycle": right == left + 1 or (left == 0 and right == size - 1),
                "star": left == 0,
                "clique": True,
                "bipartite": left < size // 2 <= right,
            }[family]
            if include:
                graph.add_edge(left, right)
    delta = max((graph.degree(vertex) for vertex in range(size)), default=0)
    result = Paper.color(graph, delta)
    Paper.certify(graph, delta, set(graph.edges()), result)
    assert result == Paper.color(graph, delta)


def test_paper_defers_edge_snapshot_until_recursive_seed_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid overlapping the result edge set with recursive seed temporaries."""

    class TrackingGraph:
        def __init__(self) -> None:
            self.backing = Adjacency(2)
            self.backing.add_edge(0, 1)
            self.edge_reads = 0

        @property
        def n(self) -> int:
            return self.backing.n

        def edges(self):
            self.edge_reads += 1
            return self.backing.edges()

        def __getattr__(self, name: str):
            return getattr(self.backing, name)

    graph = TrackingGraph()

    def seed(cls, source, delta):
        assert source is graph
        assert graph.edge_reads == 0
        assert delta == 32
        return {(0, 1): 0}

    monkeypatch.setattr(Paper, "seed", classmethod(seed))

    result = Paper.color(graph, 32)

    assert result == {(0, 1): 0}
    assert graph.edge_reads == 1


def test_paper_certificate_compares_key_view_without_copying_coloring_keys() -> None:
    class KeyViewOnly(dict):
        def __iter__(self):
            raise AssertionError("certificate copied all coloring keys")

    graph = Adjacency(2)
    graph.add_edge(0, 1)
    coloring = KeyViewOnly({(0, 1): 0})

    Paper.certify(graph, 1, {(0, 1)}, coloring)


def test_paper_complete_computes_initial_uncolored_edge_set_once() -> None:
    class DifferenceCount(set):
        def __init__(self, values=()):
            super().__init__(values)
            self.differences = 0

        def __sub__(self, other):
            self.differences += 1
            return super().__sub__(other)

    graph = Adjacency(6)
    edges = [(vertex, vertex + 1) for vertex in range(5)]
    for edge in edges:
        graph.add_edge(*edge)
    all_edges = DifferenceCount(edges)

    result = Paper.complete(Partial(graph, 3), all_edges, 2)

    assert result.keys() == all_edges
    assert all_edges.differences == 1


def test_paper_complete_recolors_edges_uncolored_by_fan_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(2)
    graph.add_edge(0, 1)
    coloring = Partial(graph, 2)
    coloring.assign((0, 1), 0)

    class ReopeningConstruction:
        @classmethod
        def collect(cls, start, pending):
            assert not pending
            start.unassign((0, 1))
            return Fans()

    monkeypatch.setattr(Paper, "construction", ReopeningConstruction)

    result = Paper.complete(coloring, {(0, 1)}, 1)

    assert result.keys() == {(0, 1)}
    coloring.validate()


@pytest.mark.parametrize("delta", [-1, True, 2.5, "3"])
def test_paper_rejects_invalid_degree_bounds(delta: object) -> None:
    with pytest.raises(ValueError, match="delta"):
        Paper.color(Adjacency(2), delta)


def test_paper_dispatches_composed_strategies_through_subclasses() -> None:
    class Selection(Construction):
        selections = 0

        @classmethod
        def collect(cls, coloring, edges):
            cls.selections += 1
            return super().collect(coloring, edges)

    class Algorithm(Paper):
        construction = Selection

    graph = Adjacency(5)
    for leaf in range(1, 5):
        graph.add_edge(0, leaf)
    result = Algorithm.color(graph, 4)
    assert Selection.selections == 1
    Paper.certify(graph, 4, set(graph.edges()), result)


def test_construction_accepts_an_empty_matching_without_mutation() -> None:
    coloring, pending = Cases.collisions(2)
    before = dict(coloring.items())
    fans = Pruning.construct(coloring, set())
    assert not fans
    assert dict(coloring.items()) == before
    fans.compatible(coloring)


@pytest.mark.parametrize("failure", ["matching", "colored", "outside", "orientation"])
def test_construction_rejects_invalid_matching_without_mutation(failure: str) -> None:
    coloring, pending = Cases.collisions(2)
    invalid = {
        "matching": {(0, 1), (0, 4)},
        "colored": {(0, 4)},
        "outside": {(0, 10)},
        "orientation": {(1, 0)},
    }[failure]
    if failure == "matching":
        coloring.unassign((0, 4))
    before = deepcopy(
        {key: value for key, value in vars(coloring).items() if key != "graph"}
    )
    with pytest.raises(ValueError):
        Pruning.construct(coloring, invalid)
    assert {
        key: value for key, value in vars(coloring).items() if key != "graph"
    } == before
    coloring.validate()


@pytest.mark.parametrize("density", [0.1, 0.4, 0.8])
@pytest.mark.parametrize("seed", [7, 19, 41])
def test_paper_certifies_seeded_graphs_with_sparse_and_dense_edges(
    density: float,
    seed: int,
) -> None:
    rng = random.Random(seed)
    graph = Adjacency(24)
    for left in range(24):
        for right in range(left + 1, 24):
            if rng.random() < density:
                graph.add_edge(left, right)
    delta = max(graph.degree(vertex) for vertex in range(24))
    result = Paper.color(graph, delta)
    Paper.certify(graph, delta, set(graph.edges()), result)


def test_paper_rejects_a_degree_bound_below_the_graph_maximum() -> None:
    graph = Adjacency(4)
    for leaf in range(1, 4):
        graph.add_edge(0, leaf)
    with pytest.raises(ValueError, match="maximum degree"):
        Paper.color(graph, 2)


def test_paper_eta_selects_only_a_valid_recursive_regime() -> None:
    assert Paper.regime(128, 129) is None
    assert Paper.regime(1024, 1025) == 90
    assert Paper.regime(1024, 99) is None


def test_seed_palette_reduction_certifies_complete_graph_with_excess_palette() -> None:
    graph = Adjacency(34)
    for left in range(graph.n):
        for right in range(left + 1, graph.n):
            graph.add_edge(left, right)
    delta = max(graph.degree(vertex) for vertex in range(graph.n))
    left, right = Paper.partition(graph)
    leftdelta = max(left.degree(vertex) for vertex in range(graph.n))
    rightdelta = max(right.degree(vertex) for vertex in range(graph.n))
    assert leftdelta + rightdelta + 2 > delta + 1

    coloring = Paper.seed(graph, delta)

    Paper.certify(graph, delta, set(graph.edges()), coloring)


def test_partition_component_discovery_avoids_isolated_vertex_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Packed(2_048)
    graph.add_edge(0, 1)
    graph.add_edge(1, 2)
    graph.add_edge(1_000, 1_001)
    originalrange = range
    universescans = 0

    def trackrange(*arguments: int) -> range:
        nonlocal universescans
        if arguments == (graph.n,):
            universescans += 1
        return originalrange(*arguments)

    monkeypatch.setattr("axiom.paper_coloring.range", trackrange, raising=False)

    left, right = Paper.partition(graph)

    assert universescans == 0
    leftedges = set(left.edges())
    rightedges = set(right.edges())
    assert leftedges.isdisjoint(rightedges)
    assert leftedges | rightedges == set(graph.edges())


@pytest.mark.parametrize(
    "edges",
    [
        (),
        ((0, 1), (1, 2), (2, 0)),
        ((0, 1), (1, 2), (2, 3), (4, 5)),
        ((0, 1), (0, 2), (0, 3), (2, 4), (5, 6), (6, 7)),
    ],
)
def test_partition_byte_indexes_preserve_disconnected_and_odd_degree_cases(
    edges: tuple[tuple[int, int], ...],
) -> None:
    graph = Adjacency(9)
    for edge in edges:
        graph.add_edge(*edge)

    first = Paper.partition(graph)
    second = Paper.partition(graph)
    firstedges = set(first[0].edges()), set(first[1].edges())
    secondedges = set(second[0].edges()), set(second[1].edges())

    assert firstedges == secondedges
    assert firstedges[0].isdisjoint(firstedges[1])
    assert firstedges[0] | firstedges[1] == set(graph.edges())
    bound = (
        max((graph.degree(vertex) for vertex in range(graph.n)), default=0) + 2
    ) // 2
    for vertex in range(graph.n):
        assert first[0].degree(vertex) <= bound
        assert first[1].degree(vertex) <= bound


def test_paper_maximum_degree_uses_sparse_endpoints_without_extra_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Packed(100_000)
    graph.add_edge(0, 1)
    graph.add_edge(1, 2)
    originalrange = range
    universescans = 0

    def trackrange(*arguments: int) -> range:
        nonlocal universescans
        if arguments == (graph.n,):
            universescans += 1
        return originalrange(*arguments)

    monkeypatch.setattr("axiom.paper_coloring.range", trackrange, raising=False)

    assert Paper.maximum(graph) == 2
    assert universescans == 0


def test_paper_maximum_degree_keeps_universe_scan_for_dense_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Packed(8)
    for left in range(graph.n):
        for right in range(left + 1, graph.n):
            graph.add_edge(left, right)
    originalrange = range
    universescans = 0

    def trackrange(*arguments: int) -> range:
        nonlocal universescans
        if arguments == (graph.n,):
            universescans += 1
        return originalrange(*arguments)

    monkeypatch.setattr("axiom.paper_coloring.range", trackrange, raising=False)

    assert Paper.maximum(graph) == graph.n - 1
    assert universescans == 1


def test_separable_fans_enforce_edge_and_vertex_color_disjointness() -> None:
    fans = Fans()
    first = Fan(0, 1, 2, 0, 1, 1)
    fans.add(first)
    fans.validate()
    assert fans.find(0, 0) == first
    assert fans.find(1, 1) == first
    assert fans.select(first.type) == (first,)
    assert fans.counts() == {first.type: 1}
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    bounded = Partial(graph, 10)
    assert fans.missing(bounded, 0) == 1

    with pytest.raises(ValueError, match="edge-disjoint"):
        fans.add(Fan(0, 1, 3, 2, 3, 3))
    with pytest.raises(ValueError, match="colors must be distinct"):
        fans.add(Fan(0, 4, 5, 0, 2, 2))


def test_modify_types_rejects_fans_incompatible_with_coloring() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 100)
    coloring.assign((0, 1), 0)
    fans = Fans()
    fan = Fan(0, 1, 2, 1, 2, 2)
    fans.add(fan)
    blocks, ignored = Spectrum.blocks(100, 10)

    with pytest.raises(AssertionError, match="spoke is already colored"):
        Spectrum.modify(coloring, fans, (fan,), blocks, 0)

    assert dict(coloring.items()) == {((0, 1)): 0}
    assert tuple(fans) == (fan,)


def test_project_subproblem_isolates_the_recursive_edge_scope() -> None:
    graph = Adjacency(6)
    for edge in ((0, 1), (0, 2), (3, 4), (4, 5)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 10)
    coloring.assign((3, 4), 0)
    coloring.assign((4, 5), 5)
    fans = Fans()
    fans.add(Fan(0, 1, 2, 0, 1, 1))

    child, childfans, scope, ignored = Extension.project(
        coloring, fans, frozenset({0, 1})
    )

    assert scope == {(0, 1), (0, 2), (3, 4)}
    assert isinstance(child.graph, Packed)
    assert set(child.graph.edges()) == scope
    assert set(child.graph.edges()) != set(graph.edges())
    assert tuple(childfans) == tuple(fans)


def test_project_subproblem_preserves_packed_budget() -> None:
    graph = Packed(6, budget=1 << 20)
    graph.add_edge(0, 1)
    graph.add_edge(3, 4)
    coloring = Partial(graph, 2)
    coloring.assign((0, 1), 0)
    coloring.assign((3, 4), 1)

    child, _, scope, _ = Extension.project(coloring, Fans(), frozenset({0, 1}))

    assert isinstance(child.graph, Packed)
    assert child.graph.memory()["budget"] == graph.memory()["budget"]
    assert set(child.graph.edges()) == scope


def test_project_does_not_sort_materialize_the_parent_fan_collection() -> None:
    class CountedFans(Fans):
        def __init__(self) -> None:
            super().__init__()
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    count = 100
    graph = Adjacency(3 * count)
    fans = CountedFans()
    for index in range(count):
        center = 3 * index
        graph.add_edge(center, center + 1)
        graph.add_edge(center, center + 2)
        fans.add(Fan(center, center + 1, center + 2, 0, 1, 1))
    coloring = Partial(graph, 4)

    child, childfans, scope, ignored = Extension.project(
        coloring, fans, frozenset({0, 1})
    )

    assert fans.iterations == 0
    assert len(childfans) == count
    assert len(scope) == 2 * count
    assert isinstance(child.graph, Packed)
    child.validate()
    childfans.validate()


def test_project_color_index_selects_only_requested_assignments_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(9)
    for edge in (
        (0, 1),
        (0, 2),
        (3, 4),
        (3, 5),
        (6, 7),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 4)
    coloring.assign((6, 7), 0)
    coloring.assign((3, 4), 2)
    fans = Fans()
    chosen = Fan(0, 1, 2, 0, 1, 1)
    unrelated = Fan(3, 4, 5, 2, 3, 3)
    fans.add(unrelated)
    fans.add(chosen)
    index = ColorIndex(coloring)
    before = Witness().capture((coloring, fans))

    def reject_rescan(self: Partial):
        raise AssertionError("projection rescanned the full coloring")

    monkeypatch.setattr(Partial, "items", reject_rescan)
    child, childfans, scope, localcolors = Extension.project(
        coloring, fans, frozenset({0, 1}), index
    )

    assert scope == {(0, 1), (0, 2), (6, 7)}
    assert child.assignments == {(6, 7): 0}
    assert localcolors == (0, 1)
    assert childfans.members == {chosen}
    assert Witness().capture((coloring, fans)) == before
    child.validate()
    childfans.validate()


def test_fan_color_index_selection_is_deterministic_and_type_local() -> None:
    graph = Adjacency(12)
    fans = Fans()
    selected = (Fan(6, 7, 8, 0, 1, 1), Fan(0, 1, 2, 0, 1, 1))
    excluded = Fan(3, 4, 5, 2, 3, 3)
    for fan in (*selected, excluded):
        for edge in fan.edges:
            graph.add_edge(*edge)
    fans.add(selected[0])
    fans.add(excluded)
    fans.add(selected[1])

    assert fans.within({0, 1}) == (selected[1], selected[0])
    assert fans.within({2, 3}) == (excluded,)


def test_project_rejects_infeasible_degree_without_mutating_parent_state() -> None:
    graph = Adjacency(4)
    for edge in ((0, 1), (0, 2), (0, 3)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 2)
    coloring.assign((0, 3), 1)
    fans = Fans()
    fans.add(Fan(0, 1, 2, 0, 1, 1))
    witness = Witness()
    before = witness.capture((coloring, fans))

    with pytest.raises(RuntimeError, match="maximum degree 3 exceeds palette size 2"):
        Extension.project(coloring, fans, frozenset({0, 1}))

    assert witness.capture((coloring, fans)) == before
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_project_subproblem_keeps_custom_graph_fallback() -> None:
    class Custom:
        def __init__(self, graph: Adjacency) -> None:
            self.graph = graph

        def __getattr__(self, name: str):
            return getattr(self.graph, name)

    backing = Adjacency(4)
    backing.add_edge(0, 1)
    graph = Custom(backing)
    coloring = Partial(graph, 2)
    coloring.assign((0, 1), 1)

    child, _, scope, _ = Extension.project(coloring, Fans(), frozenset({1}))

    assert isinstance(child.graph, Adjacency)
    assert set(child.graph.edges()) == scope == {(0, 1)}


def test_partial_coloring_flip_preserves_properness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(1, 2)
    graph.add_edge(2, 3)
    coloring = Partial(graph, 3)
    coloring.assign((1, 2), 1)
    coloring.assign((2, 3), 0)

    path = coloring.path(1, 0, 1)
    assert path == [1, 2, 3]

    def reject_full_reindex() -> None:
        raise AssertionError("path-local flip invoked a full reindex")

    monkeypatch.setattr(coloring, "reindex", reject_full_reindex)
    coloring.flip(path, 0, 1)
    assert coloring[(1, 2)] == 0
    assert coloring[(2, 3)] == 1
    assert coloring.missing(1) == [1, 2]
    assert coloring.available(1, 1)
    assert not coloring.available(1, 0)
    assert coloring.vacancy(1) == 1


@pytest.mark.parametrize("edge_count", [1, 2, 3, 4])
@pytest.mark.parametrize("reverse", [False, True])
def test_path_local_flip_handles_path_parity_and_orientation(
    edge_count: int, reverse: bool
) -> None:
    path = list(range(edge_count + 1))
    if reverse:
        path.reverse()
    graph = Adjacency(edge_count + 1)
    coloring = Partial(graph, 3)
    originals = []
    for index in range(edge_count):
        edge = path[index], path[index + 1]
        graph.add_edge(*edge)
        color = 1 if index % 2 == 0 else 0
        coloring.assign(edge, color)
        originals.append(color)

    coloring.flip(path, 0, 1)

    result = [coloring[(path[index], path[index + 1])] for index in range(edge_count)]
    assert result == [1 - color for color in originals]
    coloring.validate()


def test_partial_coloring_rejects_an_improper_endpoint_flip_atomically() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 2)
    coloring.assign((0, 1), 1)
    coloring.assign((0, 2), 0)
    assignments = dict(coloring.assignments)
    incident = {vertex: set(colors) for vertex, colors in coloring.incident.items()}
    index = dict(coloring.index)
    roots = (coloring.assignments, coloring.incident, coloring.index)

    with pytest.raises(ValueError, match="already present at an endpoint"):
        coloring.flip([1, 0], 0, 1)

    assert coloring.assignments == assignments
    assert coloring.incident == incident
    assert coloring.index == index
    assert coloring.assignments is roots[0]
    assert coloring.incident is roots[1]
    assert coloring.index is roots[2]
    coloring.validate()


def test_activate_fan_extends_one_uncolored_spoke() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(1, 3)
    coloring = Partial(graph, 2)
    coloring.assign((1, 3), 0)
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 1, 1)
    fans.add(fan)

    extended = Construction.activate(coloring, fans, fan)

    assert extended == (0, 1)
    assert coloring[(0, 1)] == 0
    assert (0, 1) in coloring
    assert len(fans) == 0
    fans.validate()


def test_color_small_journals_changes_and_rolls_back_mid_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(6)
    for edge in ((0, 1), (0, 2), (3, 4), (3, 5)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    fans = Fans()
    first = Fan(0, 1, 2, 0, 1, 1)
    second = Fan(3, 4, 5, 0, 1, 1)
    fans.add(first)
    fans.add(second)
    colorsbefore = dict(coloring.items())
    statebefore = Witness().capture((coloring, fans))
    coloringroots = (coloring.assignments, coloring.incident, coloring.index)
    fanroots = (
        fans.members,
        fans.spokes,
        fans.assignments,
        fans.assigned,
        fans.vertices,
        fans.types,
    )
    originalactivate = Construction.activate
    originaliterate = Fans.__iter__
    originalcompatible = Fans.compatible
    activations = 0
    iterationlocked = False

    def guardediterate(collection: Fans):
        if iterationlocked:
            raise AssertionError("Color-Small copied or scanned every fan")
        return originaliterate(collection)

    def compatible_then_lock(
        collection: Fans,
        candidate: Partial,
        vertices=None,
    ) -> None:
        nonlocal iterationlocked
        originalcompatible(collection, candidate, vertices)
        iterationlocked = True

    def fail_after_second_activation(
        strategy: type[Construction],
        candidate: Partial,
        collection: Fans,
        fan: Fan,
        journal: ColorJournal | None = None,
    ) -> tuple[int, int]:
        nonlocal activations
        edge = originalactivate(candidate, collection, fan, journal)
        activations += 1
        if activations == 2:
            raise RuntimeError("injected Color-Small failure after activation")
        return edge

    monkeypatch.setattr(
        Construction, "activate", classmethod(fail_after_second_activation)
    )
    monkeypatch.setattr(Fans, "__iter__", guardediterate)
    monkeypatch.setattr(Fans, "compatible", compatible_then_lock)

    with pytest.raises(RuntimeError, match="could not activate valid fan"):
        Construction.small(coloring, fans)

    iterationlocked = False
    assert activations == 2
    assert dict(coloring.items()) == colorsbefore
    assert fans.journal is None
    assert Witness().capture((coloring, fans)) == statebefore
    assert fans.members == {first, second}
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            coloringroots,
            strict=True,
        )
    )
    assert all(
        current is original
        for current, original in zip(
            (
                fans.members,
                fans.spokes,
                fans.assignments,
                fans.assigned,
                fans.vertices,
                fans.types,
            ),
            fanroots,
            strict=True,
        )
    )
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_fan_repair_checks_only_fans_at_changed_vertices() -> None:
    class CountedFans(Fans):
        def __init__(self) -> None:
            super().__init__()
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    graph = Adjacency(6)
    for edge in ((0, 1), (0, 2), (3, 4), (3, 5)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    first = Fan(0, 1, 2, 0, 1, 1)
    second = Fan(3, 4, 5, 0, 1, 1)
    fans = CountedFans()
    fans.add(first)
    fans.add(second)
    coloring.assign((0, 1), 2)

    removed = fans.repair(coloring, (0, 1))

    assert removed == 1
    assert first not in fans.members
    assert second in fans.members
    assert fans.iterations == 0
    fans.validate()


def test_fan_local_certificate_detects_corrupt_touched_assignment() -> None:
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 1, 1)
    fans.add(fan)
    fans.assignments[(0, 0)] = Fan(3, 4, 5, 2, 3, 3)

    with pytest.raises(AssertionError, match="u-fan index certificate"):
        fans.certify((0,))


def test_pruning_blocked_mapping_combines_fan_and_active_center_colors() -> None:
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 1, 1)
    fans.add(fan)

    blocked = Pruning.blocked(fans, (Spoke((3, 4), 2),))

    assert blocked[0] == {0}
    assert blocked[1] == {1}
    assert blocked[2] == {1}
    assert blocked[3] == {2}
    assert dict(blocked) == {0: {0}, 1: {1}, 2: {1}, 3: {2}}


def test_pruning_reduce_uses_local_audits_between_full_boundaries() -> None:
    class CountedFans(Fans):
        def __init__(self) -> None:
            super().__init__()
            self.iterations = 0
            self.validations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

        def validate(self) -> None:
            self.validations += 1
            super().validate()

    fan_count = 24
    update_count = 8
    edge_start = 3 * fan_count
    graph = Adjacency(edge_start + 2 * update_count)
    fans = CountedFans()
    for index in range(fan_count):
        center = 3 * index
        graph.add_edge(center, center + 1)
        graph.add_edge(center, center + 2)
        fans.add(Fan(center, center + 1, center + 2, 0, 1, 1))
    uedges = []
    for index in range(update_count):
        edge = (edge_start + 2 * index, edge_start + 2 * index + 1)
        graph.add_edge(*edge)
        uedges.append(Spoke(edge, 0))
    coloring = Partial(graph, 3)

    extended = Pruning.reduce(coloring, fans, tuple(uedges))

    assert extended == update_count
    assert all(item.edge in coloring for item in uedges)
    assert fans.iterations == 2
    assert fans.validations == 2
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_color_small_activates_deterministic_common_type() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(1, 3)
    coloring = Partial(graph, 2)
    coloring.assign((1, 3), 0)
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 1, 1)
    fans.add(fan)

    assert Construction.small(coloring, fans) == 1
    assert coloring[(0, 1)] == 0
    assert len(fans) == 0
    assert fans.journal is None


def test_color_small_repairs_fans_locally_across_many_components() -> None:
    class CountedFans(Fans):
        def __init__(self) -> None:
            super().__init__()
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    count = 48
    graph = Adjacency(4 * count)
    coloring = Partial(graph, 2)
    fans = CountedFans()
    for index in range(count):
        center = 4 * index
        leaf = center + 1
        second = center + 2
        tail = center + 3
        graph.add_edge(center, leaf)
        graph.add_edge(center, second)
        graph.add_edge(leaf, tail)
        coloring.assign((leaf, tail), 0)
        fans.add(Fan(center, leaf, second, 0, 1, 1))

    extended = Construction.small(coloring, fans)

    assert extended == count
    assert not fans
    assert fans.iterations <= 4
    coloring.validate()
    fans.validate()


def test_collect_direct_fans_uses_only_supplied_uncolored_edges() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(0, 3)
    coloring = Partial(graph, 3)

    fans = Construction.direct(coloring, {(0, 1), (0, 2), (0, 3)})

    fans.validate()
    assert len(fans) == 1
    assert next(iter(fans)).edges == {(0, 1), (0, 2)}


def test_collect_separable_fans_uses_witness_shifts_for_remaining_edges() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 3)
    coloring.assign((0, 2), 1)

    fans = Construction.collect(coloring, {(0, 1)})

    assert len(fans) == 1
    assert next(iter(fans)).edges == {(0, 1), (0, 2)}
    assert (0, 2) not in coloring
    coloring.validate()
    fans.validate()


def test_collect_separable_fans_extends_when_no_shift_is_available() -> None:
    graph = Adjacency(2)
    graph.add_edge(0, 1)
    coloring = Partial(graph, 2)

    fans = Construction.collect(coloring, {(0, 1)})

    assert len(fans) == 0
    assert coloring[(0, 1)] == 0
    coloring.validate()


def test_construct_u_fans_prunes_intersecting_vizing_fans() -> None:
    graph = Adjacency(8)
    for edge in (
        (0, 1),
        (0, 4),
        (1, 5),
        (2, 3),
        (2, 4),
        (3, 6),
        (3, 7),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((0, 4), 1)
    coloring.assign((1, 5), 0)
    coloring.assign((2, 4), 2)
    coloring.assign((3, 6), 0)
    coloring.assign((3, 7), 1)

    fans = Pruning.construct(coloring, {(0, 1), (2, 3)})

    assert len(fans) == 1
    fan = next(iter(fans))
    assert fan.center == 4
    assert fan.edges == {(0, 4), (2, 4)}
    assert coloring[(0, 1)] == 1
    assert coloring[(2, 3)] == 2
    coloring.validate()
    fans.compatible(coloring)


def test_construct_u_fans_reduces_multiple_collisions_and_chain_flips() -> None:
    graph = Adjacency(16)
    for edge in (
        (0, 1),
        (0, 4),
        (1, 5),
        (2, 3),
        (2, 4),
        (3, 6),
        (6, 7),
        (6, 10),
        (7, 11),
        (8, 9),
        (8, 10),
        (9, 12),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    for edge, color in (
        ((0, 4), 1),
        ((1, 5), 0),
        ((2, 4), 2),
        ((3, 6), 0),
        ((6, 10), 1),
        ((7, 11), 0),
        ((8, 10), 2),
        ((9, 12), 0),
    ):
        coloring.assign(edge, color)

    fans = Pruning.construct(coloring, {(0, 1), (2, 3), (6, 7), (8, 9)})

    assert dict(coloring.items()) == {
        (0, 1): 1,
        (0, 4): 0,
        (1, 5): 0,
        (2, 3): 1,
        (2, 4): 2,
        (3, 6): 2,
        (6, 7): 1,
        (6, 10): 0,
        (7, 11): 0,
        (8, 9): 1,
        (8, 10): 2,
        (9, 12): 0,
    }
    assert set(coloring.edges()) == set(graph.edges())
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)
    assert not fans


def test_prune_vizing_fans_rolls_back_coloring_and_fans_on_failed_precondition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(8)
    for edge in (
        (0, 1),
        (0, 4),
        (1, 5),
        (2, 3),
        (2, 4),
        (3, 6),
        (3, 7),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    for edge, color in (
        ((0, 4), 1),
        ((1, 5), 0),
        ((2, 4), 2),
        ((3, 6), 0),
        ((3, 7), 1),
    ):
        coloring.assign(edge, color)
    fans = Fans()
    before_colors = dict(coloring.items())
    before_fans = tuple(fans)
    witness = Witness()
    before = witness.capture((coloring, fans))

    real_rotate = Pruning.expose
    rotations = 0

    def fail_after_collision(*args: object, **kwargs: object) -> None:
        nonlocal rotations
        rotations += 1
        if rotations == 2:
            raise RuntimeError("failed pruning precondition")
        real_rotate(*args, **kwargs)

    monkeypatch.setattr(Pruning, "expose", fail_after_collision)
    with pytest.raises(RuntimeError, match="failed pruning precondition"):
        Pruning.prune(
            coloring,
            fans,
            (Spoke((0, 1), 0), Spoke((2, 3), 0)),
        )

    assert dict(coloring.items()) == before_colors
    assert tuple(fans) == before_fans
    assert witness.capture((coloring, fans)) == before
    coloring.validate()
    fans.validate()


def test_prune_rolls_back_touched_spokes_and_added_fan_without_root_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(11)
    for edge in (
        (0, 1),
        (0, 4),
        (1, 5),
        (2, 3),
        (2, 4),
        (3, 6),
        (3, 7),
        (8, 9),
        (8, 10),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    for edge, color in (
        ((0, 4), 1),
        ((1, 5), 0),
        ((2, 4), 2),
        ((3, 6), 0),
        ((3, 7), 1),
    ):
        coloring.assign(edge, color)
    fans = Fans()
    sentinel = Fan(8, 9, 10, 0, 1, 1)
    fans.add(sentinel)
    assignments = dict(coloring.items())
    coloringroots = (coloring.assignments, coloring.incident, coloring.index)
    fanroots = (
        fans.members,
        fans.spokes,
        fans.assignments,
        fans.assigned,
        fans.vertices,
        fans.types,
    )
    originaladd = fans.add

    def fail_after_add(fan: Fan) -> None:
        originaladd(fan)
        raise RuntimeError("injected post-add pruning failure")

    monkeypatch.setattr(fans, "add", fail_after_add)

    with pytest.raises(RuntimeError, match="injected post-add pruning failure"):
        Pruning.prune(
            coloring,
            fans,
            (Spoke((0, 1), 0), Spoke((2, 3), 0)),
        )

    assert dict(coloring.items()) == assignments
    assert fans.members == {sentinel}
    assert fans.find(8, 0) is sentinel
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            coloringroots,
            strict=True,
        )
    )
    assert all(
        current is original
        for current, original in zip(
            (
                fans.members,
                fans.spokes,
                fans.assignments,
                fans.assigned,
                fans.vertices,
                fans.types,
            ),
            fanroots,
            strict=True,
        )
    )
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_construct_rolls_back_completed_inner_reduction_from_edge_journal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(2)
    graph.add_edge(0, 1)
    coloring = Partial(graph, 2)
    roots = (coloring.assignments, coloring.incident, coloring.index)
    originalreduce = Pruning.reduce

    def fail_after_reduce(
        cls: type[Pruning],
        coloring: Partial,
        fans: Fans,
        uedges: tuple[Spoke, ...],
        *,
        journal: ColorJournal | None = None,
    ) -> int:
        originalreduce(coloring, fans, uedges, journal=journal)
        raise RuntimeError("injected enclosing construction failure")

    monkeypatch.setattr(Pruning, "reduce", classmethod(fail_after_reduce))

    with pytest.raises(RuntimeError, match="enclosing construction failure"):
        Pruning.construct(coloring, {(0, 1)})

    assert not coloring.assignments
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            roots,
            strict=True,
        )
    )
    coloring.validate()


def test_vizing_chain_exploration_detects_oriented_collisions() -> None:
    first = Chain(
        Spoke((0, 1), 0),
        (1,),
        (0, 2, 3),
    )
    samedirection = Chain(
        Spoke((4, 5), 0),
        (5,),
        (4, 2, 3),
    )
    opposite_direction = Chain(
        Spoke((6, 7), 0),
        (7,),
        (3, 2, 8),
    )

    same_event = Vizing.explore((first, samedirection))
    opposite_event = Vizing.explore((first, opposite_direction))

    assert isinstance(same_event, Event)
    assert same_event.collision == (first, samedirection)
    assert opposite_event.collision in {
        (first, opposite_direction),
        (opposite_direction, first),
    }


def test_vizing_resolves_opposite_direction_collision_to_complete_coloring():
    graph = Adjacency(6)
    for edge in ((0, 1), (2, 3), (4, 5)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 2)
    coloring.assign((0, 1), 0)
    first = Chain(Spoke((2, 3), 1), (3,), (0, 1), (0,))
    second = Chain(Spoke((4, 5), 1), (5,), (1, 0), (0,))
    fans = Fans()

    assert Vizing.resolve(coloring, fans, (first, second)) == (True, 2)
    assert dict(coloring.items()) == {(2, 3): 0, (4, 5): 0}
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)
    assert (0, 1) not in coloring
    completed = Paper.complete(coloring, set(graph.edges()), 1)
    Paper.certify(graph, 1, set(graph.edges()), completed)


def test_built_vizing_chains_resolve_a_real_shared_alternating_edge():
    graph = Adjacency(12)
    for edge in (
        (0, 1),
        (1, 2),
        (2, 3),
        (0, 4),
        (3, 5),
        (0, 6),
        (3, 7),
        (6, 8),
        (7, 9),
        (4, 10),
        (5, 11),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    for edge, color in (
        ((0, 1), 1),
        ((1, 2), 0),
        ((2, 3), 1),
        ((0, 4), 2),
        ((3, 5), 2),
        ((6, 8), 0),
        ((7, 9), 0),
        ((4, 10), 0),
        ((5, 11), 0),
    ):
        coloring.assign(edge, color)
    chains = tuple(Vizing.build(coloring, Spoke(edge, 0)) for edge in ((0, 6), (3, 7)))
    event = Vizing.explore(chains)
    assert event.terminal is None and event.collision is not None
    assert set(chains[0].edges) & set(chains[1].edges) == {
        (0, 1),
        (1, 2),
        (2, 3),
    }
    assert (1, 2) in coloring

    resolved, progress = Vizing.resolve(coloring, Fans(), event.collision)
    assert resolved and progress == 2
    coloring.validate()
    assert all(edge in coloring for edge in ((0, 6), (3, 7)))


def test_pruning_reduces_real_collision_inside_the_enclosing_construction():
    graph = Adjacency(24)
    coloring = Partial(graph, 3)
    edges = (
        (0, 1, 1),
        (1, 2, 0),
        (2, 3, 1),
        (0, 4, 2),
        (3, 5, 2),
        (6, 8, 0),
        (7, 9, 0),
        (4, 10, 0),
        (5, 11, 0),
    )
    pending = set()
    for offset in (0, 12):
        for left, right, color in edges:
            edge = (offset + left, offset + right)
            graph.add_edge(*edge)
            coloring.assign(edge, color)
        for edge in ((offset, offset + 6), (offset + 3, offset + 7)):
            graph.add_edge(*edge)
            pending.add(edge)

    class Routing(Pruning):
        collisions = 0

        class Oracle(Vizing):
            @classmethod
            def resolve(cls, coloring, fans, collision):
                Routing.collisions += 1
                return super().resolve(coloring, fans, collision)

        vizing = Oracle

    fans = Routing.construct(coloring, pending)
    assert Routing.collisions == 2
    covered = {spoke for fan in fans for spoke in fan.edges}
    assert all(edge in coloring or edge in covered for edge in pending)
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)
    complete = Paper.complete(coloring, set(graph.edges()), 2)
    Paper.certify(graph, 2, set(graph.edges()), complete)


def test_vizing_collision_failure_restores_color_and_every_fan_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(12)
    for edge in ((0, 1), (2, 3), (4, 5), (6, 7), (6, 8)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((0, 1), 0)
    fans = Fans()
    sentinel = Fan(6, 7, 8, 1, 2, 2)
    fans.add(sentinel)
    first = Chain(Spoke((2, 3), 1), (3,), (0, 1), (0,))
    second = Chain(Spoke((4, 5), 1), (5,), (1, 0), (0,))
    before = Witness().capture((coloring, fans))
    coloringroots = (coloring.assignments, coloring.incident, coloring.index)
    fanroots = (
        fans.members,
        fans.spokes,
        fans.assignments,
        fans.assigned,
        fans.vertices,
        fans.types,
    )
    activate = Vizing.activate
    calls = 0

    def fail_second(coloring, chain):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second-chain activation failure")
        return activate(coloring, chain)

    monkeypatch.setattr(Vizing, "activate", fail_second)
    assert Vizing.resolve(coloring, fans, (first, second)) == (False, 0)
    assert calls == 2
    assert Witness().capture((coloring, fans)) == before
    assert tuple(fans) == (sentinel,)
    assert fans.assignments[(6, 1)] is sentinel
    assert fans.assigned[6] == {1}
    assert fans.vertices[6] == {sentinel}
    assert fans.types[sentinel.type] == {sentinel}
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            coloringroots,
            strict=True,
        )
    )
    assert all(
        current is original
        for current, original in zip(
            (
                fans.members,
                fans.spokes,
                fans.assignments,
                fans.assigned,
                fans.vertices,
                fans.types,
            ),
            fanroots,
            strict=True,
        )
    )
    coloring.validate()
    fans.validate()


def test_same_direction_collision_failure_restores_first_predecessor_edit():
    graph = Adjacency(10)
    for edge in (
        (0, 1),
        (1, 2),
        (1, 3),
        (4, 5),
        (6, 7),
        (8, 9),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((0, 1), 2)
    fans = Fans()
    sentinel = Fan(8, 9, 7, 0, 1, 1)
    fans.add(sentinel)
    first = Chain(Spoke((4, 5), 0), (5,), (0, 1, 2), (1,))
    second = Chain(Spoke((6, 7), 0), (7,), (3, 1, 2), (1,))
    before = Witness().capture((coloring, fans))

    assert Vizing.resolve(coloring, fans, (first, second)) == (False, 0)
    assert Witness().capture((coloring, fans)) == before
    assert fans.assignments[(8, 0)] is sentinel
    assert fans.assigned[8] == {0}
    assert fans.vertices[8] == {sentinel}
    assert fans.types[sentinel.type] == {sentinel}
    coloring.validate()
    fans.validate()


def test_same_direction_collision_shifts_both_spokes_and_adds_compatible_fan():
    graph = Adjacency(8)
    for edge in ((0, 1), (1, 2), (1, 3), (4, 5), (6, 7)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((0, 1), 2)
    coloring.assign((1, 3), 0)
    first = Chain(Spoke((4, 5), 0), (5,), (0, 1, 2), (1,))
    second = Chain(Spoke((6, 7), 0), (7,), (3, 1, 2), (1,))
    fans = Fans()

    assert Vizing.resolve(coloring, fans, (first, second)) == (True, 2)
    assert dict(coloring.items()) == {(4, 5): 1, (6, 7): 1}
    expected = Fan(1, 0, 3, 2, 0, 0)
    assert tuple(fans) == (expected,)
    fans.compatible(coloring)
    coloring.validate()
    fans.validate()


def test_vizing_collision_rolls_back_only_touched_state_after_fan_add_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(11)
    for edge in ((0, 1), (1, 2), (1, 3), (4, 5), (6, 7), (8, 9), (8, 10)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((0, 1), 2)
    coloring.assign((1, 3), 0)
    fans = Fans()
    sentinel = Fan(8, 9, 10, 0, 1, 1)
    fans.add(sentinel)
    first = Chain(Spoke((4, 5), 0), (5,), (0, 1, 2), (1,))
    second = Chain(Spoke((6, 7), 0), (7,), (3, 1, 2), (1,))
    expected = Fan(1, 0, 3, 2, 0, 0)
    coloringroots = (coloring.assignments, coloring.incident, coloring.index)
    fanroots = (
        fans.members,
        fans.spokes,
        fans.assignments,
        fans.assigned,
        fans.vertices,
        fans.types,
    )
    assignments = dict(coloring.items())
    originaladd = fans.add

    def fail_after_add(fan: Fan) -> None:
        originaladd(fan)
        if fan == expected:
            raise RuntimeError("injected post-add collision failure")

    monkeypatch.setattr(fans, "add", fail_after_add)

    assert Vizing.resolve(coloring, fans, (first, second)) == (False, 0)

    assert dict(coloring.items()) == assignments
    assert fans.members == {sentinel}
    assert fans.find(8, 0) is sentinel
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            coloringroots,
            strict=True,
        )
    )
    assert all(
        current is original
        for current, original in zip(
            (
                fans.members,
                fans.spokes,
                fans.assignments,
                fans.assigned,
                fans.vertices,
                fans.types,
            ),
            fanroots,
            strict=True,
        )
    )
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_paper_vizing_activation_handles_trivial_fan() -> None:
    graph = Adjacency(2)
    graph.add_edge(0, 1)
    coloring = Partial(graph, 2)
    chain = Vizing.build(coloring, Spoke((0, 1), 0))

    assert chain.path == ()
    assert Vizing.activate(coloring, chain) == (0, 1)
    assert coloring[(0, 1)] == 0
    coloring.validate()


def test_paper_vizing_activation_flips_nontrivial_chain() -> None:
    graph = Adjacency(8)
    for edge in (
        (0, 1),
        (0, 2),
        (0, 3),
        (1, 4),
        (2, 5),
        (3, 7),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 3)
    coloring.assign((1, 4), 0)
    coloring.assign((0, 2), 1)
    coloring.assign((2, 5), 0)
    coloring.assign((0, 3), 2)
    coloring.assign((3, 7), 0)
    chain = Vizing.build(coloring, Spoke((0, 1), 0))

    assert chain.leaves == (1, 2, 3)
    assert chain.colors == (1, 2, 1)
    assert chain.path == (0, 2, 5)
    assert Vizing.activate(coloring, chain) == (0, 1)
    assert coloring[(0, 1)] == 1
    assert coloring[(0, 2)] == 0
    assert coloring[(2, 5)] == 1
    coloring.validate()


def test_extend_recursive_uses_small_base_case_without_copying_edge_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(1, 3)
    coloring = Partial(graph, 2)
    coloring.assign((1, 3), 0)
    fans = Fans()
    fans.add(Fan(0, 1, 2, 0, 1, 1))

    def reject_edge_copy(candidate: Partial) -> set[tuple[int, int]]:
        raise AssertionError("Extend must not materialize all colored edge keys")

    monkeypatch.setattr(Partial, "edges", reject_edge_copy)

    assert Extension.extend(coloring, fans, 10) == 1
    coloring.validate()
    assert coloring[(0, 1)] == 0


def test_extend_recursive_synchronizes_parent_fans_after_child_coloring() -> None:
    count = 100
    graph = Adjacency(3 * count)
    fans = Fans()
    for index in range(count):
        center = 3 * index
        graph.add_edge(center, center + 1)
        graph.add_edge(center, center + 2)
        fans.add(Fan(center, center + 1, center + 2, 0, 10, 10))

    coloring = Partial(graph, 200)
    assert Extension.extend(coloring, fans, 10) == count
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)
    assert len(coloring.edges()) == count
    assert not fans


def test_extend_projects_disjoint_color_groups_without_scope_overlap() -> None:
    class Partitioned:
        @classmethod
        def sparsify(
            cls: type[Partitioned], coloring: Partial, fans: Fans, eta: int
        ) -> tuple[tuple[frozenset[int], ...], Fans]:
            return (frozenset({0, 1}), frozenset({2, 3})), fans

    class Grouped(Extension):
        spectrum = Partitioned

    graph = Adjacency(6)
    for edge in ((0, 1), (0, 2), (3, 4), (3, 5)):
        graph.add_edge(*edge)
    fans = Fans()
    fans.add(Fan(0, 1, 2, 0, 1, 1))
    fans.add(Fan(3, 4, 5, 2, 3, 3))
    coloring = Partial(graph, 200)

    assert Grouped.extend(coloring, fans, 10) == 2

    assert len(coloring.assignments) == 2
    assert not fans
    coloring.validate()


def test_extend_rejects_overlapping_color_group_contract() -> None:
    class Overlapping:
        @classmethod
        def sparsify(
            cls: type[Overlapping],
            coloring: Partial,
            fans: Fans,
            eta: int,
        ) -> tuple[tuple[frozenset[int], ...], Fans]:
            return (frozenset({0, 1}), frozenset({1, 2})), fans

    class Guarded(Extension):
        spectrum = Overlapping

    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 200)
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 1, 1)
    fans.add(fan)

    with pytest.raises(RuntimeError, match="overlapping color groups"):
        Guarded.extend(coloring, fans, 10)

    assert fans.members == {fan}
    assert not coloring.assignments
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_color_blocks_are_ordered_and_disjoint() -> None:
    blocks, pairs = Spectrum.blocks(100, 10)

    assert len(blocks) == 20
    assert len(pairs) == 10
    assert all(len(block) == 5 for block in blocks)
    assert set().union(*blocks) == set(range(100))
    assert all(len(pair) == 10 for pair in pairs)


@pytest.mark.parametrize("palette", [0, -1, True, 100.0])
def test_color_blocks_rejects_invalid_palette_sizes(palette: object) -> None:
    with pytest.raises(ValueError, match="palette"):
        Spectrum.blocks(palette, 10)  # type: ignore[arg-type]


def test_type_sparsification_certificate_is_deterministic_and_non_mutating() -> None:
    graph = Adjacency(4)
    graph.add_edge(0, 1)
    graph.add_edge(2, 3)
    coloring = Partial(graph, 4)
    coloring.assign((0, 1), 0)
    before = dict(coloring.items())

    first = Spectrum.classify(coloring, {(2, 3)}, 2)
    second = Spectrum.classify(coloring, {(2, 3)}, 2)

    assert first == second
    assert first.blocks == (frozenset({0, 1}), frozenset({2, 3}))
    assert first.diagonal == {(2, 3)}
    assert first.fraction == 1.0
    assert dict(coloring.items()) == before
    with pytest.raises(TypeError):
        first.types[(2, 3)] = frozenset()  # type: ignore[index]


def test_type_sparsification_rejects_non_matching_uncolored_edges() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(1, 2)
    coloring = Partial(graph, 2)

    with pytest.raises(ValueError, match="matching"):
        Spectrum.classify(coloring, {(0, 1), (1, 2)}, 2)


def test_relevant_paths_use_matching_color_offsets() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 100)
    fan = Fan(0, 1, 2, 0, 10, 10)
    blocks, ignored = Spectrum.blocks(100, 10)

    assert not Spectrum.social(fan, blocks)
    paths = Spectrum.paths(coloring, fan, blocks, 1)

    assert [path for path, ignored, unused in paths] == [(0,), (1,), (2,)]
    assert [source for ignored, source, unused in paths] == [0, 10, 10]
    assert [target for ignored, unused, target in paths] == [15, 10, 10]


def test_sparsify_types_relabels_small_collection_deterministically() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 100)
    fans = Fans()
    fans.add(Fan(0, 1, 2, 0, 10, 10))

    groups, social = Spectrum.sparsify(coloring, fans, 10)

    assert len(groups) == 10
    assert len(social) == 1
    assert tuple(fans) == tuple(social)
    assert next(iter(social)).type == frozenset({0, 1})


def test_modify_types_flips_one_batch_and_reindexes_fans() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 100)
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 10, 10)
    fans.add(fan)
    blocks, ignored = Spectrum.blocks(100, 10)

    Spectrum.modify(coloring, fans, (fan,), blocks, 0)

    assert len(fans) == 1
    transformed = next(iter(fans))
    assert transformed.type == frozenset({0, 5})
    assert Spectrum.social(transformed, blocks)
    coloring.validate()
    fans.validate()


def test_modify_types_batch_membership_does_not_rescan_all_fans() -> None:
    class CountedFans(Fans):
        def __init__(self) -> None:
            super().__init__()
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    count = 64
    graph = Adjacency(3 * count)
    fans = CountedFans()
    for index in range(count):
        center = 3 * index
        graph.add_edge(center, center + 1)
        graph.add_edge(center, center + 2)
        fans.add(Fan(center, center + 1, center + 2, 0, 10, 10))
    coloring = Partial(graph, 100)
    blocks, ignored = Spectrum.blocks(100, 10)

    Spectrum.modify(coloring, fans, tuple(fans), blocks, 0)

    assert len(fans) == count
    assert fans.iterations <= 8
    assert all(Spectrum.social(fan, blocks) for fan in fans)
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_modify_types_does_not_rescan_unrelated_fans_after_local_flip() -> None:
    class CountedFans(Fans):
        def __init__(self) -> None:
            super().__init__()
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    count = 128
    graph = Adjacency(3 * count)
    fans = CountedFans()
    for index in range(count):
        center = 3 * index
        graph.add_edge(center, center + 1)
        graph.add_edge(center, center + 2)
        fans.add(Fan(center, center + 1, center + 2, 0, 10, 10))
    coloring = Partial(graph, 100)
    blocks, ignored = Spectrum.blocks(100, 10)
    selected = Fan(0, 1, 2, 0, 10, 10)

    Spectrum.modify(coloring, fans, (selected,), blocks, 0)

    # The two whole-collection passes are the entry and exit compatibility
    # certificates. The mutation sweep must use affected-vertex fan rows.
    assert fans.iterations == 2
    assert len(fans) == count
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_modify_types_rejects_mixed_fan_block_batches() -> None:
    graph = Adjacency(6)
    for edge in ((0, 1), (0, 2), (3, 4), (3, 5)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 100)
    fans = Fans()
    first = Fan(0, 1, 2, 0, 10, 10)
    second = Fan(3, 4, 5, 0, 20, 20)
    fans.add(first)
    fans.add(second)
    blocks, ignored = Spectrum.blocks(100, 10)

    with pytest.raises(ValueError, match="one fan block type"):
        Spectrum.modify(coloring, fans, (first, second), blocks, 0)

    assert tuple(fans) == (first, second)
    assert not coloring.edges()


def test_modify_types_flips_nontrivial_relevant_paths() -> None:
    graph = Adjacency(7)
    for edge in ((0, 1), (0, 2), (1, 3), (3, 4), (2, 5), (5, 6)):
        graph.add_edge(*edge)
    coloring = Partial(graph, 100)
    coloring.assign((1, 3), 5)
    coloring.assign((3, 4), 10)
    coloring.assign((2, 5), 5)
    coloring.assign((5, 6), 10)
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 10, 10)
    fans.add(fan)
    blocks, ignored = Spectrum.blocks(100, 10)

    Spectrum.modify(coloring, fans, (fan,), blocks, 0)

    assert coloring[(1, 3)] == 10
    assert coloring[(3, 4)] == 5
    assert coloring[(2, 5)] == 10
    assert coloring[(5, 6)] == 5
    transformed = next(iter(fans))
    assert transformed.type == frozenset({0, 5})
    assert Spectrum.social(transformed, blocks)
    coloring.validate()
    fans.validate()


def test_modify_types_restores_state_on_explicit_failure() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 100)
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 10, 10)
    fans.add(fan)
    blocks, ignored = Spectrum.blocks(100, 10)
    colorsbefore = dict(coloring.items())
    fansbefore = tuple(fans)

    with pytest.raises(IndexError):
        Spectrum.modify(coloring, fans, (fan,), blocks, 10)

    assert dict(coloring.items()) == colorsbefore
    assert tuple(fans) == fansbefore
    coloring.validate()
    fans.validate()


def test_modify_types_rolls_back_only_path_coloring_and_affected_fans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Adjacency(10)
    for edge in (
        (0, 1),
        (0, 2),
        (1, 3),
        (3, 4),
        (2, 5),
        (5, 6),
        (7, 8),
        (7, 9),
    ):
        graph.add_edge(*edge)
    coloring = Partial(graph, 100)
    for edge, color in (
        ((1, 3), 5),
        ((3, 4), 10),
        ((2, 5), 5),
        ((5, 6), 10),
    ):
        coloring.assign(edge, color)
    fans = Fans()
    fan = Fan(0, 1, 2, 0, 10, 10)
    sentinel = Fan(7, 8, 9, 0, 10, 10)
    fans.add(fan)
    fans.add(sentinel)
    blocks, ignored = Spectrum.blocks(100, 10)
    assignments = dict(coloring.items())
    coloringroots = (coloring.assignments, coloring.incident, coloring.index)
    fanroots = (
        fans.members,
        fans.spokes,
        fans.assignments,
        fans.assigned,
        fans.vertices,
        fans.types,
    )
    originaladd = fans.add
    failed = False

    def fail_after_replacement(fan: Fan) -> None:
        nonlocal failed
        originaladd(fan)
        if fan.vertices == (0, 1, 2) and fan.type == frozenset({0, 5}):
            failed = True
            raise RuntimeError("injected post-replacement Modify-Types failure")

    monkeypatch.setattr(fans, "add", fail_after_replacement)

    with pytest.raises(RuntimeError, match="post-replacement Modify-Types failure"):
        Spectrum.modify(coloring, fans, (fan,), blocks, 0)

    assert failed
    assert dict(coloring.items()) == assignments
    assert fans.members == {fan, sentinel}
    assert fans.find(7, 0) is sentinel
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            coloringroots,
            strict=True,
        )
    )
    assert all(
        current is original
        for current, original in zip(
            (
                fans.members,
                fans.spokes,
                fans.assignments,
                fans.assigned,
                fans.vertices,
                fans.types,
            ),
            fanroots,
            strict=True,
        )
    )
    coloring.validate()
    fans.validate()
    fans.compatible(coloring)


def test_sparsify_types_socializes_a_full_deterministic_batch() -> None:
    fan_count = 100
    graph = Adjacency(3 * fan_count)
    fans = Fans()
    for index in range(fan_count):
        center = 3 * index
        first = center + 1
        second = center + 2
        graph.add_edge(center, first)
        graph.add_edge(center, second)
        fans.add(Fan(center, first, second, 0, 10, 10))
    coloring = Partial(graph, 100)

    groups, social = Spectrum.sparsify(coloring, fans, 10)

    assert len(groups) == 10
    assert len(social) == fan_count
    assert all(Spectrum.social(fan, Spectrum.blocks(100, 10)[0]) for fan in social)
    coloring.validate()


def test_sparsify_types_preserves_invariants_on_cross_block_batches() -> None:
    blocks, ignored = Spectrum.blocks(100, 10)
    for seed in range(5):
        rng = random.Random(seed)
        fan_count = 120
        graph = Adjacency(3 * fan_count)
        fans = Fans()
        for index in range(fan_count):
            center = 3 * index
            graph.add_edge(center, center + 1)
            graph.add_edge(center, center + 2)
            alpha = rng.randrange(100)
            leafcolor = rng.randrange(100)
            if alpha == leafcolor:
                leafcolor = (leafcolor + 1) % 100
            fans.add(
                Fan(
                    center,
                    center + 1,
                    center + 2,
                    alpha,
                    leafcolor,
                    leafcolor,
                )
            )
        coloring = Partial(graph, 100)
        coloredbefore = coloring.edges()

        ignored, social = Spectrum.sparsify(coloring, fans, 10)

        assert len(social) >= 2
        assert all(Spectrum.social(fan, blocks) for fan in social)
        assert coloring.edges() == coloredbefore
        coloring.validate()
        social.validate()


def test_sparsify_types_restores_state_on_batch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    fan_count = 100
    graph = Adjacency(3 * fan_count)
    fans = Fans()
    for index in range(fan_count):
        center = 3 * index
        graph.add_edge(center, center + 1)
        graph.add_edge(center, center + 2)
        low = index % 50
        high = low + 50
        fans.add(Fan(center, center + 1, center + 2, low, high, high))
    coloring = Partial(graph, 100)
    colorsbefore = dict(coloring.items())
    fansbefore = tuple(fans)
    coloringroots = (coloring.assignments, coloring.incident, coloring.index)
    fanroots = (
        fans.members,
        fans.spokes,
        fans.assignments,
        fans.assigned,
        fans.vertices,
        fans.types,
    )
    originalmodify = Spectrum.modify
    batches = 0

    def fail_batch(
        strategy: type[Spectrum],
        candidate: Partial,
        collection: Fans,
        batch: tuple[Fan, ...],
        blocks: tuple[frozenset[int], ...],
        pairindex: int,
        parentjournal: ColorJournal | None = None,
    ) -> None:
        nonlocal batches
        originalmodify(candidate, collection, batch, blocks, pairindex, parentjournal)
        batches += 1
        raise RuntimeError("injected sparsification failure")

    monkeypatch.setattr(Spectrum, "modify", classmethod(fail_batch))
    with pytest.raises(RuntimeError, match="injected sparsification failure"):
        Spectrum.sparsify(coloring, fans, 10)

    assert batches == 1
    assert dict(coloring.items()) == colorsbefore
    assert tuple(fans) == fansbefore
    assert all(
        current is original
        for current, original in zip(
            (coloring.assignments, coloring.incident, coloring.index),
            coloringroots,
            strict=True,
        )
    )
    assert all(
        current is original
        for current, original in zip(
            (
                fans.members,
                fans.spokes,
                fans.assignments,
                fans.assigned,
                fans.vertices,
                fans.types,
            ),
            fanroots,
            strict=True,
        )
    )
    coloring.validate()
    fans.validate()


def test_shift_edge_to_fan_preserves_partial_coloring() -> None:
    graph = Adjacency(3)
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    coloring = Partial(graph, 3)
    coloring.assign((0, 2), 1)
    fans = Fans()

    fan = Construction.shift(coloring, (0, 1), fans)

    assert fan == Fan(0, 1, 2, 0, 1, 1)
    assert (0, 2) not in coloring
    fans.validate()


def test_paper_fan_colorer_colors_complete_graphs() -> None:
    for n in range(0, 9):
        graph = Adjacency(n)
        for left in range(n):
            for right in range(left + 1, n):
                graph.add_edge(left, right)
        coloring = Paper().color(graph, max(0, n - 1))
        assert set(coloring) == set(graph.edges())
        for vertex in range(n):
            incident = [
                coloring[tuple(sorted((vertex, neighbor)))]
                for neighbor in graph.neighbors(vertex)
            ]
            assert len(incident) == len(set(incident))


def test_paper_fan_colorer_handles_dense_adversarial_graphs() -> None:
    for seed, probability in enumerate((0.35, 0.55, 0.75, 0.95)):
        rng = random.Random(seed)
        graph = Adjacency(40)
        for left in range(40):
            for right in range(left + 1, 40):
                if rng.random() < probability:
                    graph.add_edge(left, right)

        delta = max((graph.degree(vertex) for vertex in range(graph.n)), default=0)
        coloring = Paper().color(graph, delta)

        assert set(coloring) == set(graph.edges())
        for vertex in range(graph.n):
            incident = [
                coloring[tuple(sorted((vertex, neighbor)))]
                for neighbor in graph.neighbors(vertex)
            ]
            assert len(incident) == len(set(incident))


def test_paper_fan_colorer_is_independent_of_neighbor_iteration_order() -> None:
    class ReverseNeighbors(Adjacency):
        def neighbors(self, vertex: int):
            return iter(sorted(super().neighbors(vertex), reverse=True))

    normal = Adjacency(40)
    reverse = ReverseNeighbors(40)
    for left in range(40):
        for right in range(left + 1, 40):
            if (left * 17 + right * 31) % 7 < 3:
                normal.add_edge(left, right)
                reverse.add_edge(left, right)

    delta = max((normal.degree(vertex) for vertex in range(normal.n)), default=0)
    assert Paper().color(normal, delta) == Paper().color(reverse, delta)


def test_paper_fan_colorer_runs_extend_for_large_fan_batches() -> None:
    graph = Adjacency(201)
    for leaf in range(1, 201):
        graph.add_edge(0, leaf)

    coloring = Paper().color(graph, 200)

    assert set(coloring) == set(graph.edges())
    assert len({coloring[(0, leaf)] for leaf in range(1, 201)}) == 200


def test_paper_fan_colorer_certifies_recursive_seed_output() -> None:
    graph = Adjacency(40)
    for left in range(40):
        for right in range(left + 1, 40):
            if (left * 17 + right * 31) % 7 < 3:
                graph.add_edge(left, right)

    coloring = Paper().color(graph, 39)
    certificate = Partial(graph, 40)
    for edge, color in coloring.items():
        certificate.assign(edge, color)
    certificate.validate()


def test_sparse_pruning_input_validation_avoids_universe_and_edge_copies() -> None:
    """Paper fan intake touches supplied endpoints, not every graph vertex/edge."""

    class SparseGraph:
        n = 1_000_000

        def add_edge(self, left: Vertex, right: Vertex) -> None:
            raise AssertionError("test graph is immutable")

        def remove_edge(self, left: Vertex, right: Vertex) -> None:
            raise AssertionError("test graph is immutable")

        def has_edge(self, left: Vertex, right: Vertex) -> bool:
            return (left, right) in {(2, 9), (4, 11)}

        def degree(self, vertex: Vertex) -> int:
            return int(vertex in {2, 9, 4, 11})

        def neighbors(self, vertex: Vertex):
            if vertex == 2:
                return iter((9,))
            if vertex == 9:
                return iter((2,))
            if vertex == 4:
                return iter((11,))
            if vertex == 11:
                return iter((4,))
            return iter(())

        def edges(self):
            raise AssertionError("pruning materialized the graph edge set")

        def num_edges(self) -> int:
            return 2

    class SparsePartial(Partial):
        def edges(self) -> set[Edge]:
            raise AssertionError("pruning copied every colored edge")

    graph = SparseGraph()
    coloring = SparsePartial(graph, 4)

    assert Pruning.seed(coloring, {(2, 9)}) == (Spoke((2, 9), 0),)
    assert len(Construction.direct(coloring, {(2, 9)})) == 0
    assert len(Construction.collect(coloring, set())) == 0
    certificate = Spectrum.classify(coloring, set(), 2)
    assert certificate.diagonal == frozenset()

    with pytest.raises(ValueError, match="edges of the graph"):
        Construction.direct(coloring, {(9, 2)})
