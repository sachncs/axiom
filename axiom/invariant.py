"""Invariant checkers for the :math:`z`-subgraph system and maximal matching.

These functions provide standalone validation that can be called from tests
or debugging scripts.  They do not modify state; they are read-only
diagnostics intended to make regressions visible immediately during
development.

Mathematical background:
    The :math:`z`-subgraph system carries six invariants whose conjunction
    guarantees the :math:`\tilde O(n^{2/3})` per-update cost of the
    basic algorithm (Section 2 of the paper).  They are validated
    individually by the methods of :class:`System` and bundled
    here so that external code (tests, benchmarks) can call a single
    entry point.

    Invariant (I3) for the multi-level system requires a precise
    constant that the paper excerpt omits; we therefore refuse to give
    a definitive answer rather than risk silently accepting a false
    positive.
"""

from __future__ import annotations

from axiom.hierarchy import Hierarchy
from axiom.system import System
from axiom.types import Graph, Matching, Vertex


def valid(system: System) -> bool:
    """Return ``True`` iff every invariant of ``system`` holds.

    Thin wrapper around :meth:`System.check_all_invariants`;
    surfaced as a module-level function so callers do not need to import
    the ``z_system`` module directly.

    Complexity:
        :math:`O(n + m)`.
    """
    return system.check()


def check_maximal_matching(graph: Graph, matching: Matching) -> bool:
    """Return ``True`` iff ``matching`` is maximal in ``graph``.

    A matching is maximal when no edge can be added to it without
    violating the matching property.  This is distinct from being of
    maximum cardinality: a maximal matching is a local optimum, not a
    global one.

    Args:
        graph: The host graph.
        matching: Candidate matching.

    Returns:
        ``True`` iff every unmatched vertex has only matched neighbours.

    Complexity:
        :math:`O(n + m)` -- each vertex is examined once and every
        edge of an unmatched vertex is inspected.
    """
    matched_vertices: set[Vertex] = set()
    for u, v in matching:
        matched_vertices.add(u)
        matched_vertices.add(v)

    for u in range(graph.n):
        if u in matched_vertices:
            continue
        for w in graph.neighbors(u):
            if w not in matched_vertices:
                return False
    return True


def check_i3(multi: Hierarchy, matching: Matching, r: int, z: int) -> bool:
    """Return ``True`` iff invariant (I3) is satisfied for ``multi``.

    Wraps :meth:`Hierarchy.check_i3` with the paper's :math:`2\\tau`
    constant (``\\tau = 32 r / z``).  See the docstring on
    :meth:`Hierarchy.check_i3` for the exact statement.

    Args:
        multi: The multi-level system.
        matching: The maintained maximal matching M*.
        r: The phase length.
        z: The :math:`z` parameter of the active level-1 system.

    Returns:
        ``True`` iff at most :math:`2\\tau` vertices of :math:`A_1` are
        matched by M* into :math:`R_1`.

    Complexity:
        :math:`O(|M^*|)`.
    """
    return multi.check_i3(matching, r, z)
