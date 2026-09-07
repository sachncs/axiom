"""Shared type aliases and protocols used throughout the axiom package.

This module collects the minimal vocabulary used by every other module so
that downstream code can refer to a single canonical type definition
instead of restating ``tuple[int, int]`` or ``set[tuple[int, int]]`` in
many places.

Design notes:
    * Vertices are plain ``int`` labels rather than a wrapper class.  This
      keeps arithmetic cheap and lets the package interoperate naturally
      with NumPy arrays and other integer-keyed data structures used in
      benchmarks.
    * Edges are unordered and always stored in canonical form
      ``(min, max)`` so equality comparisons and set membership behave
      symmetrically regardless of call-site order.
    * Matchings are ``set[Edge]`` because the paper's algorithms rely on
      O(1) addition, removal, and membership tests when repairing a
      matching under dynamic updates.

Assumptions:
    * Vertex labels are dense and consecutive starting at ``0``; see
      :class:`axiom.graph.Adjacency` for the corresponding invariant.

Limitations:
    * No support for parallel edges or self-loops.  Callers must filter
      these out (or rely on :meth:`Adjacency.add_edge`) before
      constructing an :data:`Edge`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, TypeAlias, runtime_checkable

Vertex: TypeAlias = int
"""A vertex is represented by a non-negative integer."""

Edge: TypeAlias = tuple[Vertex, Vertex]
"""An undirected edge is an unordered pair of vertices.

For canonical ordering we enforce ``u < v`` internally where possible.
"""

Matching: TypeAlias = set[Edge]
"""A matching is a set of edges without common vertices."""

Color: TypeAlias = int
"""An edge color is represented by a non-negative integer."""

Coloring: TypeAlias = dict[Edge, Color]
"""A proper edge coloring maps each edge to a color."""


def canonical(u: Vertex, v: Vertex) -> Edge:
    """Return the canonical (unordered) representation of an edge.

    Args:
        u: One endpoint.
        v: The other endpoint.

    Returns:
        A tuple ``(min, max)`` so that ``u < v``.

    Examples:
        >>> canonical(3, 1)
        (1, 3)
        >>> canonical(2, 5) == canonical(5, 2)
        True
    """
    if u < v:
        return (u, v)
    return (v, u)


@runtime_checkable
class Graph(Protocol):
    """Protocol defining the interface for graph implementations.

    Any graph used by the matching algorithm must implement this protocol.
    The default implementation is :class:`axiom.graph.Adjacency`.
    """

    @property
    def n(self) -> int:
        """Number of vertices in the graph."""
        ...

    def add_edge(self, u: Vertex, v: Vertex) -> None:
        """Insert an undirected edge (u, v).

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        ...

    def remove_edge(self, u: Vertex, v: Vertex) -> None:
        """Delete an undirected edge (u, v).

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        ...

    def has_edge(self, u: Vertex, v: Vertex) -> bool:
        """Return True iff the edge (u, v) exists.

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        ...

    def degree(self, v: Vertex) -> int:
        """Return the degree of vertex v.

        Args:
            v: The vertex.
        """
        ...

    def neighbors(self, v: Vertex) -> Iterator[Vertex]:
        """Iterate over the neighbours of v.

        Args:
            v: The vertex.

        Yields:
            Neighbour vertices.
        """
        ...

    def edges(self) -> Iterator[Edge]:
        """Iterate over all edges in the graph exactly once.

        Yields:
            Canonical edges (u, v) with u < v.
        """
        ...

    def num_edges(self) -> int:
        """Return the number of edges in the graph."""
        ...


@runtime_checkable
class Colorer(Protocol):
    """Protocol defining the interface for edge coloring algorithms.

    Any edge coloring implementation must produce a proper coloring using
    at most delta + 1 colors.  Two implementations are provided:
    :class:`axiom.color.Greedy` and
    :class:`axiom.color.Vizing`.
    """

    def color(self, graph: Graph, delta: int) -> Coloring:
        """Return a proper edge coloring of the graph.

        Args:
            graph: The graph to color.
            delta: An upper bound on the maximum degree.

        Returns:
            A dictionary mapping each canonical edge to its color.
        """
        ...
