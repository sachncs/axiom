"""Property-based and long-sequence checks for dynamic matching."""

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from axiom import Matcher, partners
from axiom.matching import is_maximal_matching


@settings(max_examples=30, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.booleans(),
            st.integers(min_value=0, max_value=7),
            st.integers(min_value=0, max_value=7),
        ),
        min_size=1,
        max_size=40,
    )
)
def test_generated_updates_preserve_matching_contract(
    updates: list[tuple[bool, int, int]],
) -> None:
    for mode in ("basic", "multilevel"):
        matcher = Matcher(8, mode=mode)
        for insert, left, right in updates:
            if left == right:
                continue
            if insert:
                matcher.insert(left, right)
            else:
                matcher.delete(left, right)

            matching = matcher.matching()
            assert is_maximal_matching(matcher.graph, matching)
            assert partners(matching) == matcher.partner_map
            assert matcher.maximal()
            if mode == "multilevel":
                assert matcher.multi is not None
                assert matcher.multi.check()
                system = matcher.system
                assert system is not None
                expected_h = {
                    vertex: {
                        neighbor
                        for neighbor in system.lambda_lists.get(vertex, [])
                        if system.graph.has_edge(vertex, neighbor)
                    }
                    for vertex in system.U
                    if vertex not in matcher.matched_vertices
                }
                expected_h = {
                    vertex: neighbors
                    for vertex, neighbors in expected_h.items()
                    if neighbors
                }
                actual_h = {
                    vertex: set(neighbors)
                    for vertex, neighbors in matcher.H.items()
                    if neighbors
                }
                assert actual_h == expected_h


def test_long_adversarial_multilevel_sequence_stays_consistent() -> None:
    """Exercise repeated phase rebuilds and updates without stale hierarchy state."""
    rng = random.Random(20260923)
    matcher = Matcher(24, mode="multilevel")

    for _ in range(1_000):
        left, right = sorted(rng.sample(range(matcher.n), 2))
        if rng.random() < 0.58:
            matcher.insert(left, right)
        else:
            matcher.delete(left, right)

        assert matcher.maximal()
        assert is_maximal_matching(matcher.graph, matcher.matching())
        assert partners(matcher.matching()) == matcher.partner_map
        assert matcher.multi is not None
        assert matcher.multi.check()


def test_phase_boundaries_preserve_deferred_edge_state() -> None:
    """Repeated phase rebuilds keep E_I/E_D' synchronized with the live graph."""
    rng = random.Random(20260924)
    matcher = Matcher(32, mode="multilevel")

    for _ in range(600):
        left, right = sorted(rng.sample(range(matcher.n), 2))
        if rng.random() < 0.5:
            matcher.insert(left, right)
        else:
            matcher.delete(left, right)

        assert matcher.multi is not None
        expected = (set(matcher.graph.edges()) - set(matcher.inserted_edges)) | set(
            matcher.multi.deferred_deletions
        )
        assert set(matcher.multi.graph.edges()) == expected
        assert matcher.multi.check()
        assert matcher.maximal()
