"""Compact mutable vertex partitions for dense fixed-universe sets."""

from __future__ import annotations

from array import array
from collections.abc import Iterable, Iterator

from axiom.types import Vertex


class Vertices:
    """A compact mutable set of vertices in ``range(n)``.

    Dense paper partitions otherwise retain one Python integer reference and
    hash-table entry per vertex. This representation stores 32-bit members and
    a 32-bit position per possible vertex while preserving the set operations
    needed by the matcher.
    Use a normal ``set`` for sparse vertex collections.
    """

    empty = 0xFFFFFFFF
    __slots__ = ("n", "positions", "members", "size")

    def __init__(
        self,
        n: int,
        values: Iterable[Vertex] = (),
        *,
        ordered: bool = True,
    ) -> None:
        """Create a bounded partition, optionally sorting set input first."""
        if type(n) is not int or not 0 <= n <= self.empty:
            raise ValueError("vertex universe must fit unsigned 32-bit labels")
        if type(ordered) is not bool:
            raise ValueError("ordered must be a boolean")
        self.n = n
        self.positions = array("I", [self.empty]) * n
        self.members = array("I")
        self.size = 0
        if type(values) is set and ordered:
            values = sorted(values)
        for value in values:
            if type(value) is not int or not 0 <= value < self.n:
                raise ValueError(f"vertex must be an integer in [0, {self.n})")
            if self.positions[value] == self.empty:
                self.positions[value] = len(self.members)
                self.members.append(value)
                self.size += 1

    def __contains__(self, value: object) -> bool:
        """Return whether an in-range integer vertex is present."""
        if type(value) is not int or not 0 <= value < self.n:
            return False
        return self.positions[value] != self.empty

    def __iter__(self) -> Iterator[Vertex]:
        """Yield members in deterministic insertion/swap order."""
        return iter(self.members)

    def __len__(self) -> int:
        """Return the cached number of members."""
        return self.size

    def __eq__(self, other: object) -> bool:
        """Compare membership with another compact set or a Python set."""
        if type(other) is set:
            return len(other) == self.size and all(value in self for value in other)
        if type(other) is Vertices:
            return other.size == self.size and all(value in self for value in other)
        return False

    def __or__(self, other: Iterable[Vertex]) -> set[Vertex]:
        """Return ordinary-set union without exposing the position index."""
        return set(self).union(other)

    def __ror__(self, other: Iterable[Vertex]) -> set[Vertex]:
        """Support ordinary-set union with this compact set on the right."""
        return set(other).union(self)

    def __and__(self, other: Iterable[Vertex]) -> set[Vertex]:
        """Return the common members as an ordinary set."""
        return {value for value in self if value in other}

    def __rand__(self, other: Iterable[Vertex]) -> set[Vertex]:
        """Support ordinary-set intersection with this compact set on right."""
        return {value for value in other if value in self}

    def __sub__(self, other: Iterable[Vertex]) -> set[Vertex]:
        """Return members not present in the other iterable."""
        return {value for value in self if value not in other}

    def __rsub__(self, other: Iterable[Vertex]) -> set[Vertex]:
        """Support ordinary-set difference with this compact set on right."""
        return {value for value in other if value not in self}

    def __le__(self, other: Iterable[Vertex]) -> bool:
        """Return whether every member is present in the other iterable."""
        return all(value in other for value in self)

    def __ge__(self, other: Iterable[Vertex]) -> bool:
        """Return whether the other iterable is a subset of this set."""
        return all(value in self for value in other)

    def __lt__(self, other: Iterable[Vertex]) -> bool:
        """Return proper-subset ordering against another vertex iterable."""
        values = set(other)
        return self.size < len(values) and self <= values

    def __gt__(self, other: Iterable[Vertex]) -> bool:
        """Return proper-superset ordering against another vertex iterable."""
        values = set(other)
        return self.size > len(values) and self >= values

    def update(self, values: Iterable[Vertex]) -> None:
        """Add each member from an iterable."""
        for value in values:
            self.add(value)

    def clear(self) -> None:
        """Remove all members while retaining position-index capacity."""
        self.positions = array("I", [self.empty]) * self.n
        self.members = array("I")
        self.size = 0

    def copy(self) -> Vertices:
        """Return an independent compact copy, preserving member order."""
        copied = Vertices(self.n)
        copied.positions = array(self.positions.typecode, self.positions)
        copied.members = array(self.members.typecode, self.members)
        copied.size = self.size
        return copied

    def check(self) -> bool:
        """Independently verify positions, members and cached cardinality."""
        if len(self.members) != self.size:
            return False
        if len(self.positions) != self.n:
            return False
        for position, value in enumerate(self.members):
            if (
                not 0 <= value < self.n
                or self.positions[value] != position
            ):
                return False
        return sum(value != self.empty for value in self.positions) == self.size

    def add(self, value: Vertex) -> None:
        """Insert one vertex, rejecting labels outside the fixed universe."""
        self.validate(value)
        if value in self:
            return
        self.positions[value] = len(self.members)
        self.members.append(value)
        self.size += 1

    def discard(self, value: Vertex) -> None:
        """Remove one in-range vertex if present; other values are ignored."""
        if value not in self:
            return
        position = self.positions[value]
        last = self.members[-1]
        self.members[position] = last
        self.positions[last] = position
        self.members.pop()
        self.positions[value] = self.empty
        self.size -= 1

    def validate(self, value: Vertex) -> None:
        """Reject invalid labels before they can corrupt packed membership."""
        if type(value) is not int or not 0 <= value < self.n:
            raise ValueError(f"vertex must be an integer in [0, {self.n})")
