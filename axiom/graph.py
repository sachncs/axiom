r"""Adjacency-set graph layer.

**Fidelity note:** The paper states that adjacency lists are stored as binary
search trees to support :math:`O(\log n)` insertion, deletion, and lookup.
In this Python reproduction we use the built-in ``set`` type, which provides
amortised :math:`O(1)` operations.  The asymptotic guarantees of the
algorithm are preserved; only the hidden constant factors differ.

Responsibilities:
    * Maintain the live edge set under online insertions and deletions.
    * Provide neighbour and edge iterators that yield every edge exactly
      once in canonical form.
    * Validate vertex labels and reject invalid inputs early.

Interactions:
    * Used as the storage layer by the dynamic matcher in
      :mod:`axiom.core`.
    * The greedy matching helpers in :mod:`axiom.matching` read only.
    * The :mod:`axiom.system` and :mod:`axiom.hierarchy` modules read
      adjacency when reconstructing :math:`\Lambda` and :math:`L` lists.

Thread-safety:
    * Instances are **not** thread-safe.  Each :class:`axiom.core.Matcher`
      owns one :class:`Adjacency` and is intended to be used from a single
      thread.  Concurrent access would require external locking.
"""

from __future__ import annotations

from collections.abc import Iterator

from axiom.types import Edge, Vertex


class Adjacency:
    """A simple undirected graph that supports dynamic edge insertions and deletions.

    Vertices are dense integer labels ``0 .. n-1`` fixed at construction.
    Self-loops are silently ignored (or rejected when ``strict=True``).
    Each undirected edge is stored once in the adjacency set of both
    endpoints, but iteration yields the canonical form ``(u, v)`` with
    ``u < v`` so callers see every edge exactly once.

    Attributes:
        n: Number of vertices (fixed at construction).
        adj: ``adj[v]`` is the set of neighbours of ``v``.
        edge_count: Number of edges currently in the graph.
    """

    def __init__(self, n: int) -> None:
        """Initialise an empty graph on ``n`` vertices labelled ``0 … n-1``.

        Args:
            n: Number of vertices.  Must be non-negative.

        Raises:
            ValueError: If ``n`` is negative.

        Complexity:
            ``O(n)`` time and space for the adjacency list of empty sets.
        """
        if n < 0:
            raise ValueError(f"n must be non-negative, got {n}")
        self.n: int = n
        self.adj: list[set[Vertex]] = [set() for _ in range(n)]
        self.edge_count: int = 0

    def add_edge(self, u: Vertex, v: Vertex, *, strict: bool = False) -> None:
        r"""Insert an undirected edge ``(u, v)``.

        Duplicate insertions are silently ignored unless ``strict`` is ``True``.

        Args:
            u: One endpoint.
            v: The other endpoint.
            strict: If ``True``, raise on self-loops or duplicate edges.

        Raises:
            ValueError: If either endpoint is out of range, or if ``strict``
                is ``True`` and the edge is a self-loop or already exists.

        Complexity:
            Amortised :math:`O(1)` thanks to hash-based sets.  In the
            paper's intended implementation using balanced BSTs this
            would be :math:`O(\log n)`.
        """
        self.validate_vertex(u)
        self.validate_vertex(v)
        if u == v:
            if strict:
                raise ValueError("Self-loops are not allowed")
            return
        added = v not in self.adj[u]
        if not added:
            if strict:
                raise ValueError(f"Edge ({u}, {v}) already exists")
            return
        self.adj[u].add(v)
        self.adj[v].add(u)
        self.edge_count += 1

    def remove_edge(self, u: Vertex, v: Vertex, *, strict: bool = False) -> None:
        """Delete an undirected edge ``(u, v)``.

        Deleting a non-existent edge is silently ignored unless ``strict`` is ``True``.
        Self-loops are symmetrically a no-op with :meth:`add_edge`: removed
        silently under default mode and rejected when ``strict=True``.

        Args:
            u: One endpoint.
            v: The other endpoint.
            strict: If ``True``, raise when the edge does not exist.

        Raises:
            ValueError: If either endpoint is out of range, if the edge is a
                self-loop and ``strict`` is ``True``, or if the edge does
                not exist and ``strict`` is ``True``.

        Complexity:
            Amortised :math:`O(1)`; see :meth:`add_edge` for context.
        """
        self.validate_vertex(u)
        self.validate_vertex(v)
        if u == v:
            if strict:
                raise ValueError("Self-loops are not allowed")
            return
        removed = v in self.adj[u]
        if not removed:
            if strict:
                raise ValueError(f"Edge ({u}, {v}) does not exist")
            return
        self.adj[u].discard(v)
        self.adj[v].discard(u)
        self.edge_count -= 1

    def has_edge(self, u: Vertex, v: Vertex) -> bool:
        """Return ``True`` iff the edge ``(u, v)`` exists.

        Args:
            u: One endpoint.
            v: The other endpoint.

        Raises:
            ValueError: If either endpoint is out of range.

        Complexity:
            Amortised :math:`O(1)`.
        """
        self.validate_vertex(u)
        self.validate_vertex(v)
        return v in self.adj[u]

    def degree(self, v: Vertex) -> int:
        """Return the degree of vertex ``v``.

        Args:
            v: The vertex.

        Raises:
            ValueError: If ``v`` is out of range.

        Complexity:
            :math:`O(1)`.
        """
        self.validate_vertex(v)
        return len(self.adj[v])

    def neighbors(self, v: Vertex) -> Iterator[Vertex]:
        r"""Iterate over the neighbours of ``v``.

        Args:
            v: The vertex.

        Yields:
            Neighbour vertices.

        Raises:
            ValueError: If ``v`` is out of range.

        Complexity:
            :math:`O(\deg(v))` to drain the iterator.
        """
        self.validate_vertex(v)
        yield from self.adj[v]

    def edges(self) -> Iterator[Edge]:
        """Iterate over all edges in the graph exactly once.

        Yields:
            Canonical edges ``(u, v)`` with ``u < v``.

        Complexity:
            :math:`O(m)` to enumerate every edge, where :math:`m = |E|`.
            The ``u < v`` guard avoids double-counting symmetric pairs.
        """
        for u in range(self.n):
            for v in self.adj[u]:
                if u < v:
                    yield (u, v)

    def num_edges(self) -> int:
        """Return the number of edges in the graph.

        Complexity:
            :math:`O(1)`.  We cache the count on every update rather than
            summing degrees, which would be :math:`O(n)`.
        """
        return self.edge_count

    def validate_vertex(self, v: Vertex) -> None:
        """Validate that ``v`` is in the range ``[0, n)``.

        Raises:
            ValueError: If ``v`` is out of range.
        """
        if not (0 <= v < self.n):
            raise ValueError(f"Vertex {v} out of range [0, {self.n})")

    def copy(self) -> Adjacency:
        """Return a shallow copy of the graph.

        The new instance owns fresh adjacency sets; mutating either graph
        afterwards does not affect the other.

        Complexity:
            :math:`O(n + m)` because every adjacency set must be cloned.
        """
        g = Adjacency(self.n)
        for u in range(self.n):
            g.adj[u] = set(self.adj[u])
        g.edge_count = self.edge_count
        return g
