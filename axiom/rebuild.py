"""Rebuild policy strategy for the dynamic matcher.

This module defines the abstract :class:`Rebuild` strategy and its two
concrete implementations (:class:`Basic` and :class:`Multilevel`).  The
:class:`axiom.core.Matcher` holds a single :class:`Rebuild` instance and
delegates configuration (z, phase_length, subphase_length, k, level_zs)
and full phase rebuilds to it. Subclasses are selected internally from the
canonical ``mode=`` string.

Single responsibility:
    Decide *when* and *how* to rebuild the supporting z-system or
    hierarchy after a phase boundary.  The Matcher owns the actual
    graph and matching state; the policy owns the z-system choices
    and the rebuild procedure.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol

from axiom.graph import Adjacency
from axiom.hierarchy import Hierarchy, build_hierarchy, refine_hierarchy
from axiom.system import System, build
from axiom.types import Graph

if TYPE_CHECKING:
    from axiom.core import Matcher


def _snapshot(graph: Graph) -> Graph:
    """Create an isolated adjacency snapshot for the current phase."""
    result = Adjacency(graph.n)
    for left, right in graph.edges():
        result.add_edge(left, right)
    return result


def _base_snapshot(matcher: Matcher) -> tuple[Graph, System]:
    """Build the phase-start base system for recursive refinement.

    The theorem-4.4 refinement requires a valid h-level input system.  The
    level-1 system is rebuilt on the isolated phase snapshot so that a prior
    refinement cannot leak an approximate matching or stale degree counters
    into the next recursive construction.
    """
    assert matcher.multi is not None
    assert matcher.phase_graph is not None
    previous = matcher.multi.levels[0]
    # Keep the phase-start graph and its M edges intact: theorem 4.4 treats
    # ED as deletions from that input system and chooses the bounded subset
    # that may be deferred into the refined hierarchy.  Insertions remain in
    # EI and are supplied separately to ``refine_hierarchy``.
    # The authoritative input is the immutable phase-start snapshot.  It may
    # retain the bounded deferred-deletion set E_D' from the preceding
    # refinement; the live matcher graph intentionally does not contain
    # current-phase deletions.
    graph = _snapshot(matcher.phase_graph)
    system = build(graph, previous.z)
    return graph, system


class Rebuild(Protocol):
    """Strategy interface for phase-level rebuilds.

    Implementations decide how to set up the z-system(s) (basic or
    multi-level) and how to rebuild them at phase boundaries.  They
    mutate the :class:`Matcher` instance they receive by setting
    parameters (z, phase_length, subphase_length, k, level_zs) and by
    re-running the construction routine.
    """

    name: str

    def configure(self, matcher: Matcher) -> None:
        """Set up z, phase_length, subphase_length, etc. on the matcher."""
        ...

    def rebuild(self, matcher: Matcher) -> None:
        """Run a full z-system rebuild and refresh M*."""
        ...


class Basic:
    """Single-level Ο̃(n^{2/3}) amortised rebuild policy."""

    name = "basic"

    def configure(self, matcher: Matcher) -> None:
        matcher.z = math.ceil(matcher.n ** (2.0 / 3.0)) if matcher.n > 0 else 1
        matcher.phase_length = (
            math.ceil(matcher.n ** (4.0 / 3.0)) if matcher.n > 0 else 1
        )
        matcher.subphase_length = max(1, matcher.phase_length // matcher.z)
        matcher.k = 0
        matcher.level_zs = []
        matcher.level_phase_lengths = []
        matcher.eta = 0

    def rebuild(self, matcher: Matcher) -> None:
        matcher.system = build(matcher.graph, matcher.z)
        if not matcher.system.check():
            raise RuntimeError(
                "basic rebuild produced an invalid z-system; refusing to "
                "continue with stale state"
            )
        matcher.partition()
        matcher.refresh()
        if not matcher.maximal():
            raise RuntimeError(
                "basic rebuild produced a non-maximal matching; refusing to "
                "continue with stale state"
            )
        matcher.update_count = 0
        matcher.subphase_count = 0
        matcher.accountant.record_phase_rebuild()


class Multilevel:
    """Recursive multi-level rebuild policy.

    Builds a recursively refined :class:`axiom.hierarchy.Hierarchy` at
    decreasing ``z`` values.  The innermost level is consulted on a
    per-update basis; the full hierarchy is rebuilt at phase boundaries.
    """

    name = "multilevel"

    def configure(self, matcher: Matcher) -> None:
        level_zs, phase_lengths, eta = self._schedule(matcher)
        matcher.level_zs = level_zs
        matcher.level_phase_lengths = phase_lengths
        matcher.eta = eta
        matcher.k = len(level_zs)
        matcher.phase_length = self._phase_budget(matcher)
        # The active system is the finest (smallest-z) level.
        if matcher.z == 0 and matcher.level_zs:
            matcher.z = matcher.level_zs[-1]
        matcher.subphase_length = (
            max(1, matcher.phase_length // matcher.z) if matcher.z > 0 else 1
        )

    @staticmethod
    def _schedule(matcher: Matcher) -> tuple[list[int], list[int], int]:
        """Return the paper's type-1 or type-2 level and phase schedule."""
        if matcher.n <= 1:
            return [1], [1], 1

        root_n = math.sqrt(matcher.n)
        eta = 1
        while eta < root_n:
            eta *= 2

        # The recursive theorem fixes the hierarchy from n, not from the
        # current average degree.  Start with the greatest power of two no
        # larger than n, then halve until the finest level is within one
        # power-of-two step of sqrt(n).  This keeps the schedule stable when
        # updates change density during a phase.
        z = 1 << (matcher.n.bit_length() - 1)
        level_zs = [z]
        while z // 2 >= root_n:
            z //= 2
            level_zs.append(z)

        phase_lengths = [max(1, level_z * eta) for level_z in level_zs]
        return level_zs, phase_lengths, eta

    @staticmethod
    def _phase_budget(matcher: Matcher) -> int:
        """Return the active finest-level phase length.

        The recursive type-2 schedule gives a level-``i`` phase length of
        ``z_i * eta``.  The matcher operates on the finest level, so its
        phase budget is the final schedule entry; it is not a function of
        the current edge count.
        """
        if matcher.n <= 1:
            return 1
        if not matcher.level_phase_lengths:
            raise RuntimeError("multilevel schedule has no phase lengths")
        return matcher.level_phase_lengths[-1]

    def rebuild(self, matcher: Matcher) -> None:
        level_zs, phase_lengths, eta = self._schedule(matcher)
        matcher.level_zs = level_zs
        matcher.level_phase_lengths = phase_lengths
        matcher.eta = eta
        matcher.k = len(level_zs)
        matcher.phase_length = self._phase_budget(matcher)
        previous = matcher.multi
        if (
            previous is not None
            and previous.levels
            and len(matcher.level_zs) > 1
            and (matcher.inserted_edges or matcher.deleted_edges)
        ):
            old_graph, base_system = _base_snapshot(matcher)
            matcher.multi = Hierarchy(
                graph=old_graph,
                k=1,
                levels=[base_system],
                A_levels=[set(base_system.A)],
                N_levels=[set(base_system.B)],
                R_levels=[set(base_system.U)],
                L_levels=[dict(base_system.L_lists)],
            )
            deleted = set(matcher.deleted_edges) | set(previous.deferred_deletions)
            inserted = set(matcher.inserted_edges)
            for z in matcher.level_zs[1:]:
                matcher.multi = refine_hierarchy(
                    matcher.multi,
                    z,
                    deleted=deleted,
                    inserted=inserted,
                    colorer=matcher.colorer,
                )
                deleted = set(matcher.multi.deferred_deletions)
        else:
            matcher.multi = build_hierarchy(
                matcher.graph, matcher.level_zs, colorer=matcher.colorer
            )
        matcher.inserted_edges.clear()
        matcher.deleted_edges.clear()
        matcher.inserted_incident_counts = {vertex: 0 for vertex in range(matcher.n)}
        matcher.bad_vertices.clear()

        if matcher.multi.levels:
            matcher.system = matcher.multi.levels[-1]
            matcher.z = level_zs[-1]
            matcher.subphase_length = max(1, matcher.phase_length // matcher.z)
            matcher.partition()
        else:
            matcher.system = None
            matcher.seed_matching = set()
            matcher.matchings = []

        matcher.refresh()
        if not matcher.multi.check():
            raise RuntimeError(
                "multilevel rebuild produced an invalid hierarchy; refusing to "
                "continue with stale recursive state"
            )
        if not matcher.maximal():
            raise RuntimeError(
                "multilevel rebuild produced a non-maximal matching; refusing "
                "to continue with stale state"
            )
        if not matcher.multi.check_i3(
            matcher.matched_edges, matcher.phase_length, matcher.z
        ):
            raise RuntimeError(
                "multilevel rebuild violated invariant I3; refusing to "
                "continue with stale recursive state"
            )
        matcher.phase_graph = _snapshot(matcher.multi.graph)
        matcher.update_count = 0
        matcher.subphase_count = 0
        matcher.accountant.record_phase_rebuild()
