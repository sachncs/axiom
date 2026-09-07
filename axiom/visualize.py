"""Visualization utilities for the z-subgraph system.

This module provides ASCII and text-based visualization of the
z-subgraph system state, useful for debugging and educational
purposes.  The output is plain text so it can be redirected to a file,
emailed, or diffed between runs.

**Engineering utility** -- not part of the paper's baseline algorithm.

Limitations:
    * All visualizations are designed for ``n <= ~100``; larger inputs
      produce very long reports.
    * The visualizations call the heavy invariant checks (e.g.
      ``System.check_all_invariants``) and therefore have
      ``O(n + m)`` cost on top of any printing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from axiom.core import Matcher
    from axiom.system import System


def visualize_system(system: System, width: int = 60) -> str:
    r"""Return an ASCII representation of the z-subgraph system.

    Shows the vertex partition ``(A, B, U)``, edges of ``M``, the
    per-vertex degree bars, the cached Lambda and L lists, and the
    result of every invariant check.

    Args:
        system: The z-subgraph system to visualize.
        width: Maximum line width for the output.

    Returns:
        A multi-line string with the visualization.

    Complexity:
        O(n + m) because every invariant check requires a full
        pass over the graph.
    """
    lines: list[str] = []
    separator = "=" * width

    lines.append(separator)
    lines.append("Z-SUBGRAPH SYSTEM VISUALIZATION")
    lines.append(separator)
    lines.append(f"  n = {system.graph.n}   z = {system.z}   |M| = {len(system.M)}")
    lines.append(
        f"  |A| = {len(system.A)}   |B| = {len(system.B)}   "
        f"|U| = {len(system.U)}   |S| = {len(system.S)}"
    )
    lines.append(separator)

    lines.append("\nVERTEX PARTITION:")
    lines.append(f"  A = {sorted(system.A)}")
    lines.append(f"  B = {sorted(system.B)}")
    lines.append(f"  U = {sorted(system.U)}")
    lines.append(f"  S = A ∪ B = {sorted(system.S)}")

    lines.append("\nDEGREES IN M:")
    for v in range(system.graph.n):
        deg = system.degree(v)
        partition = "A" if v in system.A else ("B" if v in system.B else "U")
        bar = "█" * deg
        lines.append(f"  v{v:3d} [{partition}] deg={deg:2d} {bar}")

    lines.append(f"\nEDGES IN M ({len(system.M)} edges):")
    for e in sorted(system.M):
        u, v = e
        lines.append(f"  ({u}, {v})")

    if system.lambda_lists:
        lines.append("\nΛ(u) LISTS (for u ∈ U):")
        for u in sorted(system.U):
            neighbors = system.lambda_lists.get(u, [])
            lines.append(f"  Λ({u}) = {neighbors}")

    if system.L_lists:
        lines.append("\nL(a) LISTS (for a ∈ A):")
        for a in sorted(system.A):
            neighbors = system.L_lists.get(a, [])
            lines.append(f"  L({a}) = {neighbors}")

    lines.append("\nINVARIANT CHECKS:")
    lines.append(f"  Degree bounds:   {'✓' if system.check_bound() else '✗'}")
    lines.append(f"  U-U degree:      {'✓' if system.check_u() else '✗'}")
    lines.append(f"  P1 (|N(u)∩B|≤2z): {'✓' if system.check_p1() else '✗'}")
    lines.append(f"  P2 (A→S in M):   {'✓' if system.check_p2() else '✗'}")
    lines.append(f"  Λ lists:         {'✓' if system.check_lambda() else '✗'}")
    lines.append(f"  L lists:         {'✓' if system.check_L() else '✗'}")
    lines.append(f"  ALL INVARIANTS:  {'✓' if system.check() else '✗'}")

    lines.append(separator)
    return "\n".join(lines)


def visualize_matching(algo: Matcher, width: int = 60) -> str:
    """Return an ASCII representation of the current matching state.

    Args:
        algo: The maximal matcher instance.
        width: Maximum line width (used for separators).

    Returns:
        A multi-line string with the visualization.

    Complexity:
        O(n + m + |M*|).
    """
    lines: list[str] = []
    separator = "=" * width

    lines.append(separator)
    lines.append("MATCHING STATE VISUALIZATION")
    lines.append(separator)
    lines.append(f"  n = {algo.n}   mode = {algo.mode}   z = {algo.z}")
    lines.append(
        f"  |E| = {algo.graph.num_edges()}   "
        f"|M*| = {len(algo.matched_edges)}   "
        f"maximal = {algo.maximal()}"
    )
    lines.append(f"  updates since rebuild = {algo.update_count}/{algo.phase_length}")
    lines.append(separator)

    lines.append("\nGRAPH EDGES:")
    for e in sorted(algo.graph.edges()):
        u, v = e
        in_matching = e in algo.matched_edges
        marker = " ★" if in_matching else ""
        lines.append(f"  ({u}, {v}){marker}")

    lines.append(f"\nMATCHING M* ({len(algo.matched_edges)} edges):")
    for e in sorted(algo.matched_edges):
        u, v = e
        lines.append(f"  ({u}, {v})")

    lines.append("\nVERTEX STATUS:")
    for v in range(algo.n):
        p = algo.partner(v)
        status = f"matched to {p}" if p is not None else "unmatched"
        lines.append(f"  v{v:3d}: {status}")

    stats = algo.stats()
    lines.append("\nSTATISTICS:")
    for key, value in stats.items():
        lines.append(f"  {key}: {value}")

    lines.append(separator)
    return "\n".join(lines)


def visualize_adjacency(algo: Matcher, width: int = 60) -> str:
    """Return an ASCII adjacency list representation of the graph.

    Args:
        algo: The maximal matcher instance.
        width: Maximum line width (used for separators).

    Returns:
        A multi-line string with the adjacency list.

    Complexity:
        O(n + m) to enumerate every neighbour.
    """
    lines: list[str] = []
    separator = "=" * width

    lines.append(separator)
    lines.append("GRAPH ADJACENCY LIST")
    lines.append(separator)

    for v in range(algo.n):
        neighbors = sorted(algo.graph.neighbors(v))
        matched_to = algo.partner(v)
        marker = f" [matched to {matched_to}]" if matched_to is not None else ""
        lines.append(f"  v{v:3d}: {neighbors}{marker}")

    lines.append(separator)
    return "\n".join(lines)
