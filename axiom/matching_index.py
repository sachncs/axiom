"""Sparse, set-like storage for canonical undirected edges."""

from __future__ import annotations

import sys
from collections.abc import Iterator, MutableSet
from types import NotImplementedType
from typing import cast

from axiom.capacity import JournalCapacityError


class MatchingIndex(MutableSet[tuple[int, int]]):
    """Store edge pairs as packed integer keys without vertex-sized arrays.

    The key reserves 32 bits for each endpoint, so storage grows with the
    number of edges rather than with the vertex universe. A conservative
    conservative per-key reservation rejects growth before the caller's byte
    budget can be reached. Current container and integer-key bytes are exposed
    by ``memory``.
    """

    key_reservation = 80

    def __init__(self, n: int, budget: int = 1_073_741_824) -> None:
        """Create an empty edge index for a fixed unsigned 32-bit universe."""
        if type(n) is not int:
            raise TypeError("vertex universe size must be an integer")
        if type(budget) is not int:
            raise TypeError("storage budget must be an integer")
        if not 0 <= n <= 1 << 32:
            raise ValueError("vertex universe must fit unsigned 32-bit labels")
        if budget < 0:
            raise ValueError("storage budget must be nonnegative")
        self.n = n
        self.budget = budget
        self.values: set[int] = set()
        self.active = False
        self.keybytes = 0

    def __len__(self) -> int:
        """Return the number of unique undirected edges."""
        return len(self.values)

    def __bool__(self) -> bool:
        """Return whether at least one edge is present."""
        return bool(self.values)

    def __iter__(self) -> Iterator[tuple[int, int]]:
        """Yield every canonical edge exactly once."""
        for value in self.values:
            yield self.decode(value)

    def __contains__(self, edge: object) -> bool:
        """Return whether a validated edge is present, in either orientation."""
        return self.encode(edge) in self.values

    def __eq__(self, other: object) -> bool:
        """Compare edge contents independent of orientation."""
        if isinstance(other, MatchingIndex):
            return self.n == other.n and self.values == other.values
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
        if value in self.values:
            return
        reserved = (
            sys.getsizeof(self.values) + (len(self.values) + 1) * self.key_reservation
        )
        if reserved > self.budget:
            raise JournalCapacityError("matching edge-index budget exceeded")
        self.values.add(value)
        self.keybytes += sys.getsizeof(value)

    def discard(self, edge: object) -> None:
        """Remove one edge if present; absent edges are ignored."""
        value = self.encode(edge)
        if value in self.values:
            self.values.remove(value)
            self.keybytes -= sys.getsizeof(value)

    def clear(self) -> None:
        """Remove all edges and release the set's reserved table."""
        if self.active:
            raise RuntimeError("cannot clear an edge index during a matching journal")
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
            return self.encode(edge) in self.values
        except (TypeError, ValueError):
            return False

    def copy(self) -> set[tuple[int, int]]:
        """Return a detached ordinary-set copy of the canonical edges."""
        return set(self)

    def memory(self) -> dict[str, int]:
        """Return current set/key bytes and the configured conservative budget."""
        return {
            "allocated": sys.getsizeof(self.values) + self.keybytes,
            "budget": self.budget,
            "edges": len(self.values),
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
