"""Owner-bound undo for admitted paper Systems, cached rows and matching cuts.

Root references are retained, not recursively copied. Row aliases share one
first-write record across all admitted Systems and hierarchy cache edits. Other
Matcher state is protected by its owner-specific journals and shallow root record.
"""

from __future__ import annotations

from threading import get_ident
from typing import TYPE_CHECKING, Any

from axiom.types import Edge, Vertex
from axiom.vertices import Vertices

if TYPE_CHECKING:
    from axiom.core import Matcher
    from axiom.system import System


class Systems:
    """Retain System roots and bound touched row/key/edge undo storage."""

    def __init__(
        self, owner: Matcher, capacity: int = 65536, audit: bool = True
    ) -> None:
        """Admit Systems, optionally using owner-certified roots for fast updates.

        The standalone journal defaults to a complete cache-row admission.
        Matcher transactions may set ``audit=False`` because stable System roots
        are exclusively mutated through this journal; candidate/replaced roots
        are still completely admitted before publication.
        """
        from axiom.system import System

        if type(capacity) is not int or capacity <= 0:
            raise ValueError("system capacity must be a positive integer")
        if type(audit) is not bool:
            raise TypeError("system audit selection must be a boolean")
        if owner.systems is not None:
            raise RuntimeError("system transaction is already active")
        candidates = [owner.system, owner.phase_base_system]
        if owner.multi is not None:
            candidates.extend(owner.multi.levels)
        self.owner = owner
        self.capacity = capacity
        self.audit = audit
        self.thread = get_ident()
        self.active = True
        self.bound = False
        self.roots: dict[int, tuple[System, dict[str, Any]]] = {}
        self.maps: dict[int, dict[Vertex, list[Vertex]]] = {}
        self.rows: dict[int, tuple[list[Vertex], tuple[Vertex, ...]]] = {}
        self.keys: dict[tuple[int, Vertex], tuple[bool, Any]] = {}
        self.edges: dict[tuple[int, Edge], set[Edge]] = {}
        self.size = 0
        for system in candidates:
            if system is None or id(system) in self.roots:
                continue
            if type(system) is not System or system.journal is not None:
                raise TypeError("system admission requires an idle plain System")
            if (
                type(system.z) is not int
                or system.z < 0
                or type(getattr(system.graph, "n", None)) is not int
                or system.graph.n != owner.n
            ):
                raise ValueError("invalid System configuration")
            attributes = vars(system)
            if attributes.keys() != {
                "graph",
                "z",
                "A",
                "B",
                "U",
                "M",
                "lambda_lists",
                "L_lists",
                "journal",
            }:
                raise TypeError("unsupported System fields")
            if (
                any(type(attributes[name]) is not set for name in ("A", "B", "M"))
                or type(attributes["U"]) not in (set, Vertices)
            ):
                raise TypeError("System partitions require plain sets")
            for name in ("lambda_lists", "L_lists"):
                container = attributes[name]
                if type(container) is not dict:
                    raise TypeError("System caches require plain maps and lists")
                if audit and any(
                    not self.validrow(row, source)
                    for source, row in container.items()
                ):
                    raise TypeError("System caches require plain maps and lists")
                self.maps[id(container)] = container
            self.reserve(len(attributes))
            self.roots[id(system)] = system, dict(attributes)
        for entry in self.roots.values():
            object.__setattr__(entry[0], "journal", self)
        object.__setattr__(owner, "systems", self)
        self.bound = True

    def check(self) -> None:
        """Reject stale, closed, cross-thread or detached System handles."""
        if get_ident() != self.thread:
            raise RuntimeError("system journal belongs to another thread")
        if not self.active or self.owner.systems is not self:
            raise RuntimeError("system journal is not active here")
        if any(entry[0].journal is not self for entry in self.roots.values()):
            raise RuntimeError("system journal binding changed")

    def reserve(self, count: int) -> None:
        """Charge roots, map cells, row controls/elements or matching cells."""
        if get_ident() != self.thread:
            raise RuntimeError("system journal belongs to another thread")
        if not self.active:
            raise RuntimeError("system journal is not active here")
        if type(count) is not int or count < 0:
            raise ValueError("system reservation requires a nonnegative integer")
        if self.bound:
            self.check()
        if count > self.capacity - self.size:
            raise MemoryError("system journal capacity exceeded")
        self.size += count

    def edit(
        self,
        container: dict[Vertex, list[Vertex]],
        source: Vertex,
        target: Vertex,
        added: bool,
    ) -> None:
        """Retain a map cell and aliased row before the shared list primitive."""
        from axiom.system import System

        self.check()
        address = id(container)
        key = address, source
        if address in self.maps and key not in self.keys:
            self.reserve(1)
            self.keys[key] = source in container, container.get(source)
        values = container.get(source)
        if values is not None and id(values) not in self.rows:
            self.reserve(1 + len(values))
            self.rows[id(values)] = values, tuple(values)
        if values is None:
            values = []
            container[source] = values
        System.change(values, target, added)

    def forget(
        self, container: dict[Vertex, list[Vertex]], source: Vertex
    ) -> None:
        """Remove an empty cache row while retaining its original map cell."""
        self.check()
        address = id(container)
        key = address, source
        if address not in self.maps:
            raise RuntimeError("cache map is not owned by this System journal")
        if key not in self.keys:
            self.reserve(1)
            self.keys[key] = source in container, container.get(source)
        values = container.get(source)
        if values:
            raise RuntimeError("cannot forget a nonempty System cache row")
        container.pop(source, None)

    def restrict(self, matching: set[Edge], allowed: set[Edge]) -> None:
        """Log removals first, then delete by iterating only bounded undo cells.

        The discovery pass streams the retained set and allocates no matching
        copy. Capacity failure occurs before that pass changes the set.
        """
        self.check()
        for edge in matching:
            if edge in allowed:
                continue
            key = id(matching), edge
            if key not in self.edges:
                self.reserve(1)
                self.edges[key] = matching
        for (_, edge), candidate in self.edges.items():
            if candidate is matching and edge not in allowed and edge in matching:
                matching.remove(edge)

    def validate(self) -> None:
        """Check candidate roots and every changed cache row before publication."""
        self.check()
        candidates = [self.owner.system, self.owner.phase_base_system]
        if self.owner.multi is not None:
            candidates.extend(self.owner.multi.levels)
        unique = {id(system): system for system in candidates if system is not None}
        for system in unique.values():
            if (
                type(system).__name__ != "System"
                or type(system).__module__ != "axiom.system"
            ):
                raise TypeError("unsupported System candidate record")
            if (
                type(system.z) is not int
                or system.z < 0
                or type(getattr(system.graph, "n", None)) is not int
                or system.graph.n != self.owner.n
            ):
                raise ValueError("invalid System candidate configuration")
            original = self.roots.get(id(system))
            if original is None and system.journal is not None:
                raise RuntimeError("new System candidate is already journaled")
            attributes = vars(system)
            if attributes.keys() != {
                "graph",
                "z",
                "A",
                "B",
                "U",
                "M",
                "lambda_lists",
                "L_lists",
                "journal",
            }:
                raise TypeError("unsupported System candidate fields")
            if any(
                type(getattr(system, name)) is not set for name in ("A", "B", "M")
            ) or type(system.U) not in (set, Vertices):
                raise TypeError("System candidate requires plain sets")
            for name in ("lambda_lists", "L_lists"):
                container = getattr(system, name)
                if type(container) is not dict:
                    raise TypeError("System candidate requires plain maps and lists")
                full = self.audit or original is None or (
                    container is not original[1][name]
                )
                if full:
                    for source, row in container.items():
                        if not self.validrow(row, source):
                            raise TypeError(
                                "System candidate requires nonempty sorted cache rows"
                            )
                    continue
                address = id(container)
                for mapaddress, source in self.keys:
                    if mapaddress != address:
                        continue
                    row = container.get(source)
                    if row is not None and not self.validrow(row, source):
                        raise TypeError(
                            "System candidate requires nonempty sorted cache rows"
                        )

    def validrow(self, row: Any, source: Vertex) -> bool:
        """Validate one sorted, nonempty dense-vertex cache row."""
        if (
            type(source) is not int
            or not 0 <= source < self.owner.n
            or type(row) is not list
            or not row
        ):
            return False
        previous = -1
        for target in row:
            if (
                type(target) is not int
                or not 0 <= target < self.owner.n
                or target <= previous
                or target == source
            ):
                return False
            previous = target
        return True

    def commit(self) -> None:
        """Unbind System undo after successful graph publication."""
        self.check()
        for entry in self.roots.values():
            object.__setattr__(entry[0], "journal", None)
        self.rows.clear()
        self.keys.clear()
        self.edges.clear()
        self.maps.clear()
        self.roots.clear()
        self.active = False
        object.__setattr__(self.owner, "systems", None)

    def rollback(self) -> None:
        """Restore rows, map keys, matching cells and original System roots."""
        self.check()
        for values, original in self.rows.values():
            values[:] = original
        for (address, source), (present, original) in self.keys.items():
            container = self.maps[address]
            if present:
                container[source] = original
            else:
                container.pop(source, None)
        for key, matching in self.edges.items():
            matching.add(key[1])
        for system, attributes in self.roots.values():
            for name in vars(system).keys() - attributes.keys():
                del vars(system)[name]
            vars(system).update(attributes)
        self.rows.clear()
        self.keys.clear()
        self.edges.clear()
        self.maps.clear()
        self.roots.clear()
        self.active = False
        object.__setattr__(self.owner, "systems", None)
