"""Set-like storage for canonical undirected edges using native ``Packed`` graphs.

Unlike a partner array, this index represents any simple-edge set, including
candidate sets with multiple edges incident to the same vertex. Matching
validity remains a separate invariant for callers to audit.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableSet

from axiom.storage import Packed


class MatchingIndex(MutableSet[tuple[int, int]]):
    """A mutable edge set over a fixed vertex universe.

    The native graph owns the sparse edge topology. Each undirected edge is
    stored once per endpoint internally, while iteration yields each canonical
    ``(u, v)`` with ``u < v`` exactly once.

    ``budget`` is the native storage budget in bytes. At one million vertices,
    the backing store uses its native vertex metadata plus storage proportional
    to live edges and reserved edge blocks; it does not allocate Python edge
    tuples or a dense partner array. Exact memory depends on the native block
    allocator and the number/distribution of edges; inspect ``memory()`` for
    the current allocated capacity.

    The index deliberately permits overlapping edges. A partner array would
    save memory for valid matchings but could not represent invalid candidate
    sets for independent invariant checks, so this general set uses sparse
    graph storage instead.
    """

    def __init__(self, n: int, budget: int = 1_073_741_824) -> None:
        """Create an empty index for vertices ``0`` through ``n - 1``."""
        if type(n) is not int:
            raise TypeError("vertex universe size must be an integer")
        if type(budget) is not int:
            raise TypeError("storage budget must be an integer")
        if n < 0:
            raise ValueError("vertex universe size must be nonnegative")
        if budget < 0:
            raise ValueError("storage budget must be nonnegative")
        self.n = n
        self.graph = Packed(n, budget=budget)

    def __len__(self) -> int:
        """Return the number of unique edges."""
        return self.graph.num_edges()

    def __bool__(self) -> bool:
        """Return whether at least one edge is stored."""
        return len(self) != 0

    def __iter__(self) -> Iterator[tuple[int, int]]:
        """Yield every edge once in canonical endpoint order."""
        return self.graph.edges()

    def __contains__(self, edge: object) -> bool:
        """Return whether a validated undirected edge is present."""
        left, right = self.validate(edge)
        return self.graph.has_edge(left, right)

    def __eq__(self, other: object) -> bool:
        """Compare contents independent of edge orientation and iteration order."""
        if isinstance(other, MatchingIndex):
            return len(self) == len(other) and all(edge in other for edge in self)
        if isinstance(other, (set, frozenset)):
            if len(self) != len(other):
                return False
            return all(self.contains(other_edge) for other_edge in other)
        return NotImplemented

    def __le__(self, other: object) -> bool:
        """Return whether this edge set is a subset of another set-like value."""
        if not isinstance(other, (MatchingIndex, set, frozenset)):
            return NotImplemented
        return len(self) <= len(other) and all(
            self.containsin(other, edge) for edge in self
        )

    def __ge__(self, other: object) -> bool:
        """Return whether this edge set is a superset of another set-like value."""
        if not isinstance(other, (MatchingIndex, set, frozenset)):
            return NotImplemented
        return len(self) >= len(other) and all(self.contains(edge) for edge in other)

    def add(self, edge: object) -> None:
        """Add an edge; adding an existing undirected edge is a no-op."""
        left, right = self.validate(edge)
        self.graph.add_edge(left, right)

    def discard(self, edge: object) -> None:
        """Remove an edge if present; absent edges are ignored."""
        left, right = self.validate(edge)
        self.graph.remove_edge(left, right)

    def clear(self) -> None:
        """Remove all edges while retaining the allocated graph container."""
        if self.graph.memory()["active"]:
            raise RuntimeError("cannot clear an edge index during a native journal")
        self.graph = self.graph.empty()

    def contains(self, edge: object) -> bool:
        """Test edge presence while treating malformed comparison keys as absent."""
        try:
            left, right = self.validate(edge)
        except (TypeError, ValueError):
            return False
        return self.graph.has_edge(left, right)

    @staticmethod
    def containsin(other: object, edge: tuple[int, int]) -> bool:
        """Check a canonical edge against a set or another edge index."""
        if isinstance(other, MatchingIndex):
            return edge in other
        if isinstance(other, (set, frozenset)):
            return edge in other or (edge[1], edge[0]) in other
        return False

    def validate(self, edge: object) -> tuple[int, int]:
        """Validate a two-label edge and return its canonical orientation."""
        if not isinstance(edge, (tuple, list)) or len(edge) != 2:
            raise TypeError("edge must be a two-element tuple or list")
        left, right = edge
        if type(left) is not int or type(right) is not int:
            raise TypeError("edge labels must be integers")
        if left < 0 or right < 0:
            raise ValueError("edge labels must be nonnegative")
        if left >= self.n or right >= self.n:
            raise ValueError("edge label is outside the vertex universe")
        if left == right:
            raise ValueError("self-loops are not allowed")
        return (left, right) if left < right else (right, left)
