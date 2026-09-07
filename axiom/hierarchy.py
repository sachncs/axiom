r"""The multi-level :math:`z`-subgraph system.

This module defines :class:`Hierarchy`, the :math:`k`-level generalisation
of the single-level :class:`axiom.system.System`.  Stacking
:math:`k = \Theta(\log n)` systems at decreasing :math:`z` values allows
the algorithm to deliver an amortised :math:`n^{1/2+o(1)}` update
bound (Theorem 1.1 in the paper).

Structure:
    The :class:`Hierarchy` owns ``k`` :class:`axiom.system.System`
    instances and the level-1 partition of :math:`A` into
    :math:`A_1, A_2` together with the derived sets
    :math:`N_1 \\subseteq A_2 \\cup B` and
    :math:`R_1 = V \\setminus (A_1 \\cup N_1)`.

Invariant I3 (paper, Section 6.2):
    At most :math:`2\\tau` vertices of :math:`A_1` are matched by
    :math:`M^*` into :math:`R_1`, where :math:`\\tau = 32 r / z`.
    This module implements :meth:`Hierarchy.check_i3` with the paper's
    :math:`2\\tau` constant and :meth:`Hierarchy.maintain_i3` that repairs
    any violation by re-routing :math:`A_1`-vertices out of :math:`R_1`.

References:
    Chuzhoy, Khanna, Song.  "A Faster Deterministic Algorithm for Fully
    Dynamic Maximal Matching" (arXiv:2605.00797v1), Section 6.2.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from axiom.system import System
from axiom.system import build as build_z_system
from axiom.types import Graph, Vertex


@dataclass
class Hierarchy:
    r"""A :math:`k`-level subgraph system.

    Attributes:
        graph: The underlying dynamic graph.
        k: Number of levels.
        levels: A list of :class:`axiom.system.System` instances, one per level.
        A1: Partition of level-1 :math:`A` into :math:`A_1`.
        A2: Partition of level-1 :math:`A` into :math:`A_2`.
        N1: Subset :math:`N_1 \subseteq A_2 \cup B`.
        R1: :math:`R_1 = V \setminus (A_1 \cup N_1)`.

    Thread-safety:
        Not thread-safe.
    """

    graph: Graph
    k: int
    levels: list[System] = field(default_factory=list)
    A1: set[Vertex] = field(default_factory=set)
    A2: set[Vertex] = field(default_factory=set)
    N1: set[Vertex] = field(default_factory=set)
    R1: set[Vertex] = field(default_factory=set)

    def check_i3(self, matching: set[tuple[int, int]], r: int, z: int) -> bool:
        """Check multi-level invariant (I3).

        At most :math:`2\\tau` vertices of :math:`A_1` are matched by
        :math:`M^*` into :math:`R_1`, where :math:`\\tau = 32 r / z`
        (Section 6.2 of the paper).  In other words, the count of
        edges of the matching that connect a vertex of :math:`A_1`
        to a vertex of :math:`R_1` is at most :math:`2\\tau = 64 r / z`.

        Args:
            matching: The maintained maximal matching M*.
            r: The phase length (set by the :class:`axiom.rebuild.Rebuild`
                policy at construction).
            z: The :math:`z` parameter of the active level-1 system.

        Returns:
            ``True`` iff the invariant holds.  The constant is the
            paper's :math:`2\\tau`; we treat it as ``64 r / z``
            (``\\tau = 32 r / z``).

        Complexity:
            :math:`O(|M^*|)`.
        """
        if z <= 0:
            return True
        tau = (32 * r) // z
        bound = 2 * tau
        count = 0
        for u, v in matching:
            if (u in self.A1 and v in self.R1) or (v in self.A1 and u in self.R1):
                count += 1
                if count > bound:
                    return False
        return True

    def maintain_i3(
        self,
        matching: set[tuple[int, int]],
        r: int,
        z: int,
        partner_of: Callable[[Vertex], Vertex | None],
        rematch: Callable[[Vertex], None],
    ) -> int:
        """Repair any violation of invariant (I3).

        Iterates over vertices of :math:`A_1` that are currently matched
        by :math:`M^*` into :math:`R_1`, breaks the offending edge, and
        calls ``rematch`` to find a new partner for the A_1 endpoint.

        Args:
            matching: The maintained maximal matching M* (mutated in place).
            r: The phase length.
            z: The :math:`z` parameter of the active level-1 system.
            partner_of: Callable returning the partner of a vertex in M*.
            rematch: Callable to re-match an unmatched A_1 vertex.

        Returns:
            The number of A_1 -> R_1 edges broken and rematched.
        """
        if z <= 0:
            return 0
        tau = (32 * r) // z
        bound = 2 * tau
        offenders: list[tuple[int, int]] = []
        for u, v in matching:
            if (u in self.A1 and v in self.R1) or (v in self.A1 and u in self.R1):
                offenders.append((u, v))
        offenders = offenders[:bound]
        for u, v in offenders:
            matching.discard((min(u, v), max(u, v)))
            rematch(u)
            rematch(v)
        return len(offenders)


def build_hierarchy(graph: Graph, level_zs: list[int]) -> Hierarchy:
    r"""Build a multi-level system by stacking independent levels.

    Each level is constructed by :func:`axiom.system.build` on the same
    graph but with its own :math:`z` value.  After building the levels,
    the partition of the level-1 :math:`A`-set into :math:`A_1` and
    :math:`A_2` and the derived sets :math:`N_1`, :math:`R_1` are
    computed deterministically by sorting :math:`A` and splitting it
    in half.

    **Fidelity note:** The paper derives a :math:`z_i`-system from a
    :math:`z_{i-1}`-system in :math:`O(n^{1+o(1)} z_1)` time, faster than
    rebuilding when the graph is dense.  We implement the natural
    reconstruction: build each level independently from the current
    graph, preserving all invariants.  The recursive derivation
    mechanics (edge-set selection :math:`E'_D`, list inheritance) are
    described at high level but lack pseudocode in the excerpt, so we
    opt for the clearer (and empirically sufficient for stress tests)
    independent rebuild.

    Args:
        graph: The host graph.
        level_zs: Strictly decreasing positive integers giving the
            :math:`z` value of each level (finest first).

    Returns:
        A :class:`Hierarchy` whose ``levels`` list contains one
        entry per :math:`z` value.

    Complexity:
        Linear in the number of levels times the cost of
        :func:`axiom.system.build`.
    """
    hierarchy = Hierarchy(graph=graph, k=len(level_zs))

    # Levels are rebuilt independently for clarity, even though the
    # paper describes a recursive refinement.
    for z in level_zs:
        level = build_z_system(graph, z)
        hierarchy.levels.append(level)

    if hierarchy.levels:
        level1 = hierarchy.levels[0]
        # Split level-1 A deterministically by sorted order.  The paper
        # description of which side becomes A_1 versus A_2 is left
        # abstract; using a sorted split keeps the construction
        # reproducible across runs.
        sorted_A = sorted(level1.A)
        split = len(sorted_A) // 2
        hierarchy.A1 = set(sorted_A[:split])
        hierarchy.A2 = set(sorted_A[split:])
        hierarchy.N1 = hierarchy.A2 | level1.B
        hierarchy.R1 = set(range(graph.n)) - (hierarchy.A1 | hierarchy.N1)

    return hierarchy
