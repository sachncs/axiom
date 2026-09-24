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


def _copy_system(system: System, graph: Graph) -> System:
    """Copy a system state onto an isolated graph snapshot."""
    copied = System(
        graph=graph,
        z=system.z,
        A=set(system.A),
        B=set(system.B),
        U=set(system.U),
        M=set(system.M),
    )
    copied.index()
    return copied


def _with_edges(graph: Graph, edges: set[tuple[int, int]]) -> Graph:
    """Return a graph snapshot containing ``graph`` plus ``edges``."""
    result = _snapshot(graph)
    for left, right in edges:
        if not result.has_edge(left, right):
            result.add_edge(left, right)
    return result


def _base_snapshot(matcher: Matcher) -> tuple[Graph, System]:
    """Snapshot the inherited level-1 system for recursive refinement.

    The theorem-4.4 refinement requires a valid h-level input system.  The
    level-1 partition and matching are part of that input and must be
    inherited rather than rebuilt independently.  The graph is copied so the
    refinement can apply its deleted/inserted edge sets without mutating the
    live hierarchy.
    """
    assert matcher.multi is not None
    assert matcher.phase_base_graph is not None
    assert matcher.phase_base_system is not None
    # Keep the phase-start graph and its M edges intact: theorem 4.4 treats
    # ED as deletions from that input system and chooses the bounded subset
    # that may be deferred into the refined hierarchy.  Insertions remain in
    # EI and are supplied separately to ``refine_hierarchy``.
    # The authoritative input is the immutable phase-start snapshot.  It may
    # retain the bounded deferred-deletion set E_D' from the preceding
    # refinement; the live matcher graph intentionally does not contain
    # current-phase deletions.
    graph = _snapshot(matcher.phase_base_graph)
    previous = matcher.phase_base_system
    system = _copy_system(previous, graph)
    if not system.check():
        raise RuntimeError(
            "phase snapshot cannot inherit the previous level-1 system: "
            "its partition or matching is no longer valid"
        )
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

    @staticmethod
    def _validate_nested_schedule(
        level_zs: list[int], phase_lengths: list[int]
    ) -> None:
        """Reject schedules that do not encode the paper's binary nesting."""
        if len(level_zs) != len(phase_lengths) or not level_zs:
            raise RuntimeError("multilevel schedule has mismatched level state")
        if any(
            level_zs[index] <= 0 or phase_lengths[index] <= 0
            for index in range(len(level_zs))
        ):
            raise RuntimeError("multilevel schedule contains a non-positive value")
        for index in range(len(level_zs) - 1):
            if level_zs[index] != 2 * level_zs[index + 1]:
                raise RuntimeError(
                    "multilevel z schedule is not recursively halved: "
                    f"{level_zs[index]} -> {level_zs[index + 1]}"
                )
            if phase_lengths[index] != 2 * phase_lengths[index + 1]:
                raise RuntimeError(
                    "multilevel phase schedule is not binary nested: "
                    f"{phase_lengths[index]} -> {phase_lengths[index + 1]}"
                )

    @staticmethod
    def _reset_phase_clocks(matcher: Matcher) -> None:
        """Reset the nested clocks after a schedule change or first build."""
        matcher.level_phase_updates = [0 for _ in matcher.level_phase_lengths]
        matcher.level_phase_indices = [0 for _ in matcher.level_phase_lengths]

    @staticmethod
    def advance_phase_clocks(matcher: Matcher) -> None:
        """Advance every recursive level by one accepted graph update.

        A finest-level rebuild must not reset a parent phase.  The paper's
        level-i phases are nested, with each parent spanning an integral
        number of child phases.  Keeping one clock per level makes those
        boundaries explicit for the rebuild and invariant-maintenance code.
        """
        if len(matcher.level_phase_updates) != len(matcher.level_phase_lengths):
            Multilevel._reset_phase_clocks(matcher)
        for index, length in enumerate(matcher.level_phase_lengths):
            matcher.level_phase_updates[index] += 1
            if matcher.level_phase_updates[index] > length:
                raise RuntimeError(
                    "multilevel phase clock exceeded its configured boundary"
                )
            if matcher.level_phase_updates[index] == length:
                matcher.level_phase_indices[index] += 1
                matcher.level_phase_updates[index] = 0

    def configure(self, matcher: Matcher) -> None:
        level_zs, phase_lengths, eta = self._schedule(matcher)
        self._validate_nested_schedule(level_zs, phase_lengths)
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
        self._reset_phase_clocks(matcher)

    @staticmethod
    def _schedule(matcher: Matcher) -> tuple[list[int], list[int], int]:
        """Return the paper's density-sensitive recursive level schedule.

        The starting degree is the least power of two at least the current
        average degree.  Refinement then halves it until the finest level
        reaches the paper's ``sqrt(n) / (4 log n)`` threshold.
        """
        if matcher.n <= 1:
            return [1], [1], 1

        root_n = math.sqrt(matcher.n)
        eta = 1
        while eta < root_n:
            eta *= 2

        edge_count = matcher.graph.num_edges()
        if edge_count <= matcher.n * root_n:
            # Type-1 phases use the one-level construction with z=sqrt(n)
            # and span n updates.  Recursive refinement is reserved for the
            # dense type-2 regime, where rebuilding from the average degree
            # can be amortized over the longer phase hierarchy.
            z = max(1, math.ceil(root_n))
            return [z], [max(1, matcher.n)], eta

        average_degree = (2 * edge_count) / matcher.n
        required_z = max(1, math.ceil(average_degree))
        z = 1
        while z < required_z:
            z *= 2
        threshold = root_n / (4 * max(1.0, math.log2(matcher.n)))
        level_zs = [z]
        while z // 2 >= threshold and z > 1:
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
        previous_lengths = list(matcher.level_phase_lengths)
        level_zs, phase_lengths, eta = self._schedule(matcher)
        self._validate_nested_schedule(level_zs, phase_lengths)
        matcher.level_zs = level_zs
        matcher.level_phase_lengths = phase_lengths
        matcher.eta = eta
        matcher.k = len(level_zs)
        matcher.phase_length = self._phase_budget(matcher)
        schedule_changed = previous_lengths != phase_lengths or len(
            matcher.level_phase_updates
        ) != len(phase_lengths)
        if schedule_changed:
            self._reset_phase_clocks(matcher)
        parent_boundary = matcher.update_count > 0 and (
            len(level_zs) == 1
            or schedule_changed
            or any(value == 0 for value in matcher.level_phase_updates[:-1])
        )
        previous = matcher.multi
        previous_level_zs = (
            [level.z for level in previous.levels] if previous is not None else []
        )
        phase_base_graph: Graph
        phase_base_system: System
        if (
            previous is not None
            and previous.levels
            and previous_level_zs == matcher.level_zs
            and len(matcher.level_zs) > 1
            and (matcher.inserted_edges or matcher.deleted_edges)
        ):
            old_graph, base_system = _base_snapshot(matcher)
            deleted = set(matcher.deleted_edges) | set(previous.deferred_deletions)
            phase_base_graph = old_graph
            phase_base_system = _copy_system(base_system, old_graph)
            refine_graph = _with_edges(old_graph, deleted)
            working_base_system = _copy_system(base_system, refine_graph)
            matcher.multi = Hierarchy(
                graph=refine_graph,
                k=1,
                levels=[working_base_system],
                A_levels=[set(base_system.A)],
                N_levels=[set(base_system.B)],
                R_levels=[set(base_system.U)],
                L_levels=[dict(working_base_system.L_lists)],
            )
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
                # E_I is incorporated into the graph produced by this
                # refinement.  It is therefore part of the input graph for
                # the next recursive level, not a second insertion set.
                inserted = set()
        else:
            # Preserve the exact level-1 input before recursive refinement
            # rebinds retained levels to each narrower working graph.  This
            # is the inherited h-level system required by Theorem 4.4 for
            # the next recursive rebuild; rebuilding it would discard the
            # prior partition and matching state.
            phase_base_graph = _snapshot(matcher.graph)
            phase_base_system = build(phase_base_graph, matcher.level_zs[0])
            matcher.multi = build_hierarchy(
                phase_base_graph, matcher.level_zs, colorer=matcher.colorer
            )
        # Recursive refinement constructs the finest system on a selected
        # working subgraph.  The dynamic update pipeline owns a phase graph
        # consisting of live edges minus cumulative E_I, plus deferred E_D'.
        # E_D/E_I span child phases until their parent phase closes.
        assert matcher.multi is not None
        if parent_boundary:
            # The parent phase has closed: consume deferred deletions and
            # establish a new level-1 root over the current live graph.
            matcher.multi.deferred_deletions.clear()
            matcher.multi.sync_graph(matcher.graph)
            matcher.inserted_edges.clear()
            matcher.deleted_edges.clear()
            matcher.inserted_incident_counts = {
                vertex: 0 for vertex in range(matcher.n)
            }
            matcher.bad_vertices.clear()
        else:
            # A child phase rebuild keeps the inherited parent snapshot and
            # cumulative update sets.  Insertions remain outside the phase
            # graph until the parent boundary, exactly as E_I requires.
            matcher.multi.sync_graph(
                matcher.graph, excluded_edges=matcher.inserted_edges
            )

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
        if parent_boundary:
            next_base_graph = _snapshot(matcher.graph)
            next_base_system = build(next_base_graph, matcher.level_zs[0])
        else:
            next_base_graph = phase_base_graph
            next_base_system = phase_base_system
        matcher.phase_base_graph = next_base_graph
        matcher.phase_base_system = next_base_system
        if not next_base_system.check():
            raise RuntimeError(
                "multilevel rebuild produced an invalid inherited phase base"
            )
        matcher.update_count = 0
        matcher.subphase_count = 0
        matcher.accountant.record_phase_rebuild()
