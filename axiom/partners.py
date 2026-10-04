"""Compact array-backed mapping from vertices to their matching partners."""

from __future__ import annotations

from array import array
from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from typing import TypeVar, overload

Key = TypeVar("Key")
Missing = object()


class Partners(MutableMapping[int, int]):
    """Store partner indices in a fixed-size signed 32-bit array.

    A value of ``-1`` means that a vertex is currently unmatched. Keys and
    partners are validated independently; self-pairs are allowed because this
    container represents cells, not graph or matching invariants.

    Args:
        n: Number of vertices in the fixed universe.
        mapping: Optional initial key-to-partner values.

    Raises:
        TypeError: If ``n`` or a key/partner is not an exact integer.
        ValueError: If a size or vertex is outside the supported range.
    """

    def __init__(
        self,
        n: int,
        mapping: Mapping[int, int] | Iterable[tuple[int, int]] | None = None,
    ):
        """Create an empty mapping, optionally populated from key/value pairs."""
        if type(n) is not int:
            raise TypeError("vertex universe size must be an integer")
        if n < 0:
            raise ValueError("vertex universe size must be nonnegative")
        if n > 2**31:
            raise ValueError("vertex universe exceeds signed 32-bit range")
        self.n = n
        self.data = array("i", [-1]) * n
        if self.data.itemsize != 4:
            raise RuntimeError("platform does not provide a 32-bit signed int array")
        self.size = 0
        if mapping is not None:
            source = mapping.items() if isinstance(mapping, Mapping) else mapping
            for key, partner in source:
                self[key] = partner

    def __getitem__(self, key: int) -> int:
        """Return a vertex's partner or raise ``KeyError`` if unmatched."""
        index = self.validate(key, "key")
        partner = self.data[index]
        if partner == -1:
            raise KeyError(key)
        return partner

    def __setitem__(self, key: int, value: int) -> None:
        """Set one vertex's partner after validating both indices."""
        index = self.validate(key, "key")
        partner = self.validate(value, "partner")
        if self.data[index] == -1:
            self.size += 1
        self.data[index] = partner

    def __delitem__(self, key: int) -> None:
        """Mark a matched vertex as unmatched."""
        index = self.validate(key, "key")
        if self.data[index] == -1:
            raise KeyError(key)
        self.data[index] = -1
        self.size -= 1

    def __iter__(self) -> Iterator[int]:
        """Iterate over currently matched vertices in ascending order."""
        return (index for index, partner in enumerate(self.data) if partner != -1)

    def __len__(self) -> int:
        """Return the number of matched vertices represented by this map."""
        return self.size

    def __contains__(self, key: object) -> bool:
        """Return whether an exact-integer vertex has an assigned partner."""
        if type(key) is not int or key < 0 or key >= self.n:
            return False
        return self.data[key] != -1

    @overload
    def pop(self, key: int) -> int: ...

    @overload
    def pop(self, key: int, default: Key) -> int | Key: ...

    def pop(self, key: int, default: object = Missing) -> int | object:
        """Remove a key and return its partner, or return the optional default."""
        index = self.validate(key, "key")
        partner = self.data[index]
        if partner == -1:
            if default is not Missing:
                return default
            raise KeyError(key)
        self.data[index] = -1
        self.size -= 1
        return partner

    def clear(self) -> None:
        """Mark every vertex as unmatched without changing the universe."""
        self.data = array("i", [-1]) * self.n
        self.size = 0

    def validate(self, vertex: int, label: str) -> int:
        """Validate and return a vertex index."""
        if type(vertex) is not int:
            raise TypeError(f"{label} must be an integer")
        if vertex < 0 or vertex >= self.n:
            raise ValueError(f"{label} is outside the vertex universe")
        return vertex
