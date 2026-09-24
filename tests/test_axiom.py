"""Comprehensive unit tests for the FDMM implementation.

Tests cover graph layer, edge colouring, :math:`z`-system construction and
invariants, dynamic update maintenance, accounting counters, simulation
utilities, and stress tests.
"""

from __future__ import annotations

import random

import pytest

from axiom.augment import augment
from axiom.color import Vizing
from axiom.core import Matcher
from axiom.graph import Adjacency
from axiom.hierarchy import Hierarchy, build_hierarchy, refine_hierarchy
from axiom.matching import greedy, is_maximal_matching, partner_in, partners
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
        g.add_edge(0, 2)
        g.add_edge(0, 1)
        assert list(g.neighbors(0)) == [1, 2]

    def test_edges_iterator(self) -> None:
        g = Adjacency(4)
        g.add_edge(1, 2)
        g.add_edge(0, 1)
        assert list(g.edges()) == [(0, 1), (1, 2)]

    def test_invalid_vertex(self) -> None:
        g = Adjacency(3)
        with pytest.raises(ValueError):
            g.degree(5)

    def test_matcher_rejects_invalid_update_vertices(self) -> None:
        matcher = Matcher(3)
        with pytest.raises(ValueError):
            matcher.insert(-1, 1)
        with pytest.raises(ValueError):
            matcher.delete(1, 3)

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

    def test_matching_graph_uses_exact_single_color_path(self) -> None:
        g = Adjacency(6)
        g.add_edge(0, 1)
        g.add_edge(2, 3)
        g.add_edge(4, 5)
        assert Vizing().color(g, 1) == {
            (0, 1): 0,
            (2, 3): 0,
            (4, 5): 0,
        }

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

    def test_fan_rotation_colors_adversarial_partial_state(self) -> None:
        """Regression for the former two-path fallback failure."""
        g = Adjacency(6)
        for edge in ((0, 4), (0, 5), (2, 3), (3, 5)):
            g.add_edge(*edge)
        coloring = Vizing().color(g, 2)
        assert len(coloring) == g.num_edges()
        assert self._is_proper(g, coloring)


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
        assert is_maximal_matching(g, m)

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

    def test_matcher_rejects_non_integer_size(self) -> None:
        with pytest.raises(ValueError, match="integer"):
            Matcher(True)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="integer"):
            Matcher(4.5)  # type: ignore[arg-type]

    def test_multilevel_init(self) -> None:
        algo = Matcher(10, mode="multilevel")
        assert algo.mode == "multilevel"
        assert algo.maximal()
        assert algo.multi is not None
        assert algo.multi.check()

    def test_multilevel_scheduler_tracks_finest_level_budget(self) -> None:
        algo = Matcher(16, mode="multilevel")
        assert algo.eta == 4
        assert algo.level_zs == [4]
        assert algo.level_phase_lengths == [16]
        assert algo.phase_length == 16

        dense = Adjacency(16)
        for u in range(16):
            for v in range(u + 1, 16):
                dense.add_edge(u, v)
        dense_algo = Matcher(16, mode="multilevel", graph=dense)
        assert dense_algo.eta == 4
        assert dense_algo.level_zs == [16, 8, 4, 2, 1]
        assert dense_algo.level_phase_lengths == [64, 32, 16, 8, 4]
        assert dense_algo.phase_length == 4

    def test_multilevel_phase_clocks_are_nested_across_fine_rebuilds(self) -> None:
        dense = Adjacency(16)
        for left in range(16):
            for right in range(left + 1, 16):
                dense.add_edge(left, right)

        algo = Matcher(16, mode="multilevel", graph=dense)
        edges = list(algo.graph.edges())
        for edge in edges[:4]:
            algo.delete(*edge)

        # The finest phase has rebuilt, but all parent clocks retain their
        # progress.  Only the finest level has reached its boundary.
        assert algo.level_phase_updates == [4, 4, 4, 4, 0]
        assert algo.level_phase_indices == [0, 0, 0, 0, 1]

        for edge in edges[4:8]:
            algo.delete(*edge)

        # The next parent boundary closes after two finest phases; the
        # higher levels continue in the same inherited phase.
        assert algo.level_phase_updates == [8, 8, 8, 0, 0]
        assert algo.level_phase_indices == [0, 0, 0, 1, 2]

    def test_recursive_rebuild_inherits_level_one_without_rebuilding(self, monkeypatch):
        dense = Adjacency(16)
        for left in range(16):
            for right in range(left + 1, 16):
                dense.add_edge(left, right)
        algo = Matcher(16, mode="multilevel", graph=dense)
        assert len(algo.level_zs) > 1
        edge = next(iter(algo.graph.edges()))

        import axiom.rebuild as rebuild_module

        def unexpected_base_rebuild(*args, **kwargs):
            raise AssertionError("recursive rebuild rebuilt level one")

        monkeypatch.setattr(rebuild_module, "build", unexpected_base_rebuild)
        algo.graph.remove_edge(*edge)
        algo.deleted_edges.add(edge)
        algo.policy.rebuild(algo)

        assert algo.multi is not None
        assert algo.multi.check()

    def test_removed_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="basic.*multilevel"):
            Matcher(10, mode="tiered")

    def test_policy_injection_is_not_part_of_public_api(self) -> None:
        with pytest.raises(TypeError, match="policy"):
            Matcher(4, mode="basic", policy=object())  # type: ignore[call-arg]

    def test_matcher_rejects_invalid_colorer(self) -> None:
        with pytest.raises(ValueError, match="colorer"):
            Matcher(4, colorer=object())  # type: ignore[arg-type]

    def test_multilevel_rejects_non_paper_colorer(self) -> None:
        with pytest.raises(ValueError, match="PaperFanColorer"):
            Matcher(4, mode="multilevel", colorer=Vizing())

    def test_matcher_has_no_forwarding_wrapper_methods(self) -> None:
        assert not hasattr(Matcher, "augment")
        assert not hasattr(Matcher, "try_augment")
        assert not hasattr(Matcher, "flip")
        assert not hasattr(Matcher, "maintain_i3")

    def test_legacy_invariant_wrapper_module_is_removed(self) -> None:
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("axiom.invariant")

    def test_matcher_rejects_graph_with_different_size(self) -> None:
        with pytest.raises(ValueError, match="graph.n must equal matcher n"):
            Matcher(4, graph=Adjacency(5))

    def test_matcher_rejects_graph_missing_protocol_methods(self) -> None:
        class IncompleteGraph:
            n = 4

        with pytest.raises(ValueError, match="Graph protocol"):
            Matcher(4, graph=IncompleteGraph())  # type: ignore[arg-type]

    def test_matcher_rejects_inconsistent_custom_graph(self) -> None:
        graph = Adjacency(2)
        graph.adj[0].add(1)

        with pytest.raises(ValueError, match="graph"):
            Matcher(2, graph=graph)

    def test_duplicate_and_self_loop_insertions_are_noops(self) -> None:
        algo = Matcher(3, mode="multilevel")
        algo.insert(0, 1)
        snapshot = algo.stats
        algo.insert(1, 0)
        algo.insert(2, 2)
        assert algo.graph.num_edges() == 1
        assert algo.matching() == {(0, 1)}
        assert algo.stats == snapshot

    def test_fast_insert_rematches_the_exposed_partner(self) -> None:
        operations = [
            ("insert", 1, 2),
            ("insert", 0, 1),
            ("delete", 0, 1),
            ("insert", 1, 3),
            ("insert", 0, 3),
            ("insert", 0, 1),
            ("delete", 0, 1),
            ("insert", 2, 3),
            ("insert", 0, 2),
            ("delete", 1, 3),
            ("delete", 1, 2),
            ("insert", 0, 1),
        ]
        algo = Matcher(4, mode="multilevel")
        for operation, u, v in operations:
            getattr(algo, operation)(u, v)
            assert algo.maximal()

    def test_rematch_bu_prioritizes_h_before_inserted_edges(self) -> None:
        algo = Matcher(4, mode="multilevel")
        system = algo.system
        assert system is not None
        # Make the target an unmatched U vertex with both sources available.
        system.U = {0, 1, 2, 3}
        system.A = set()
        system.B = set()
        system.lambda_lists = {0: [2], 1: [], 2: [0], 3: []}
        algo.graph.add_edge(0, 2)
        algo.matched_edges.clear()
        algo.matched_vertices.clear()
        algo.partner_map.clear()
        algo.H_reverse = {2: {0}}
        algo.inserted_edges = {(1, 2)}
        algo.H_tilde = {(1, 2)}
        algo.bad_vertices = {2}

        algo._Matcher__rematch_vertex(2)

        assert algo.matching() == {(0, 2)}

    def test_proc_update_preserves_incoming_h_tilde_targets(self) -> None:
        algo = Matcher(4, mode="multilevel")
        algo.H_tilde = {(1, 2), (2, 3)}
        algo.matched_vertices = {2}

        algo._Matcher__proc_update(2)

        assert algo.H_tilde == {(1, 2)}

    def test_rematch_rejects_partition_corruption_instead_of_scanning_graph(
        self,
    ) -> None:
        algo = Matcher(4, mode="basic")
        assert algo.system is not None
        algo.system.A.discard(0)
        algo.system.B.discard(0)
        algo.system.U.discard(0)

        with pytest.raises(RuntimeError, match="does not partition"):
            algo._Matcher__rematch_vertex(0)

    def test_bad_vertex_promotion_backfills_existing_inserted_edges(self) -> None:
        algo = Matcher(8, mode="multilevel")

        # Vertex 1 becomes bad on the third incident insertion for this
        # schedule.  The edge (1, 2) predates that transition and must still
        # become visible as an incoming tilde-H edge for its unmatched source.
        algo.insert(0, 1)
        algo.insert(1, 2)
        algo.insert(1, 3)

        assert 1 in algo.bad_vertices
        assert (2, 1) in algo.H_tilde
        assert (3, 1) in algo.H_tilde

    def test_augment_preserves_matching_on_three_edge_path(self) -> None:
        graph = Adjacency(10)
        for edge in [(0, 4), (4, 7), (7, 9), (1, 8)]:
            graph.add_edge(*edge)
        matching = {(1, 8), (4, 7)}
        matched = {1, 8, 4, 7}
        assert augment(matching, graph.neighbors, 0, matched.__contains__)
        assert matching == {(0, 4), (1, 8), (7, 9)}

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

    def test_subphase_keeps_seed_inside_maintained_matching(self) -> None:
        algo = Matcher(8, mode="basic")
        algo.subphase_length = 1

        algo.insert(0, 1)

        assert algo.seed_matching <= algo.matched_edges
        assert algo.matchings[0] == algo.seed_matching
        assert algo.maximal()

    def test_deleted_seed_edge_is_removed_immediately(self) -> None:
        graph = Adjacency(8)
        for left in range(8):
            for right in range(left + 1, 8):
                graph.add_edge(left, right)

        for mode in ("basic", "multilevel"):
            algo = Matcher(8, mode=mode, graph=graph.copy())
            edge = next(iter(algo.seed_matching))

            algo.delete(*edge)

            assert edge not in algo.seed_matching
            assert all(edge not in matching for matching in algo.matchings)
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
        algo = Matcher(4, mode="basic")
        algo.phase_length = 3
        algo.insert(0, 1)
        assert algo.update_count == 1
        algo.insert(2, 3)
        assert algo.update_count == 2
        algo.insert(0, 2)
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

    def test_small_graph_matrix_sparse_and_dense(self) -> None:
        for mode in ("basic", "multilevel"):
            for n in range(11):
                sparse = Matcher(n, mode=mode)
                for vertex in range(max(0, n - 1)):
                    sparse.insert(vertex, vertex + 1)
                    assert sparse.maximal()

                dense_graph = Adjacency(n)
                for left in range(n):
                    for right in range(left + 1, n):
                        dense_graph.add_edge(left, right)
                dense = Matcher(n, mode=mode, graph=dense_graph)
                assert dense.maximal()
                for left in range(n):
                    for right in range(left + 1, n):
                        dense.delete(left, right)
                        assert dense.maximal()

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
        algo = Matcher(6, mode="basic")
        algo.phase_length = 5
        for u, v in [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]:
            algo.insert(u, v)
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

    def test_rematch_u_consumes_incoming_h_edge(self) -> None:
        """ProcRematchBU follows H's source-to-target direction."""
        algo = Matcher(4, mode="basic")
        algo.graph.add_edge(0, 1)
        assert algo.system is not None
        algo.system.U.update({0, 1})
        algo.H = {1: {0}}
        algo.H_reverse = {0: {1}}
        algo.S_hat = set()
        algo._Matcher__rematch_u(0)
        assert algo.matching() == {(0, 1)}

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

    def test_failed_update_rolls_back_all_mutable_state(self) -> None:
        """A failed repair cannot expose a partially applied update."""
        algo = Matcher(2, mode="basic")
        algo.phase_length = 1
        before = {
            "edges": set(algo.graph.edges()),
            "matching": algo.matching(),
            "matched_vertices": set(algo.matched_vertices),
            "partners": dict(algo.partner_map),
            "stats": algo.stats,
            "update_count": algo.update_count,
        }

        def fail_color(graph: object, delta: int) -> dict[tuple[int, int], int]:
            raise RuntimeError("injected rebuild failure")

        algo.colorer.color = fail_color  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="injected rebuild failure"):
            algo.insert(0, 1)

        assert set(algo.graph.edges()) == before["edges"]
        assert algo.matching() == before["matching"]
        assert algo.matched_vertices == before["matched_vertices"]
        assert algo.partner_map == before["partners"]
        assert algo.stats == before["stats"]
        assert algo.update_count == before["update_count"]

    def test_failed_multilevel_update_rolls_back_hierarchy_state(self) -> None:
        """A failed recursive rebuild cannot leak a partial phase update."""
        algo = Matcher(16, mode="multilevel")
        assert algo.multi is not None
        algo.phase_length = 1
        before = {
            "edges": set(algo.graph.edges()),
            "matching": algo.matching(),
            "matched_vertices": set(algo.matched_vertices),
            "partners": dict(algo.partner_map),
            "stats": algo.stats,
            "update_count": algo.update_count,
            "subphase_count": algo.subphase_count,
            "inserted": set(algo.inserted_edges),
            "deleted": set(algo.deleted_edges),
            "phase_edges": set(algo.phase_graph.edges())
            if algo.phase_graph is not None
            else set(),
            "hierarchy_edges": set(algo.multi.graph.edges()),
            "levels": [
                (
                    set(level.A),
                    set(level.B),
                    set(level.U),
                    set(level.M),
                )
                for level in algo.multi.levels
            ],
        }

        def fail_color(graph: object, delta: int) -> dict[tuple[int, int], int]:
            raise RuntimeError("injected multilevel rebuild failure")

        algo.colorer.color = fail_color  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="injected multilevel rebuild failure"):
            algo.insert(0, 1)

        assert set(algo.graph.edges()) == before["edges"]
        assert algo.matching() == before["matching"]
        assert algo.matched_vertices == before["matched_vertices"]
        assert algo.partner_map == before["partners"]
        assert algo.stats == before["stats"]
        assert algo.update_count == before["update_count"]
        assert algo.subphase_count == before["subphase_count"]
        assert algo.inserted_edges == before["inserted"]
        assert algo.deleted_edges == before["deleted"]
        assert algo.phase_graph is not None
        assert set(algo.phase_graph.edges()) == before["phase_edges"]
        assert algo.multi is not None
        assert set(algo.multi.graph.edges()) == before["hierarchy_edges"]
        assert [
            (set(level.A), set(level.B), set(level.U), set(level.M))
            for level in algo.multi.levels
        ] == before["levels"]
        assert algo.multi.check()


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

    def test_recursive_builder_retains_valid_levels(self) -> None:
        g = Adjacency(8)
        for u in range(8):
            for v in range(u + 1, 8):
                g.add_edge(u, v)
        hierarchy = build_hierarchy(g, [8, 4, 2])
        assert hierarchy.k == 3
        assert len(hierarchy.levels) == 3
        assert hierarchy.check()
        assert all(level.graph is hierarchy.graph for level in hierarchy.levels)

    def test_recursive_builder_colors_each_preceding_matching(self) -> None:
        """Each refinement input is the preceding level's matching subgraph."""
        from axiom.paper_coloring import PaperFanColorer

        class RecordingColorer:
            def __init__(self) -> None:
                self.calls: list[set[tuple[int, int]]] = []
                self.delegate = PaperFanColorer()

            def color(self, graph: Adjacency, delta: int) -> dict[tuple[int, int], int]:
                self.calls.append(set(graph.edges()))
                return self.delegate.color(graph, delta)

        graph = Adjacency(8)
        for u in range(8):
            for v in range(u + 1, 8):
                graph.add_edge(u, v)
        colorer = RecordingColorer()

        hierarchy = build_hierarchy(graph, [8, 4, 2], colorer=colorer)

        assert len(colorer.calls) == 2
        assert colorer.calls[0] == set(hierarchy.levels[0].M)
        assert colorer.calls[1] == set(hierarchy.levels[1].M)

    def test_recursive_regions_follow_multilevel_definition(self) -> None:
        graph = Adjacency(10)
        for u in range(10):
            for v in range(u + 1, 10):
                graph.add_edge(u, v)

        hierarchy = build_hierarchy(graph, [8, 4, 2])
        final_b = set(hierarchy.levels[-1].B)
        final_u = set(hierarchy.levels[-1].U)

        for index, region in enumerate(hierarchy.R_levels):
            below = set().union(*hierarchy.A_levels[index + 1 :]) | final_b | final_u
            assert region == below - hierarchy.N_levels[index]
            assert hierarchy.N_levels[index] <= (
                set().union(*hierarchy.A_levels[index + 1 :]) | final_b
            )
        assert all(
            hierarchy.R_levels[index + 1] <= hierarchy.R_levels[index]
            for index in range(hierarchy.k - 1)
        )

    def test_hierarchy_check_detects_intermediate_index_corruption(self) -> None:
        graph = Adjacency(8)
        for u in range(8):
            for v in range(u + 1, 8):
                graph.add_edge(u, v)
        hierarchy = build_hierarchy(graph, [8, 4, 2])
        assert hierarchy.check()

        source = next(iter(hierarchy.levels[0].U))
        hierarchy.levels[0].lambda_lists[source] = []

        assert not hierarchy.check()

    def test_recursive_builder_random_sparse_graphs(self) -> None:
        for seed in range(12):
            rng = random.Random(seed)
            graph = Adjacency(10)
            for u in range(10):
                for v in range(u + 1, 10):
                    if rng.random() < 0.35:
                        graph.add_edge(u, v)
            hierarchy = build_hierarchy(graph, [4, 2])
            assert hierarchy.check(), seed

    def test_recursive_builder_removes_base_only_u_u_edges(self) -> None:
        # A one-level base system may contain U-U edges, but the multilevel
        # definition forbids them from level 2 onward.
        graph = Adjacency(5)
        for u in range(5):
            for v in range(u + 1, 5):
                graph.add_edge(u, v)

        hierarchy = build_hierarchy(graph, [2, 1])

        assert (3, 4) in hierarchy.levels[0].M
        assert (3, 4) not in hierarchy.levels[1].M
        assert hierarchy.check()

    def test_recursive_builder_is_deterministic(self) -> None:
        first = Adjacency(10)
        for u in range(10):
            for v in range(u + 1, 10):
                if (u * 13 + v * 7) % 5 < 2:
                    first.add_edge(u, v)
        second = Adjacency(10)
        for edge in first.edges():
            second.add_edge(*edge)

        left = build_hierarchy(first, [10, 5, 3, 2])
        right = build_hierarchy(second, [10, 5, 3, 2])

        assert left.check() and right.check()
        assert [system.M for system in left.levels] == [
            system.M for system in right.levels
        ]
        assert left.A_levels == right.A_levels
        assert left.N_levels == right.N_levels
        assert left.R_levels == right.R_levels

    def test_recursive_builder_uses_configured_colorer(self) -> None:
        graph = Adjacency(8)
        for u in range(8):
            for v in range(u + 1, 8):
                graph.add_edge(u, v)

        calls: list[int] = []

        class RecordingColorer(Vizing):
            def color(self, graph: Adjacency, delta: int) -> dict[tuple[int, int], int]:
                calls.append(delta)
                return super().color(graph, delta)

        hierarchy = build_hierarchy(graph, [8, 4, 2], RecordingColorer())

        assert hierarchy.check()
        assert calls == [8, 4]

    def test_refinement_applies_edge_subsets_and_insertions(self) -> None:
        old_graph = Adjacency(8)
        for u in range(8):
            for v in range(u + 1, 8):
                old_graph.add_edge(u, v)
        old_graph.remove_edge(0, 7)
        base = build_hierarchy(old_graph, [8])
        deleted = {(0, 1)}
        inserted = {(0, 7)}
        refined = refine_hierarchy(
            base,
            4,
            deleted=deleted,
            inserted=inserted,
        )
        assert refined.check()
        assert (0, 7) in set(refined.graph.edges())
        assert len(refined.deferred_deletions) <= len(deleted) * 4 // 8

    def test_refinement_counts_empty_color_classes_for_deleted_edge_bound(self) -> None:
        graph = Adjacency(16)
        for u in range(0, 16, 2):
            graph.add_edge(u, u + 1)

        base = build_hierarchy(graph, [8])
        deleted = set(base.levels[0].M)
        refined = refine_hierarchy(base, 4, deleted=deleted)

        assert len(refined.deferred_deletions) <= len(deleted) * 4 // 8

    def test_deferred_deletions_propagate_geometrically_across_levels(self) -> None:
        graph = Adjacency(16)
        for u in range(16):
            for v in range(u + 1, 16):
                graph.add_edge(u, v)

        base = build_hierarchy(graph, [16])
        deleted = set(list(base.levels[0].M)[:13])
        level_two = refine_hierarchy(base, 8, deleted=deleted)
        assert level_two.deferred_deletions <= deleted
        assert len(level_two.deferred_deletions) <= len(deleted) * 8 // 16

        level_three = refine_hierarchy(
            level_two,
            4,
            deleted=set(level_two.deferred_deletions),
        )

        assert level_three.check()
        assert all(
            not (left in level_three.levels[-1].U and right in level_three.levels[-1].U)
            for left, right in level_three.levels[-1].M
        )
        assert level_three.deferred_deletions <= level_two.deferred_deletions
        assert len(level_three.deferred_deletions) <= (
            len(level_two.deferred_deletions) * 4 // 8
        )

    def test_refinement_removes_non_deferred_phase_deletions(self) -> None:
        """ED is removed from the refined graph except for bounded ED'."""
        graph = Adjacency(16)
        for u in range(16):
            for v in range(u + 1, 16):
                graph.add_edge(u, v)

        base = build_hierarchy(graph, [16])
        deleted = set(list(base.levels[0].M)[:12])
        refined = refine_hierarchy(base, 8, deleted=deleted)

        assert refined.check()
        assert refined.deferred_deletions <= deleted
        assert len(refined.deferred_deletions) <= len(deleted) * 8 // 16
        assert not (deleted - refined.deferred_deletions) & set(refined.graph.edges())

    def test_refinement_rejects_invalid_update_edge_sets(self) -> None:
        graph = Adjacency(4)
        graph.add_edge(0, 1)
        base = build_hierarchy(graph, [2])

        with pytest.raises(ValueError, match="deleted edges must belong"):
            refine_hierarchy(base, 1, deleted={(2, 3)})
        with pytest.raises(ValueError, match="canonical endpoints"):
            refine_hierarchy(base, 1, inserted={(1, 0)})
        with pytest.raises(ValueError, match="must be disjoint"):
            refine_hierarchy(base, 1, deleted={(0, 1)}, inserted={(0, 1)})

    def test_phase_sync_retains_deferred_deletions(self) -> None:
        phase_graph = Adjacency(4)
        phase_graph.add_edge(0, 1)
        hierarchy = build_hierarchy(phase_graph, [2, 1])
        hierarchy.deferred_deletions = {(2, 3)}

        live_graph = Adjacency(4)
        live_graph.add_edge(0, 1)
        hierarchy.sync_graph(live_graph)

        assert hierarchy.graph.has_edge(2, 3)

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

    def test_check_i3_floors_final_threshold(self) -> None:
        """I3 uses floor(2*tau), not 2*floor(tau)."""
        g = Adjacency(2)
        mls = Hierarchy(graph=g, k=1, A1={0}, R1={1})

        # tau = 32/40, so floor(2*tau) == 1 while 2*floor(tau) == 0.
        assert mls.check_i3({(0, 1)}, r=1, z=40) is True

    def test_maintain_i3_removes_all_excess_crossings(self) -> None:
        g = Adjacency(6)
        mls = Hierarchy(graph=g, k=1, A1={0, 1, 2}, R1={3, 4, 5})
        matching = {(0, 3), (1, 4), (2, 5)}

        repaired = mls.maintain_i3(
            matching,
            r=1,
            z=128,
            partner_of=lambda vertex: None,
            rematch=lambda vertex: None,
        )

        assert repaired == 3
        assert matching == set()
        assert mls.check_i3(matching, r=1, z=64)

    def test_matcher_i3_repair_keeps_partner_indexes_synchronized(self) -> None:
        matcher = Matcher(4, mode="multilevel")
        assert matcher.multi is not None
        matcher.multi.A1 = {0}
        matcher.multi.R1 = {1}
        matcher.matched_edges = {(0, 1)}
        matcher.matched_vertices = {0, 1}
        matcher.partner_map = {0: 1, 1: 0}

        repaired = matcher.multi.maintain_i3(
            matcher.matched_edges,
            r=1,
            z=128,
            partner_of=matcher.partner,
            rematch=lambda _vertex: None,
            drop_match=matcher.drop_match,
        )

        assert repaired == 1
        assert matcher.matched_edges == set()
        assert matcher.matched_vertices == set()
        assert matcher.partner_map == {}


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

    def test_random_insert_delete_multilevel_preserves_maximality(self) -> None:
        algo = Matcher(12, mode="multilevel")
        for op, u, v in random_updates(12, 300, random.Random(991)):
            getattr(algo, op)(u, v)
            assert algo.maximal()
            seen: set[int] = set()
            for left, right in algo.matching():
                assert left not in seen
                assert right not in seen
                seen.update((left, right))
                assert algo.partner(left) == right
                assert algo.partner(right) == left

    def test_auxiliary_indexes_follow_matching_and_lambda(self) -> None:
        algo = Matcher(8, mode="multilevel")
        for op, u, v in random_updates(8, 80, random.Random(414)):
            getattr(algo, op)(u, v)
            assert algo.system is not None
            assert algo.S_hat == {
                vertex
                for vertex in algo.system.S
                if vertex not in algo.matched_vertices
            }
            for vertex in algo.system.U:
                expected = {
                    neighbor
                    for neighbor in algo.system.lambda_lists.get(vertex, [])
                    if algo.graph.has_edge(vertex, neighbor)
                }
                if vertex not in algo.matched_vertices:
                    assert algo.H.get(vertex, set()) == expected
                else:
                    assert vertex not in algo.H
            for source, targets in algo.H.items():
                for target in targets:
                    assert source in algo.H_reverse.get(target, set())

    def test_proc_update_removes_replaced_h_reverse_entries(self) -> None:
        graph = Adjacency(8)
        for vertex in range(7):
            graph.add_edge(vertex, vertex + 1)
        algo = Matcher(8, mode="multilevel", graph=graph)
        if not algo.H:
            return
        source = next(iter(algo.H))
        old_target = next(iter(algo.H[source]))

        assert source in algo.H_reverse[old_target]
        assert algo.system is not None
        algo.system.graph.remove_edge(source, old_target)
        algo.system.index()
        algo._Matcher__proc_update(source)

        assert old_target not in algo.H.get(source, set())
        assert source not in algo.H_reverse.get(old_target, set())

    def test_inserted_edge_badness_is_phase_persistent(self) -> None:
        algo = Matcher(4, mode="multilevel")
        algo.phase_length = 100
        algo.insert(0, 1)
        algo.insert(0, 2)
        assert 0 in algo.bad_vertices
        algo.insert(0, 3)
        assert 0 in algo.bad_vertices
        algo.delete(0, 1)
        assert 0 in algo.bad_vertices
        for left, right in algo.H_tilde:
            assert right in algo.bad_vertices
            assert (min(left, right), max(left, right)) in algo.inserted_edges
            assert left not in algo.matched_vertices

    def test_multilevel_phase_graph_excludes_inserted_edges(self) -> None:
        algo = Matcher(4, mode="multilevel")
        algo.insert(0, 1)

        assert algo.graph.has_edge(0, 1)
        assert algo.multi is not None
        assert not algo.multi.graph.has_edge(0, 1)

    def test_large_graph_multilevel(self) -> None:
        n = 100
        algo = Matcher(n, mode="multilevel")
        for i in range(n - 1):
            algo.insert(i, i + 1)
        assert algo.maximal()
        assert algo.size() == n // 2

    def test_dense_multilevel_rebuilds_preserve_hierarchy(self) -> None:
        n = 16
        graph = Adjacency(n)
        for u in range(n):
            for v in range(u + 1, n):
                graph.add_edge(u, v)

        algo = Matcher(n, mode="multilevel", graph=graph)
        rng = random.Random(20260923)
        for _ in range(360):
            u, v = sorted(rng.sample(range(n), 2))
            if rng.random() < 0.55:
                algo.insert(u, v)
            else:
                algo.delete(u, v)
            assert algo.maximal()
            assert algo.multi is not None and algo.multi.check()

        assert algo.stats()["phase_rebuilds"] >= 2

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

    def test_policy_default_is_multilevel(self) -> None:
        """Matcher with mode='multilevel' has a Multilevel policy."""
        from axiom.rebuild import Multilevel

        algo = Matcher(4, mode="multilevel")
        assert isinstance(algo.policy, Multilevel)

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
        """compare returns results for both basic and multilevel modes."""
        from axiom.parallel import compare

        results = compare(n=20, updates=20, seed=1, max_workers=1)
        assert "basic" in results
        assert "multilevel" in results

    def test_compare_with_one_update_handles_zero_elapsed(self) -> None:
        """compare with very small updates exercises the float('inf') branch."""
        from axiom.parallel import compare

        results = compare(n=10, updates=1, seed=1, max_workers=1)
        assert results["basic"].is_maximal
        assert results["multilevel"].is_maximal
        assert results["basic"].matching_size >= 0
        assert results["multilevel"].matching_size >= 0

    def test_compare_alternating_seeds(self) -> None:
        """compare runs deterministically across multiple seeds."""
        from axiom.parallel import compare

        for seed in (1, 7, 42):
            results = compare(n=15, updates=10, seed=seed, max_workers=1)
            assert results["basic"].is_maximal
            assert results["multilevel"].is_maximal

    def test_run_parallel_empty_configs(self) -> None:
        """run_parallel with no configs returns an empty list."""
        from axiom.parallel import run_parallel

        assert run_parallel([], max_workers=1) == []

    def test_run_parallel_respects_max_workers(self) -> None:
        """run_parallel completes a small batch with explicit max_workers."""
        from axiom.parallel import run_parallel

        configs = [
            (10, "basic", 5, 1),
            (10, "multilevel", 5, 2),
        ]
        results = run_parallel(configs, max_workers=2)
        assert len(results) == 2
        assert all(r.is_maximal for r in results)

    def test_worker_zero_updates_returns_inf_rate(self) -> None:
        """worker with zero updates produces inf updates_per_sec."""
        from axiom.parallel import worker

        result = worker(n=8, mode="basic", updates=0, seed=1)
        assert result.updates == 0
        assert result.elapsed_sec >= 0.0
        assert result.updates_per_sec == float("inf")
        assert result.is_maximal
