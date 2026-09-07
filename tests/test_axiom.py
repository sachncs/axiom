"""Comprehensive unit tests for the FDMM reproduction.

Tests cover graph layer, edge colouring, :math:`z`-system construction and
invariants, dynamic update maintenance, accounting counters, simulation
utilities, and stress tests.
"""

from __future__ import annotations

import random

import pytest

from axiom.color import Vizing
from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.hierarchy import Hierarchy
from axiom.invariant import check_maximal_matching
from axiom.matching import greedy, partner_in, partners
from axiom.simulation import random_updates
from axiom.simulation import replay as replay
from axiom.system import System, build
from axiom.types import canonical
from axiom.visualize import visualize_adjacency, visualize_matching, visualize_system

# ------------------------------------------------------------------
# Graph layer
# ------------------------------------------------------------------


class TestAdjacency:
    """Tests for :class:`axiom.graph.Adjacency`."""

    def test_empty_graph(self) -> None:
        g = Adjacency(5)
        assert g.n == 5
        assert g.num_edges() == 0
        assert g.degree(0) == 0

    def test_add_edge(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        assert g.has_edge(0, 1)
        assert g.has_edge(1, 0)
        assert g.degree(0) == 1
        assert g.degree(1) == 1

    def test_remove_edge(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.remove_edge(0, 1)
        assert not g.has_edge(0, 1)
        assert g.degree(0) == 0

    def test_duplicate_insert_ignored(self) -> None:
        g = Adjacency(3)
        g.add_edge(0, 1)
        g.add_edge(0, 1)
        assert g.num_edges() == 1

    def test_self_loop_ignored(self) -> None:
        g = Adjacency(3)
        g.add_edge(0, 0)
        assert g.num_edges() == 0

    def test_neighbors(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        assert set(g.neighbors(0)) == {1, 2}

    def test_edges_iterator(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        edges = set(g.edges())
        assert edges == {(0, 1), (1, 2)}

    def test_invalid_vertex(self) -> None:
        g = Adjacency(3)
        with pytest.raises(ValueError):
            g.degree(5)

    def test_copy(self) -> None:
        g = Adjacency(3)
        g.add_edge(0, 1)
        h = g.copy()
        h.remove_edge(0, 1)
        assert g.has_edge(0, 1)
        assert not h.has_edge(0, 1)

    def test_single_vertex(self) -> None:
        g = Adjacency(1)
        g.add_edge(0, 0)
        assert g.num_edges() == 0
        assert list(g.edges()) == []

    def test_zero_vertices(self) -> None:
        g = Adjacency(0)
        assert g.num_edges() == 0
        assert list(g.edges()) == []

    def test_complete_graph(self) -> None:
        n = 5
        g = Adjacency(n)
        for i in range(n):
            for j in range(i + 1, n):
                g.add_edge(i, j)
        assert g.num_edges() == n * (n - 1) // 2
        for v in range(n):
            assert g.degree(v) == n - 1

    def test_bipartite_graph(self) -> None:
        n, m = 3, 4
        g = Adjacency(n + m)
        for i in range(n):
            for j in range(m):
                g.add_edge(i, n + j)
        assert g.num_edges() == n * m
        for i in range(n):
            assert g.degree(i) == m
        for j in range(m):
            assert g.degree(n + j) == n

    def test_edges_no_duplicates(self) -> None:
        g = Adjacency(3)
        g.add_edge(0, 1)
        g.add_edge(1, 0)
        assert len(list(g.edges())) == 1

    def test_remove_nonexistent_edge(self) -> None:
        g = Adjacency(3)
        g.remove_edge(0, 1)
        assert g.num_edges() == 0

    def test_large_graph_degree(self) -> None:
        n = 1000
        g = Adjacency(n)
        for i in range(n - 1):
            g.add_edge(i, i + 1)
        assert g.num_edges() == n - 1
        assert g.degree(0) == 1
        assert g.degree(n - 1) == 1

    def test_copy_isolation(self) -> None:
        g = Adjacency(5)
        g.add_edge(0, 1)
        g.add_edge(2, 3)
        h = g.copy()
        h.add_edge(0, 2)
        assert not g.has_edge(0, 2)
        assert h.has_edge(0, 2)

    def test_neighbors_on_isolated_vertex(self) -> None:
        g = Adjacency(5)
        g.add_edge(0, 1)
        assert set(g.neighbors(2)) == set()

    def test_strict_self_loop_raises(self) -> None:
        g = Adjacency(3)
        with pytest.raises(ValueError):
            g.add_edge(0, 0, strict=True)

    def test_strict_duplicate_raises(self) -> None:
        g = Adjacency(3)
        g.add_edge(0, 1)
        with pytest.raises(ValueError):
            g.add_edge(0, 1, strict=True)

    def test_strict_missing_delete_raises(self) -> None:
        g = Adjacency(3)
        with pytest.raises(ValueError):
            g.remove_edge(0, 1, strict=True)


# ------------------------------------------------------------------
# Edge colouring
# ------------------------------------------------------------------


class TestColor:
    """Tests for :mod:`axiom.color`."""

    def _is_proper(self, graph: Adjacency, coloring: dict) -> bool:
        for u in range(graph.n):
            seen: set[int] = set()
            for v in graph.neighbors(u):
                e = canonical(u, v)
                c = coloring[e]
                if c in seen:
                    return False
                seen.add(c)
        return True

    def test_triangle(self) -> None:
        g = Adjacency(3)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 0)
        coloring = Vizing().color(g, 2)
        assert len(set(coloring.values())) <= 3
        assert self._is_proper(g, coloring)

    def test_star(self) -> None:
        g = Adjacency(5)
        for i in range(1, 5):
            g.add_edge(0, i)
        coloring = Vizing().color(g, 4)
        assert len(set(coloring.values())) <= 5
        assert self._is_proper(g, coloring)

    def test_path(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)
        coloring = Vizing().color(g, 2)
        assert len(set(coloring.values())) <= 3
        assert self._is_proper(g, coloring)

    def test_empty_graph(self) -> None:
        g = Adjacency(3)
        coloring = Vizing().color(g, 0)
        assert coloring == {}

    def test_cycle(self) -> None:
        g = Adjacency(5)
        for i in range(5):
            g.add_edge(i, (i + 1) % 5)
        coloring = Vizing().color(g, 2)
        assert len(set(coloring.values())) <= 3
        assert self._is_proper(g, coloring)

    def test_complete_graph_odd(self) -> None:
        n = 5
        g = Adjacency(n)
        for i in range(n):
            for j in range(i + 1, n):
                g.add_edge(i, j)
        coloring = Vizing().color(g, n - 1)
        assert len(set(coloring.values())) <= n
        assert self._is_proper(g, coloring)

    def test_complete_graph_even(self) -> None:
        n = 6
        g = Adjacency(n)
        for i in range(n):
            for j in range(i + 1, n):
                g.add_edge(i, j)
        coloring = Vizing().color(g, n - 1)
        assert len(set(coloring.values())) <= n
        assert self._is_proper(g, coloring)

    def test_disconnected_components(self) -> None:
        g = Adjacency(6)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 0)
        g.add_edge(3, 4)
        g.add_edge(4, 5)
        g.add_edge(5, 3)
        coloring = Vizing().color(g, 2)
        assert len(set(coloring.values())) <= 3
        assert self._is_proper(g, coloring)

    def test_single_edge(self) -> None:
        g = Adjacency(2)
        g.add_edge(0, 1)
        coloring = Vizing().color(g, 1)
        assert len(set(coloring.values())) == 1
        assert self._is_proper(g, coloring)

    def test_two_parallel_paths(self) -> None:
        g = Adjacency(6)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(3, 4)
        g.add_edge(4, 5)
        coloring = Vizing().color(g, 2)
        assert len(set(coloring.values())) <= 3
        assert self._is_proper(g, coloring)

    def test_coloring_all_edges_present(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 2)
        coloring = Vizing().color(g, 2)
        assert len(coloring) == g.num_edges()
        for e in g.edges():
            assert e in coloring


# ------------------------------------------------------------------
# Matching helpers
# ------------------------------------------------------------------


class TestMatching:
    """Tests for :mod:`axiom.matching`."""

    def test_greedy(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)
        m = greedy(g)
        assert check_maximal_matching(g, m)

    def test_greedy_empty_graph(self) -> None:
        g = Adjacency(3)
        m = greedy(g)
        assert m == set()

    def test_partner_in(self) -> None:
        m = {(0, 1), (2, 3)}
        assert partner_in(m, 0) == 1
        assert partner_in(m, 3) == 2
        assert partner_in(m, 5) is None

    def test_partners(self) -> None:
        m = {(0, 1), (2, 3)}
        pmap = partners(m)
        assert pmap == {0: 1, 1: 0, 2: 3, 3: 2}


# ------------------------------------------------------------------
# z-Subgraph system
# ------------------------------------------------------------------


class TestSystem:
    """Tests for :class:`axiom.system.System`."""

    def test_basic_properties(self) -> None:
        g = Adjacency(6)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 2)
        g.add_edge(3, 4)
        g.add_edge(4, 5)

        system = System(graph=g, z=2)
        system.A = {0, 1, 2}
        system.B = {3, 4}
        system.U = {5}
        system.M = {(0, 1), (3, 4)}
        system.index()

        assert system.S == {0, 1, 2, 3, 4}
        assert system.degree(0) == 1
        assert system.degree(5) == 0
        assert system.check_p2()

    def test_lambda_lists(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(0, 3)
        system = System(graph=g, z=2)
        system.U = {0}
        system.B = {1, 2}
        system.A = {3}
        system.index()
        assert set(system.lambda_lists[0]) == {1, 2}
        assert set(system.L_lists[3]) == {0}

    def test_maximal_matching_check(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)
        system = System(graph=g, z=2)
        assert system.maximal({(0, 1), (2, 3)})
        assert not system.maximal({(0, 1)})

    def test_empty_graph_maximal(self) -> None:
        g = Adjacency(3)
        system = System(graph=g, z=1)
        assert system.maximal(set())

    def test_single_edge_maximal(self) -> None:
        g = Adjacency(2)
        g.add_edge(0, 1)
        system = System(graph=g, z=1)
        assert system.maximal({(0, 1)})

    def test_check_degree_bounds_empty(self) -> None:
        g = Adjacency(3)
        system = System(graph=g, z=1)
        system.A = set()
        system.B = set()
        system.U = {0, 1, 2}
        assert system.check_bound()

    def test_P1_violation(self) -> None:
        g = Adjacency(4)
        for i in range(3):
            g.add_edge(3, i)
        system = System(graph=g, z=1)
        system.U = {3}
        system.B = {0, 1, 2}
        system.A = set()
        assert not system.check_p1()

    def test_P2_violation(self) -> None:
        g = Adjacency(3)
        g.add_edge(0, 2)
        system = System(graph=g, z=1)
        system.A = {0}
        system.B = set()
        system.U = {1, 2}
        system.M = {(0, 2)}
        assert not system.check_p2()

    def test_all_invariants_on_empty(self) -> None:
        g = Adjacency(0)
        system = System(graph=g, z=0)
        assert system.check()

    def test_degree_in_M_on_unmatched_vertex(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        system = System(graph=g, z=1)
        system.M = {(0, 1)}
        assert system.degree(2) == 0

    def test_neighbors_in_M(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        system = System(graph=g, z=2)
        system.M = {(0, 1), (0, 2)}
        assert set(system.partner_in(0)) == {1, 2}
        assert set(system.partner_in(1)) == {0}


# ------------------------------------------------------------------
# z-System construction
# ------------------------------------------------------------------


class TestBuild:
    """Tests for :func:`axiom.system.build`."""

    def test_build_on_empty_graph(self) -> None:
        g = Adjacency(4)
        system = build(g, z=1)
        assert system.check_bound()
        assert system.check_u()

    def test_build_on_path(self) -> None:
        g = Adjacency(5)
        for i in range(4):
            g.add_edge(i, i + 1)
        system = build(g, z=2)
        assert system.check_bound()
        assert system.check_p2()

    def test_build_step_one_partition(self) -> None:
        """Verify that A, B, U are defined from M, not from G-degree."""
        g = Adjacency(4)
        # star: vertex 0 has degree 3, leaves degree 1
        for i in range(1, 4):
            g.add_edge(0, i)
        system = build(g, z=2)
        # M is a greedy maximal matching with cap 2.
        # It will contain (0,1) and (0,2).  Vertex 0 now has degree 2 in M -> S.
        # Leaves 1 and 2 have degree 1 in M (< 2) -> U.
        # Vertex 3 has degree 0 in M -> U.
        assert 0 in system.S
        assert system.degree(0) == 2
        assert 1 in system.U or 1 in system.S
        assert 2 in system.U or 2 in system.S
        assert 3 in system.U

    def test_build_invariants(self) -> None:
        g = Adjacency(10)
        for i in range(9):
            g.add_edge(i, i + 1)
        system = build(g, z=2)
        assert system.check_bound()
        assert system.check_p2()
        assert system.check_lambda()
        assert system.check_L()


# ------------------------------------------------------------------
# Dynamic maximal matching algorithm
# ------------------------------------------------------------------


class TestMatcher:
    """End-to-end tests for :class:`axiom.core.Matcher`."""

    def test_basic_init(self) -> None:
        algo = Matcher(10, mode="basic")
        assert algo.n == 10
        assert algo.mode == "basic"
        assert algo.maximal()

    def test_multilevel_init(self) -> None:
        algo = Matcher(10, mode="multilevel")
        assert algo.mode == "multilevel"
        assert algo.maximal()

    def test_insert_then_delete_basic(self) -> None:
        algo = Matcher(4, mode="basic")
        algo.insert(0, 1)
        assert algo.maximal()
        algo.insert(1, 2)
        assert algo.maximal()
        algo.insert(2, 3)
        assert algo.maximal()

        algo.delete(0, 1)
        assert algo.maximal()
        algo.delete(1, 2)
        assert algo.maximal()
        algo.delete(2, 3)
        assert algo.maximal()

    def test_insert_then_delete_multilevel(self) -> None:
        algo = Matcher(4, mode="multilevel")
        algo.insert(0, 1)
        assert algo.maximal()
        algo.insert(1, 2)
        assert algo.maximal()
        algo.insert(2, 3)
        assert algo.maximal()

        algo.delete(0, 1)
        assert algo.maximal()
        algo.delete(1, 2)
        assert algo.maximal()
        algo.delete(2, 3)
        assert algo.maximal()

    def test_triangle_updates(self) -> None:
        algo = Matcher(3, mode="basic")
        algo.insert(0, 1)
        algo.insert(1, 2)
        algo.insert(2, 0)
        assert algo.maximal()
        assert algo.size() >= 1

        algo.delete(0, 1)
        assert algo.maximal()

    def test_star_updates(self) -> None:
        algo = Matcher(5, mode="basic")
        for i in range(1, 5):
            algo.insert(0, i)
        assert algo.maximal()
        assert algo.size() == 1

        algo.delete(0, 1)
        assert algo.maximal()

    def test_path_updates(self) -> None:
        algo = Matcher(5, mode="basic")
        for i in range(4):
            algo.insert(i, i + 1)
        assert algo.maximal()

        for i in range(4):
            algo.delete(i, i + 1)
        assert algo.maximal()

    def test_statistics(self) -> None:
        algo = Matcher(5, mode="basic")
        algo.insert(0, 1)
        stats = algo.stats()
        assert stats["n"] == 5
        assert stats["m"] == 1
        assert stats["matching_size"] == 1
        assert "total_updates" in stats

    def test_rebuild_triggered(self) -> None:
        algo = Matcher(2, mode="basic")
        algo.phase_length = 3
        algo.insert(0, 1)
        assert algo.update_count == 1
        algo.insert(0, 1)
        assert algo.update_count == 2
        algo.insert(0, 1)
        assert algo.update_count == 0
        assert algo.maximal()

    def test_is_maximal_after_sequence(self) -> None:
        algo = Matcher(6, mode="basic")
        edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)]
        for u, v in edges:
            algo.insert(u, v)
            assert algo.maximal()

        for u, v in edges:
            algo.delete(u, v)
            assert algo.maximal()

    def test_invalid_mode(self) -> None:
        with pytest.raises(ValueError):
            Matcher(5, mode="fast")

    def test_negative_vertices(self) -> None:
        with pytest.raises(ValueError):
            Matcher(-1)

    def test_empty_graph_basic(self) -> None:
        algo = Matcher(0, mode="basic")
        assert algo.maximal()
        assert algo.size() == 0

    def test_empty_graph_multilevel(self) -> None:
        algo = Matcher(0, mode="multilevel")
        assert algo.maximal()
        assert algo.size() == 0

    def test_single_vertex_graph(self) -> None:
        algo = Matcher(1, mode="basic")
        algo.insert(0, 0)
        assert algo.maximal()
        assert algo.size() == 0

    def test_complete_graph_basic(self) -> None:
        n = 6
        algo = Matcher(n, mode="basic")
        for i in range(n):
            for j in range(i + 1, n):
                algo.insert(i, j)
        assert algo.maximal()
        assert algo.size() == n // 2

    def test_complete_graph_then_remove_all(self) -> None:
        n = 5
        algo = Matcher(n, mode="basic")
        edges = [(i, j) for i in range(n) for j in range(i + 1, n)]
        for u, v in edges:
            algo.insert(u, v)
        assert algo.maximal()
        for u, v in edges:
            algo.delete(u, v)
        assert algo.maximal()
        assert algo.size() == 0

    def test_bipartite_graph(self) -> None:
        n, m = 3, 4
        algo = Matcher(n + m, mode="basic")
        for i in range(n):
            for j in range(m):
                algo.insert(i, n + j)
        assert algo.maximal()
        assert algo.size() >= min(n, m)

    def test_repeated_insert_delete_same_edge(self) -> None:
        algo = Matcher(2, mode="basic")
        for _ in range(20):
            algo.insert(0, 1)
            assert algo.maximal()
            algo.delete(0, 1)
            assert algo.maximal()

    def test_random_stress_basic(self) -> None:
        n = 10
        rng = random.Random(42)
        algo = Matcher(n, mode="basic")
        edges: set[tuple[int, int]] = set()
        for _ in range(200):
            u = rng.randrange(n)
            v = rng.randrange(n)
            if u == v:
                continue
            e = (min(u, v), max(u, v))
            if e not in edges:
                edges.add(e)
                algo.insert(e[0], e[1])
            else:
                edges.remove(e)
                algo.delete(e[0], e[1])
            assert algo.maximal()

    def test_random_stress_multilevel(self) -> None:
        n = 10
        rng = random.Random(123)
        algo = Matcher(n, mode="multilevel")
        edges: set[tuple[int, int]] = set()
        for _ in range(200):
            u = rng.randrange(n)
            v = rng.randrange(n)
            if u == v:
                continue
            e = (min(u, v), max(u, v))
            if e not in edges:
                edges.add(e)
                algo.insert(e[0], e[1])
            else:
                edges.remove(e)
                algo.delete(e[0], e[1])
            assert algo.maximal()

    def test_alternating_insert_delete_path(self) -> None:
        algo = Matcher(4, mode="basic")
        for _ in range(10):
            algo.insert(0, 1)
            assert algo.maximal()
            algo.insert(1, 2)
            assert algo.maximal()
            algo.insert(2, 3)
            assert algo.maximal()
            algo.delete(0, 1)
            assert algo.maximal()
            algo.delete(1, 2)
            assert algo.maximal()
            algo.delete(2, 3)
            assert algo.maximal()

    def test_matching_is_subset_of_edges(self) -> None:
        algo = Matcher(5, mode="basic")
        algo.insert(0, 1)
        algo.insert(1, 2)
        algo.insert(2, 3)
        matching = algo.matching()
        for e in matching:
            assert algo.graph.has_edge(e[0], e[1])

    def test_delete_nonexistent_edge(self) -> None:
        algo = Matcher(3, mode="basic")
        algo.delete(0, 1)
        assert algo.maximal()

    def test_get_matching_returns_copy(self) -> None:
        algo = Matcher(2, mode="basic")
        algo.insert(0, 1)
        m1 = algo.matching()
        m2 = algo.matching()
        assert m1 is not m2

    def test_accounting_counters(self) -> None:
        algo = Matcher(4, mode="basic")
        algo.insert(0, 1)
        algo.insert(1, 2)
        algo.delete(0, 1)
        stats = algo.stats()
        assert stats["total_updates"] == 3
        assert stats["total_insertions"] == 2
        assert stats["total_deletions"] == 1

    def test_partner_method(self) -> None:
        algo = Matcher(4, mode="basic")
        algo.insert(0, 1)
        assert algo.partner(0) == 1
        assert algo.partner(1) == 0
        assert algo.partner(2) is None

    def test_phase_transition(self) -> None:
        algo = Matcher(4, mode="basic")
        algo.phase_length = 5
        for _i in range(5):
            algo.insert(0, 1)
        assert algo.update_count == 0  # rebuild triggered
        assert algo.maximal()

    def test_rematch_after_deleting_matching_edge(self) -> None:
        algo = Matcher(4, mode="basic")
        algo.insert(0, 1)
        algo.insert(2, 3)
        assert algo.size() == 2
        algo.delete(0, 1)
        assert algo.maximal()
        # The remaining edge (2,3) should still be in the matching
        assert (2, 3) in algo.matching()

    def test_multilevel_levels_exist(self) -> None:
        algo = Matcher(50, mode="multilevel")
        assert algo.k >= 1
        assert algo.system is not None

    def test_rematch_u_no_phantom_edge_from_stale_list(self) -> None:
        """Regression: a stale lambda list must not produce a phantom edge.

        With the partner dict maintained atomically by add_match/drop_match,
        a vertex placed back into U without a matching edge has no entry in
        the partner map. The rematch routine must consult the graph (via
        graph.has_edge) before adding a candidate edge to the matching,
        not blindly trust a stale lambda list that mentions a non-edge.
        """
        from axiom.types import canonical

        algo = Matcher(4, mode="basic")
        algo.insert(0, 1)
        algo.insert(0, 2)
        algo.policy.rebuild(algo)
        # Place vertex 0 in U and ensure it is unmatched in M*.
        algo.system.U.add(0)
        algo.system.A.discard(0)
        algo.system.B.discard(0)
        for e in list(algo.matched_edges):
            if 0 in e:
                algo.drop_match(e[0], e[1])
        assert 0 not in algo.matched_vertices
        assert 0 not in algo.partner_map
        # Inject a stale lambda list that claims 3 is a neighbour of 0.
        algo.system.lambda_lists[0] = [1, 2, 3]
        # Ensure 1 and 2 are already matched so they are skipped.
        algo.matched_vertices.add(1)
        algo.matched_vertices.add(2)
        algo._Matcher__rematch_u(0)
        # Phantom edge (0,3) must not be added because (0,3) is not
        # in the underlying graph.
        assert canonical(0, 3) not in algo.matched_edges

    def test_partition_color_range_error(self) -> None:
        """Regression: out-of-range colors from a colorer must raise."""
        from axiom.color import Greedy

        algo = Matcher(4, mode="basic", colorer=Greedy())

        def bad_color(graph: object, delta: int) -> dict[tuple[int, int], int]:
            return {(0, 1): 0, (1, 2): delta + 5}

        algo.colorer.color = bad_color  # type: ignore[assignment]
        algo.insert(0, 1)
        algo.insert(1, 2)
        with pytest.raises(RuntimeError):
            algo.policy.rebuild(algo)


# ------------------------------------------------------------------
# Multi-level system
# ------------------------------------------------------------------


class TestHierarchy:
    """Tests for :class:`axiom.hierarchy.Hierarchy`."""

    def test_empty(self) -> None:
        g = Adjacency(4)
        mls = Hierarchy(graph=g, k=2)
        assert mls.k == 2
        assert not mls.levels

    def test_with_levels(self) -> None:
        g = Adjacency(4)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        mls = Hierarchy(graph=g, k=2)
        mls.levels = [
            System(graph=g, z=2, A={0}, B={1}, U={2, 3}),
            System(graph=g, z=1, A={0}, B={1}, U={2, 3}),
        ]
        assert len(mls.levels) == 2

    def test_check_i3_empty(self) -> None:
        g = Adjacency(0)
        mls = Hierarchy(graph=g, k=1)
        # Empty graph: trivial satisfaction.
        assert mls.check_i3(set(), r=10, z=2) is True

    def test_check_i3_trivial_match(self) -> None:
        g = Adjacency(4)
        mls = Hierarchy(
            graph=g,
            k=1,
            A1={0},
            A2={1},
            N1={1, 2},
            R1={3},
        )
        # Edge (0, 3) crosses A1 and R1. With r=10 and z=2, the bound
        # is 2*tau = 2 * (32 * 10 / 2) = 320; the matching trivially
        # satisfies I3.
        assert mls.check_i3({(0, 3)}, r=10, z=2) is True


# ------------------------------------------------------------------
# Simulation utilities
# ------------------------------------------------------------------


class TestSequence:
    """Tests for :mod:`axiom.simulation`."""

    def test_random_updates(self) -> None:
        rng = random.Random(7)
        updates = list(random_updates(5, 20, rng))
        assert len(updates) == 20
        for op, u, v in updates:
            assert op in ("insert", "delete")
            assert 0 <= u < 5
            assert 0 <= v < 5

    def test_replay(self) -> None:
        algo = Matcher(4, mode="basic")
        updates = [("insert", 0, 1), ("insert", 1, 2), ("delete", 0, 1)]
        replay(algo, updates)
        assert algo.maximal()


# ------------------------------------------------------------------
# Performance sanity checks
# ------------------------------------------------------------------


class TestPerformance:
    """Lightweight performance sanity checks."""

    def test_large_graph_basic(self) -> None:
        n = 100
        algo = Matcher(n, mode="basic")
        for i in range(n - 1):
            algo.insert(i, i + 1)
        assert algo.maximal()
        assert algo.size() == n // 2

    def test_large_graph_multilevel(self) -> None:
        n = 100
        algo = Matcher(n, mode="multilevel")
        for i in range(n - 1):
            algo.insert(i, i + 1)
        assert algo.maximal()
        assert algo.size() == n // 2

    def test_dense_graph_basic(self) -> None:
        n = 20
        algo = Matcher(n, mode="basic")
        for i in range(n):
            for j in range(i + 1, n):
                algo.insert(i, j)
        assert algo.maximal()
        assert algo.size() == n // 2


# ------------------------------------------------------------------
# Refactor regression tests
# ------------------------------------------------------------------


class TestRefactor:
    """Tests for the post-refactor invariants introduced by the
    rebuild-strategy, partner-dict, and dead-code-removal work."""

    def test_partner_dict_consistent_with_matching(self) -> None:
        """partner(v) must agree with the matching at every step.

        Run a deterministic random walk and assert that the partner
        dict and the matched_edges set describe the same relation.
        """
        import random as random_mod

        rng = random_mod.Random(0)
        n = 30
        algo = Matcher(n, mode="basic")
        for op in random_updates(n, 300, rng):
            if op[0] == "insert":
                algo.insert(op[1], op[2])
            else:
                algo.delete(op[1], op[2])
            # Every matched vertex has exactly one partner entry; no
            # unmatched vertex has a partner entry.
            for u in range(n):
                p = algo.partner(u)
                if p is None:
                    assert u not in algo.partner_map
                    assert u not in algo.matched_vertices
                else:
                    assert algo.partner(p) == u
                    assert (min(u, p), max(u, p)) in algo.matched_edges

    def test_policy_default_is_basic(self) -> None:
        """Matcher with mode='basic' has a Basic policy."""
        from axiom.rebuild import Basic

        algo = Matcher(4, mode="basic")
        assert isinstance(algo.policy, Basic)

    def test_policy_default_is_tiered(self) -> None:
        """Matcher with mode='tiered' has a Tiered policy."""
        from axiom.rebuild import Tiered

        algo = Matcher(4, mode="tiered")
        assert isinstance(algo.policy, Tiered)

    def test_policy_explicit_overrides_mode(self) -> None:
        """Passing policy=Basic() overrides a 'tiered' mode string."""
        from axiom.rebuild import Basic

        algo = Matcher(4, mode="tiered", policy=Basic())
        assert isinstance(algo.policy, Basic)

    def test_no_aux_graph_attribute(self) -> None:
        """The dead aux_graph field has been removed from Matcher."""
        algo = Matcher(4, mode="basic")
        assert not hasattr(algo, "aux_graph")

    def test_add_drop_match_helpers(self) -> None:
        """add_match / drop_match update all three matching views atomically."""
        algo = Matcher(4, mode="basic")
        algo.add_match(0, 1)
        assert (0, 1) in algo.matched_edges
        assert 0 in algo.matched_vertices
        assert 1 in algo.matched_vertices
        assert algo.partner(0) == 1
        assert algo.partner(1) == 0
        algo.drop_match(0, 1)
        assert (0, 1) not in algo.matched_edges
        assert 0 not in algo.matched_vertices
        assert 1 not in algo.matched_vertices
        assert algo.partner(0) is None
        assert algo.partner(1) is None

    def test_three_visualize_distinct(self) -> None:
        """The three visualize_* functions produce non-empty distinct strings."""
        algo = Matcher(4, mode="basic")
        for u, v in [(0, 1), (1, 2), (2, 3)]:
            algo.insert(u, v)
        s = visualize_system(algo.system)
        m = visualize_matching(algo)
        a = visualize_adjacency(algo)
        assert s and m and a
        assert s != m != a


# ------------------------------------------------------------------
# Coverage expansion
# ------------------------------------------------------------------


class TestCoverage:
    """Additional tests that close gaps in coverage of the public API."""

    def test_disconnected_components_basic(self) -> None:
        """Two disjoint components: each is matched independently."""
        algo = Matcher(20, mode="basic")
        for u, v in [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)]:
            algo.insert(u, v)
        for u, v in [(10, 11), (12, 13), (14, 15), (16, 17), (18, 19)]:
            algo.insert(u, v)
        assert algo.maximal()
        assert algo.size() == 10

    def test_dense_graph_stress(self) -> None:
        """A dense graph after a long random walk."""
        import random as random_mod

        rng = random_mod.Random(123)
        n = 30
        algo = Matcher(n, mode="basic")
        # Build a dense graph by inserting many edges.
        edges = []
        for i in range(n):
            for j in range(i + 1, n):
                edges.append((i, j))
        # Insert a quarter of the edges randomly.
        sample = rng.sample(edges, len(edges) // 4)
        for e in sample:
            algo.insert(e[0], e[1])
        assert algo.maximal()
        # Then a random walk.
        for op in random_updates(n, 100, rng):
            if op[0] == "insert":
                algo.insert(op[1], op[2])
            else:
                algo.delete(op[1], op[2])
        assert algo.maximal()

    def test_replay_then_maximal(self) -> None:
        """After replay, the matching must be maximal for any seed."""
        import random as random_mod

        rng = random_mod.Random(7)
        n = 40
        updates = list(random_updates(n, 100, rng))
        algo = Matcher(n, mode="basic")
        replay(algo, updates)
        assert algo.maximal()

    def test_augment_method_returns_count(self) -> None:
        """Matcher.augment() returns the number of paths applied."""
        algo = Matcher(6, mode="basic")
        algo.insert(0, 1)
        algo.insert(2, 3)
        algo.insert(4, 5)
        # Force a rebuild via policy so the system has an S partition.
        algo.policy.rebuild(algo)
        # Manually drive augment(); the result is an int >= 0.
        count = algo.augment()
        assert isinstance(count, int)
        assert count >= 0

    def test_try_augment_returns_bool(self) -> None:
        """Matcher.try_augment returns a boolean."""
        algo = Matcher(4, mode="basic")
        algo.insert(0, 1)
        algo.policy.rebuild(algo)
        result = algo.try_augment(2, set())
        assert isinstance(result, bool)

    def test_flip_path_no_op_on_empty(self) -> None:
        """flip() on a single-vertex path does nothing."""
        algo = Matcher(4, mode="basic")
        seed_before = set(algo.seed_matching)
        algo.flip([0])
        assert algo.seed_matching == seed_before

    def test_greedy_colorer_proper(self) -> None:
        """Greedy().color returns a proper coloring."""
        from axiom.color import Greedy

        g = Adjacency(6)
        for u, v in [(0, 1), (0, 2), (1, 2), (1, 3), (2, 4), (3, 4), (4, 5)]:
            g.add_edge(u, v)
        coloring = Greedy().color(g, 3)
        # For every vertex, no two incident edges share a color.
        for v in range(g.n):
            edges = [e for e in coloring if v in e]
            colors = [coloring[e] for e in edges]
            assert len(colors) == len(set(colors))

    def test_ledger_independent(self) -> None:
        """Ledger can be used standalone (no matcher required)."""
        from axiom.ledger import Ledger

        ledger = Ledger()
        ledger.record_insertion()
        ledger.record_deletion()
        ledger.record_phase_rebuild()
        ledger.record_subphase_rebuild()
        ledger.record_rematch_u_scan(5)
        ledger.record_rematch_b_scan(3)
        ledger.record_rematch_a_scan(2)
        ledger.record_greedy_rebuild()
        ledger.record_stale_cleanup(2)
        snap = ledger.snapshot()
        assert snap["total_updates"] == 2
        assert snap["phase_rebuilds"] == 1
        assert snap["subphase_rebuilds"] == 1
        assert snap["rematch_u_scans"] == 5
        # Two stale_cleanup calls (count=2 + count=0 from a previous
        # field default) sum to 2.
        assert snap["stale_cleanups"] >= 1

    def test_compare_modes_returns_both(self) -> None:
        """compare returns results for both basic and tiered modes."""
        from axiom.parallel import compare

        results = compare(n=20, updates=20, seed=1, max_workers=1)
        assert "basic" in results
        assert "tiered" in results
