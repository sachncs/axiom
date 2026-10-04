"""Sparse, set-like storage for canonical undirected edges."""

from __future__ import annotations

import sys
from array import array
from collections.abc import Iterator, MutableSet
from types import NotImplementedType
from typing import cast

from axiom.capacity import JournalCapacityError


class MatchingIndex(MutableSet[tuple[int, int]]):
    """Store canonical edges sparsely, or use partner rows for matchings.

    The general mode packs both endpoints into one integer key, so storage
    grows with the edge count. ``enable_disjoint`` replaces ordinary matching
    edges with a compact partner row per vertex; any overlapping edges are
    retained in a sparse overflow set so audits can still represent invalid
    candidates. Sparse growth is admitted against a conservative byte budget.
    """

    key_reservation = 80

    def __init__(
        self,
        n: int,
        budget: int = 1_073_741_824,
        *,
        disjoint: bool = False,
    ) -> None:
        """Create an empty edge index for a fixed unsigned 32-bit universe."""
        if type(n) is not int:
            raise TypeError("vertex universe size must be an integer")
        if type(budget) is not int:
            raise TypeError("storage budget must be an integer")
        if not 0 <= n <= 1 << 32:
            raise ValueError("vertex universe must fit unsigned 32-bit labels")
        if budget < 0:
            raise ValueError("storage budget must be nonnegative")
        if type(disjoint) is not bool:
            raise TypeError("disjoint must be a boolean")
        self.n = n
        self.budget = budget
        self.values: set[int] = set()
        self._partners: array[int] | None = None
        self._size = 0
        self.active = False
        self.keybytes = 0
        if disjoint:
            self.enable_disjoint()

    def enable_disjoint(self) -> None:
        """Use compact partner rows for disjoint edges and a sparse overflow set."""
        if self.active or self.values or self._partners is not None:
            raise RuntimeError("disjoint storage requires an empty inactive index")
        if self.n >= 0xFFFFFFFF or self.n * 4 > self.budget:
            raise JournalCapacityError(
                "disjoint matching partner index exceeds its budget"
            )
        partners = array("I", [0xFFFFFFFF]) * self.n
        if partners.itemsize != 4:
            raise RuntimeError("platform does not provide a 32-bit unsigned array")
        self._partners = partners

    def __len__(self) -> int:
        """Return the number of unique undirected edges."""
        return self._size + len(self.values)

    def __bool__(self) -> bool:
        """Return whether at least one edge is present."""
        return len(self) != 0

    def __iter__(self) -> Iterator[tuple[int, int]]:
        """Yield every canonical edge exactly once."""
        if self._partners is not None:
            for left, right in enumerate(self._partners):
                if right != 0xFFFFFFFF and left < right:
                    yield left, right
            for value in self.values:
                yield self.decode(value)
            return
        for value in self.values:
            yield self.decode(value)

    def __contains__(self, edge: object) -> bool:
        """Return whether a validated edge is present, in either orientation."""
        value = self.encode(edge)
        if self._partners is not None:
            left, right = self.decode(value)
            return (
                self._partners[left] == right and self._partners[right] == left
            ) or value in self.values
        return value in self.values

    def __eq__(self, other: object) -> bool:
        """Compare edge contents independent of orientation."""
        if isinstance(other, MatchingIndex):
            return (
                self.n == other.n
                and len(self) == len(other)
                and all(edge in other for edge in self)
            )
        if isinstance(other, (set, frozenset)):
            return len(self) == len(other) and all(
                self.contains(edge) for edge in other
            )
        return NotImplemented

    def __le__(self, other: object) -> bool:
        """Return whether this edge index is a subset of a supported set."""
        if not isinstance(other, (MatchingIndex, set, frozenset)):
            return NotImplemented
        return len(self) <= len(other) and all(self.contains(edge) for edge in self)

    def __ge__(self, other: object) -> bool:
        """Return whether this edge index is a superset of a supported set."""
        if not isinstance(other, (MatchingIndex, set, frozenset)):
            return NotImplemented
        return len(self) >= len(other) and all(self.contains(edge) for edge in other)

    def __or__(self, other: object) -> set[tuple[int, int]] | NotImplementedType:
        """Return an ordinary set containing edges from either operand."""
        if isinstance(other, MatchingIndex):
            other = set(other)
        if isinstance(other, (set, frozenset)):
            return set(self) | cast(set[tuple[int, int]], set(other))
        return NotImplemented

    def __ror__(self, other: object) -> set[tuple[int, int]] | NotImplementedType:
        """Support ordinary edge-set union when this index is on the right."""
        if isinstance(other, (set, frozenset)):
            return cast(set[tuple[int, int]], set(other)) | set(self)
        return NotImplemented

    def __and__(self, other: object) -> set[tuple[int, int]] | NotImplementedType:
        """Return common edges as an ordinary set."""
        if isinstance(other, MatchingIndex):
            other = set(other)
        if isinstance(other, (set, frozenset)):
            return set(self) & cast(set[tuple[int, int]], set(other))
        return NotImplemented

    def __rand__(self, other: object) -> set[tuple[int, int]] | NotImplementedType:
        """Support ordinary edge-set intersection with this index on the right."""
        if isinstance(other, (set, frozenset)):
            return cast(set[tuple[int, int]], set(other)) & set(self)
        return NotImplemented

    def __sub__(self, other: object) -> set[tuple[int, int]] | NotImplementedType:
        """Return this index's edges absent from the other set."""
        if isinstance(other, MatchingIndex):
            other = set(other)
        if isinstance(other, (set, frozenset)):
            return set(self) - cast(set[tuple[int, int]], set(other))
        return NotImplemented

    def __rsub__(self, other: object) -> set[tuple[int, int]] | NotImplementedType:
        """Support ordinary edge-set difference with this index on the right."""
        if isinstance(other, (set, frozenset)):
            return cast(set[tuple[int, int]], set(other)) - set(self)
        return NotImplemented

    def __xor__(self, other: object) -> set[tuple[int, int]] | NotImplementedType:
        """Return edges present in exactly one operand."""
        if isinstance(other, MatchingIndex):
            other = set(other)
        if isinstance(other, (set, frozenset)):
            return set(self) ^ cast(set[tuple[int, int]], set(other))
        return NotImplemented

    def __rxor__(self, other: object) -> set[tuple[int, int]] | NotImplementedType:
        """Support ordinary symmetric difference with this index on the right."""
        if isinstance(other, (set, frozenset)):
            return cast(set[tuple[int, int]], set(other)) ^ set(self)
        return NotImplemented

    def add(self, edge: object) -> None:
        """Add one edge unless doing so would exceed the conservative budget."""
        value = self.encode(edge)
        if self._partners is not None:
            left, right = self.decode(value)
            if self._partners[left] == right and self._partners[right] == left:
                return
            if value in self.values:
                return
            if (
                self._partners[left] == 0xFFFFFFFF
                and self._partners[right] == 0xFFFFFFFF
            ):
                self._partners[left] = right
                self._partners[right] = left
                self._size += 1
            else:
                self._add_sparse(value)
            return
        if value in self.values:
            return
        self._add_sparse(value)

    def _add_sparse(self, value: int) -> None:
        """Add an overflow/general edge key after accounting for dense rows."""
        if value in self.values:
            return
        dense_bytes = sys.getsizeof(self._partners) if self._partners is not None else 0
        reserved = (
            dense_bytes
            + sys.getsizeof(self.values)
            + (len(self.values) + 1) * self.key_reservation
        )
        if reserved > self.budget:
            raise JournalCapacityError("matching edge-index budget exceeded")
        self.values.add(value)
        self.keybytes += sys.getsizeof(value)

    def discard(self, edge: object) -> None:
        """Remove one edge if present; absent edges are ignored."""
        value = self.encode(edge)
        if self._partners is not None:
            left, right = self.decode(value)
            if value in self.values:
                self.values.remove(value)
                self.keybytes -= sys.getsizeof(value)
                self._promote_overflow()
                return
            if self._partners[left] == right and self._partners[right] == left:
                self._partners[left] = 0xFFFFFFFF
                self._partners[right] = 0xFFFFFFFF
                self._size -= 1
            self._promote_overflow()
            return
        if value in self.values:
            self.values.remove(value)
            self.keybytes -= sys.getsizeof(value)

    def _promote_overflow(self) -> None:
        """Move overflow edges into vacant partner rows after conflicts clear."""
        if self._partners is None or not self.values:
            return
        for value in tuple(self.values):
            left, right = self.decode(value)
            if (
                self._partners[left] == 0xFFFFFFFF
                and self._partners[right] == 0xFFFFFFFF
            ):
                self.values.remove(value)
                self.keybytes -= sys.getsizeof(value)
                self._partners[left] = right
                self._partners[right] = left
                self._size += 1

    def clear(self) -> None:
        """Remove all edges and release the set's reserved table."""
        if self.active:
            raise RuntimeError("cannot clear an edge index during a matching journal")
        if self._partners is not None:
            for vertex in range(self.n):
                self._partners[vertex] = 0xFFFFFFFF
            self._size = 0
            self.values.clear()
            self.keybytes = 0
            return
        self.values.clear()
        self.keybytes = 0

    def begin(self) -> None:
        """Protect the edge root from unjournaled bulk replacement."""
        if self.active:
            raise RuntimeError("matching edge journal is already active")
        self.active = True

    def commit(self) -> None:
        """Close the active edge journal after all touched cells are accepted."""
        if not self.active:
            raise RuntimeError("matching edge journal is not active")
        self.active = False

    def rollback(self) -> None:
        """Close the active edge journal after touched cells have been restored."""
        if not self.active:
            raise RuntimeError("matching edge journal is not active")
        self.active = False

    def contains(self, edge: object) -> bool:
        """Check membership while treating malformed comparison keys as absent."""
        try:
            return edge in self
        except (TypeError, ValueError):
            return False

    def copy(self) -> set[tuple[int, int]]:
        """Return a detached ordinary-set copy of the canonical edges."""
        return set(self)

    def memory(self) -> dict[str, int]:
        """Return current set/key bytes and the configured conservative budget."""
        return {
            "allocated": (
                sys.getsizeof(self._partners)
                + sys.getsizeof(self.values)
                + self.keybytes
                if self._partners is not None
                else sys.getsizeof(self.values) + self.keybytes
            ),
            "budget": self.budget,
            "edges": len(self),
        }

    def encode(self, edge: object) -> int:
        """Validate an edge and encode its canonical endpoints as one integer."""
        if not isinstance(edge, (tuple, list)) or len(edge) != 2:
            raise TypeError("edge must be a two-element tuple or list")
        left, right = edge
        if type(left) is not int or type(right) is not int:
            raise TypeError("edge labels must be integers")
        if not 0 <= left < self.n or not 0 <= right < self.n:
            raise ValueError("edge label is outside the vertex universe")
        if left == right:
            raise ValueError("self-loops are not allowed")
        if left > right:
            left, right = right, left
        return (left << 32) | right

    @staticmethod
    def decode(value: int) -> tuple[int, int]:
        """Decode a packed edge key into canonical endpoints."""
        return value >> 32, value & 0xFFFFFFFF
