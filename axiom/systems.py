"""Owner-bound undo for admitted paper Systems, cached rows and matching cuts.

Root references are retained, not recursively copied. Sorted cache-row edits
are retained as bounded inverse deltas, including when rows are aliased across
admitted Systems. Other Matcher state is protected by its owner-specific
journals and shallow root record.
"""

from __future__ import annotations

from array import array
from bisect import bisect_left
from threading import get_ident
from typing import TYPE_CHECKING, Any

from axiom.capacity import JournalCapacityError
from axiom.graph import packed_backed
from axiom.types import Edge, Graph, Vertex
from axiom.vertices import Vertices

if TYPE_CHECKING:
    from axiom.core import Matcher
from axiom.system import CacheRow, System


class Systems:
    """Retain System roots and journal touched cache edits by inverse delta."""

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
        self.maps: dict[int, dict[Vertex, CacheRow]] = {}
        self.mapcompact: dict[int, bool] = {}
        self.changes: list[tuple[CacheRow, Vertex, bool]] = []
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
                "implicit_all_u_neighbors",
                "journal",
            }:
                raise TypeError("unsupported System fields")
            if (
                any(
                    type(attributes[name]) not in (set, Vertices)
                    for name in ("A", "B", "U")
                )
                or type(attributes["M"]) is not set
                or type(attributes["implicit_all_u_neighbors"]) is not bool
                or (
                    attributes["implicit_all_u_neighbors"]
                    and (
                        attributes["A"]
                        or attributes["B"]
                        or len(attributes["U"]) != owner.n
                    )
                )
                or any(
                    type(attributes[name]) is Vertices and attributes[name].n != owner.n
                    for name in ("A", "B", "U")
                )
            ):
                raise TypeError("System partitions require bounded set storage")
            if audit and any(
                type(attributes[name]) is Vertices and not attributes[name].check()
                for name in ("A", "B", "U")
            ):
                raise ValueError("System contains an invalid compact partition")
            for name in ("lambda_lists", "L_lists"):
                container = attributes[name]
                if type(container) is not dict:
                    raise TypeError("System caches require plain maps")
                packed = packed_backed(system.graph)
                compact = self.mapcompact.get(id(container))
                if compact is not None and compact != packed:
                    raise TypeError("shared cache maps require matching graph backends")
                self.mapcompact[id(container)] = packed
                if audit and any(
                    not self.cachemap(container, row, source)
                    for source, row in container.items()
                ):
                    raise TypeError("System caches require backend-compatible rows")
                self.maps[id(container)] = container
            # The derived implicit-row marker is constant metadata and does
            # not consume a journal cell; preserve the existing admission
            # budget when that implementation detail is present.
            self.reserve(len(attributes) - 1)
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
            raise JournalCapacityError("system journal capacity exceeded")
        self.size += count

    def edit(
        self,
        container: dict[Vertex, CacheRow],
        source: Vertex,
        target: Vertex,
        added: bool,
    ) -> None:
        """Retain map roots and a constant-size inverse before each row edit."""
        from axiom.system import System

        self.check()
        address = id(container)
        key = address, source
        if address in self.maps and key not in self.keys:
            self.reserve(1)
            self.keys[key] = source in container, container.get(source)
        values = container.get(source)
        if values is None:
            if not added:
                return
            if address not in self.maps:
                raise RuntimeError("new cache rows require an admitted System map")
            values = array("I") if self.mapcompact.get(address, False) else []
        position = bisect_left(values, target)
        present = position < len(values) and values[position] == target
        if added != present:
            # One inverse operation restores this edit; copying the whole row
            # makes a single hub update exceed the fixed journal budget.
            self.reserve(1)
            self.changes.append((values, target, added))
        if source not in container:
            container[source] = values
        System.change(values, target, added)

    def forget(self, container: dict[Vertex, CacheRow], source: Vertex) -> None:
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

    def allows(self, allowed: set[Edge] | Graph, edge: Edge) -> bool:
        """Check matching membership in either an edge set or graph snapshot."""
        if isinstance(allowed, set):
            return edge in allowed
        return allowed.has_edge(*edge)

    def restrict(self, matching: set[Edge], allowed: set[Edge] | Graph) -> None:
        """Log removals first, then cut the bounded list of removed edges.

        The discovery pass streams the matching and allocates only a list of
        removed edges. Capacity failure occurs before matching mutation.
        """
        self.check()
        cuts: list[Edge] = []
        for edge in matching:
            if self.allows(allowed, edge):
                continue
            key = id(matching), edge
            if key not in self.edges:
                self.reserve(1)
                self.edges[key] = matching
            cuts.append(edge)
        for edge in cuts:
            matching.discard(edge)

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
                "implicit_all_u_neighbors",
                "journal",
            }:
                raise TypeError("unsupported System candidate fields")
            if (
                any(
                    type(getattr(system, name)) not in (set, Vertices)
                    for name in ("A", "B", "U")
                )
                or type(system.M) is not set
                or type(system.implicit_all_u_neighbors) is not bool
                or (
                    system.implicit_all_u_neighbors
                    and (system.A or system.B or len(system.U) != self.owner.n)
                )
            ):
                raise TypeError("System candidate requires bounded set storage")
            for name in ("A", "B", "U"):
                partition = getattr(system, name)
                if type(partition) is Vertices:
                    if partition.n != self.owner.n:
                        raise ValueError("System candidate partition universe differs")
                    if (
                        self.audit
                        or original is None
                        or partition is not original[1][name]
                    ) and not partition.check():
                        raise ValueError(
                            "System candidate compact partition is invalid"
                        )
            for name in ("lambda_lists", "L_lists"):
                container = getattr(system, name)
                if type(container) is not dict:
                    raise TypeError("System candidate requires plain maps")
                packed = packed_backed(system.graph)
                compact = self.mapcompact.get(id(container))
                if compact is not None and compact != packed:
                    raise TypeError("shared cache maps require matching graph backends")
                self.maps[id(container)] = container
                self.mapcompact[id(container)] = packed
                full = (
                    self.audit
                    or original is None
                    or (container is not original[1][name])
                )
                if full:
                    for source, row in container.items():
                        if not self.cachemap(container, row, source):
                            raise TypeError(
                                "System candidate requires nonempty sorted cache rows"
                            )
                    continue
                address = id(container)
                for mapaddress, source in self.keys:
                    if mapaddress != address:
                        continue
                    row = container.get(source)
                    if row is not None and not self.cachemap(container, row, source):
                        raise TypeError(
                            "System candidate requires nonempty sorted cache rows"
                        )

    def validrow(self, row: Any, source: Vertex) -> bool:
        """Validate one sorted, nonempty dense-vertex cache row."""
        if (
            type(source) is not int
            or not 0 <= source < self.owner.n
            or type(row) not in (list, array)
            or not row
        ):
            return False
        if type(row) is array and (row.typecode != "I" or row.itemsize != 4):
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

    def cachemap(
        self,
        container: dict[Vertex, CacheRow],
        row: Any,
        source: Vertex,
        packed: bool | None = None,
    ) -> bool:
        """Validate row representation against its admitted graph backend."""
        if packed is None:
            packed = self.mapcompact.get(id(container), False)
        return (type(row) is array) == packed and self.validrow(row, source)

    def commit(self) -> None:
        """Unbind System undo after successful graph publication."""
        self.check()
        for entry in self.roots.values():
            object.__setattr__(entry[0], "journal", None)
        self.changes.clear()
        self.keys.clear()
        self.edges.clear()
        self.maps.clear()
        self.mapcompact.clear()
        self.roots.clear()
        self.active = False
        object.__setattr__(self.owner, "systems", None)

    def rollback(self) -> None:
        """Reverse row deltas, then restore map keys, matching and System roots."""
        self.check()
        from axiom.system import System

        for values, target, added in reversed(self.changes):
            System.change(values, target, not added)
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
        self.changes.clear()
        self.keys.clear()
        self.edges.clear()
        self.maps.clear()
        self.mapcompact.clear()
        self.roots.clear()
        self.active = False
        object.__setattr__(self.owner, "systems", None)
