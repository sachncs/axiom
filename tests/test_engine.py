"""Independent certificates for the explicit non-durable native matching core."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom.engine import Engine
from axiom.graph import Adjacency


class Reference:
    """Small ordered local-repair oracle, independent of native representation."""

    def __init__(self, vertices: int) -> None:
        self.graph = Adjacency(vertices)
        self.partners: dict[int, int] = {}
        self.version = 0

    def rematch(self, vertex: int) -> None:
        if vertex in self.partners:
            return
        for neighbor in self.graph.neighbors(vertex):
            if neighbor not in self.partners:
                self.partners[vertex] = neighbor
                self.partners[neighbor] = vertex
                return

    def edit(self, left: int, right: int, adding: bool) -> bool:
        left, right = min(left, right), max(left, right)
        if left == right or self.graph.has_edge(left, right) == adding:
            return False
        if adding:
            self.graph.add_edge(left, right)
            if left not in self.partners and right not in self.partners:
                self.partners[left] = right
                self.partners[right] = left
        else:
            self.graph.remove_edge(left, right)
            if self.partners.get(left) == right:
                del self.partners[left]
                del self.partners[right]
                self.rematch(left)
                self.rematch(right)
        self.version += 1
        return True


def test_bounded_degree64_checkpoint_and_full_state_rollback():
    engine = Engine(256, budget=200 << 10)
    engine.ring(32)
    for vertex in range(256):
        assert engine.partner(vertex) == vertex ^ 1
        for neighbor in range(256):
            distance = (neighbor - vertex) % 256
            assert engine.has_edge(vertex, neighbor) == (
                1 <= distance <= 32 or 224 <= distance <= 255
            )
    before = snapshot(engine)
    image = engine.snapshot()
    token = engine.begin()
    engine.delete(0, 1)
    engine.delete(80, 81)
    engine.insert(0, 80)
    assert engine.check()
    engine.rollback(token)
    assert snapshot(engine) == before
    # Undo restores logical rows/partners, not arena row order or retained capacity.
    # Both encodings must round-trip exactly and drive identical future repairs.
    candidates = []
    for encoded in (image, engine.snapshot()):
        restored = Engine.restore(encoded, budget=200 << 10)
        assert snapshot(restored) == before and restored.check()
        assert restored.snapshot() == encoded
        assert restored.memory()["allocated"] <= 200 << 10
        restored.delete(0, 1)
        restored.delete(80, 81)
        restored.insert(0, 80)
        assert restored.check()
        candidates.append(restored)
    assert snapshot(candidates[0]) == snapshot(candidates[1])


def snapshot(engine: Engine) -> tuple:
    """Read one committed graph/matching state through public query methods."""
    return (
        engine.version,
        engine.num_edges(),
        engine.size(),
        tuple(engine.partner(vertex) for vertex in range(engine.n)),
        tuple(
            (u, v)
            for u in range(engine.n)
            for v in range(u + 1, engine.n)
            if engine.has_edge(u, v)
        ),
    )


def certify(engine: Engine, reference: Reference) -> None:
    """Check exact topology, deterministic matching, and independent maximality."""
    assert engine.check()
    assert engine.version == reference.version
    assert engine.num_edges() == reference.graph.num_edges()
    assert engine.size() * 2 == len(reference.partners)
    for vertex in range(engine.n):
        partner = engine.partner(vertex)
        assert partner == reference.partners.get(vertex)
        assert engine.degree(vertex) == reference.graph.degree(vertex)
        if partner is not None:
            assert engine.partner(partner) == vertex and engine.has_edge(
                vertex, partner
            )
        for other in range(vertex + 1, engine.n):
            assert engine.has_edge(vertex, other) == reference.graph.has_edge(
                vertex, other
            )
            if engine.has_edge(vertex, other):
                assert partner is not None or engine.partner(other) is not None
    version, page, start = engine.page(limit=5)
    edges = list(page)
    while start is not None:
        current, page, start = engine.page(start, 5, version)
        assert current == version
        edges.extend(page)
    expected = {(u, v) for u, v in reference.partners.items() if u < v}
    assert set(edges) == expected and len(edges) == len(expected)


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.tuples(st.booleans(), st.integers(0, 32), st.integers(0, 32)), max_size=180
    )
)
def test_updates_match_independent_deterministic_reference(
    updates: list[tuple[bool, int, int]],
) -> None:
    engine, reference = Engine(33), Reference(33)
    for adding, u, v in updates:
        expected = reference.edit(u, v, adding)
        assert (engine.insert(u, v) if adding else engine.delete(u, v)) == expected
        assert engine.check()
    certify(engine, reference)


@pytest.mark.parametrize("n", [0, 1, 2, 33])
def test_empty_engine_and_bounded_pages(n: int) -> None:
    engine = Engine(n)
    assert engine.n == n and engine.size() == engine.num_edges() == engine.version == 0
    assert engine.check() and engine.page(n) == (0, [], None)
    assert engine.active is False and engine.poisoned is False
    for attribute in ("active", "poisoned"):
        with pytest.raises(AttributeError):
            setattr(engine, attribute, True)
    with pytest.raises(ValueError):
        engine.page(limit=4097)


def test_batch_has_no_public_topology_or_partner_visibility_until_publication() -> None:
    engine = Engine(16)
    engine.ring()
    before = snapshot(engine)
    token = engine.begin()
    assert engine.active is True and engine.poisoned is False
    assert engine.delete(0, 1)
    assert engine.insert(0, 4)
    for query in (
        lambda: engine.version,
        engine.size,
        engine.num_edges,
        lambda: engine.partner(0),
        engine.page,
        lambda: engine.has_edge(0, 1),
    ):
        with pytest.raises(RuntimeError, match="unpublished"):
            query()
    assert engine.check()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(engine.insert, 0, 5)
        with pytest.raises(RuntimeError, match="another thread"):
            future.result()
    engine.rollback(token)
    assert engine.active is False
    assert snapshot(engine) == before
    token = engine.begin()
    engine.delete(0, 1)
    engine.insert(0, 4)
    engine.commit(token)
    assert engine.version == before[0] + 2 and engine.check()
    assert engine.memory()["active"] == 0


def test_failed_native_batch_rolls_back_earlier_matching_repairs_and_can_retry() -> (
    None
):
    engine = Engine(16)
    engine.ring()
    before = snapshot(engine)
    token = engine.begin()
    engine.delete(0, 1)
    engine.insert(0, 4)
    with pytest.raises(ValueError, match="out of range"):
        engine.insert(16, 0)
    assert snapshot(engine) == before and engine.check()
    assert engine.memory()["active"] == 0
    with pytest.raises(RuntimeError, match="stale"):
        engine.commit(token)
    assert engine.delete(0, 1) and engine.check()


def test_shared_budget_rejects_partner_journal_before_any_graph_or_matching_edit() -> (
    None
):
    metadata = Engine(4).memory()["allocated"]
    engine = Engine(4, budget=metadata)
    before = snapshot(engine)
    with pytest.raises(MemoryError, match="partner journal"):
        engine.insert(0, 1)
    assert snapshot(engine) == before and engine.check()
    assert engine.memory()["active"] == 0


def test_budget_failure_rolls_back_batch_and_reuses_capacity() -> None:
    metadata = Engine(16).memory()["allocated"]
    engine = Engine(16, budget=metadata + 8 * 28 + 2 * 8 * 12)
    before = snapshot(engine)
    token = engine.begin()
    for vertex in range(1, 7):
        assert engine.insert(0, vertex)
    with pytest.raises(MemoryError):
        engine.insert(0, 7)
    assert snapshot(engine) == before and engine.check()
    assert engine.memory()["allocated"] <= engine.memory()["budget"]
    with pytest.raises(RuntimeError, match="stale"):
        engine.rollback(token)
    assert engine.insert(0, 15)
    assert engine.partner(0) == 15 and engine.version == 1 and engine.check()


def test_high_degree_ring_and_matching_pages_reject_stale_versions() -> None:
    engine = Engine(129)
    engine.ring(16)
    assert engine.check() and engine.num_edges() == 129 * 16 and engine.size() == 64
    version, _, nextpage = engine.page(limit=1)
    assert nextpage == 1
    engine.delete(0, 1)
    with pytest.raises(RuntimeError, match="stale"):
        engine.page(nextpage, version=version)
    assert engine.partner(0) == 128 and engine.partner(128) == 0
    assert engine.check()


@pytest.mark.parametrize("value", [True, -1, 1.5, "4", 1 << 40])
def test_engine_rejects_invalid_universe_before_allocation(value: object) -> None:
    with pytest.raises(ValueError):
        Engine(value)  # type: ignore[arg-type]


def test_engine_type_is_sealed_and_reinitialization_is_rejected() -> None:
    engine = Engine(4)
    with pytest.raises(TypeError):
        type("MutableEngine", (Engine,), {})
    with pytest.raises(TypeError):
        Engine.insert = lambda *args: False  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="reinitialized"):
        engine.__init__(8)
