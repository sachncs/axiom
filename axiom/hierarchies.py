"""Bounded undo for paper Hierarchy roots and deferred phase deletions."""

from __future__ import annotations

from threading import get_ident
from typing import TYPE_CHECKING

from axiom.types import Edge
from axiom.vertices import Vertices

if TYPE_CHECKING:
    from axiom.core import Matcher
    from axiom.hierarchy import Hierarchy


class Hierarchies:
    """Retain an admitted hierarchy and journal only changed deferred edges."""

    def __init__(self, owner: Matcher, capacity: int = 65536) -> None:
        """Bind the current hierarchy without copying its state-sized indexes."""
        from axiom.hierarchy import Hierarchy

        if type(capacity) is not int or capacity <= 0:
            raise ValueError("hierarchy capacity must be a positive integer")
        if owner.hierarchies is not None:
            raise RuntimeError("hierarchy transaction is already active")
        self.owner = owner
        self.capacity = capacity
        self.thread = get_ident()
        self.active = True
        self.root: Hierarchy | None = None
        self.state: dict[str, object] = {}
        self.edges: dict[Edge, bool] = {}
        if owner.multi is not None:
            root = owner.multi
            if type(root) is not Hierarchy or root.journal is not None:
                raise TypeError("hierarchy admission requires an idle plain record")
            self.validate_record(root)
            self.root = root
            self.state = dict(vars(root))
            object.__setattr__(root, "journal", self)
        object.__setattr__(owner, "hierarchies", self)

    def validate_record(self, root: Hierarchy) -> None:
        """Reject unsupported mutable roots before omitting recursive copying."""
        from axiom.system import System

        fields = {
            "graph",
            "k",
            "levels",
            "A1",
            "A2",
            "N1",
            "R1",
            "A_levels",
            "N_levels",
            "R_levels",
            "L_levels",
            "deferred_deletions",
            "journal",
        }
        if vars(root).keys() != fields:
            raise TypeError("unsupported hierarchy fields")
        if type(root.k) is not int or root.k < 1:
            raise ValueError("hierarchy level count must be positive")
        if type(root.levels) is not list or any(
            type(level) is not System for level in root.levels
        ):
            raise TypeError("hierarchy levels require plain System records")
        for name in ("A1", "A2", "N1"):
            partition = getattr(root, name)
            if type(partition) not in (set, Vertices):
                raise TypeError("hierarchy partitions require bounded set storage")
            if type(partition) is Vertices and partition.n != root.graph.n:
                raise ValueError("hierarchy partition universe differs")
        if type(root.deferred_deletions) is not set:
            raise TypeError("deferred deletions require a plain set")
        if type(root.R1) not in (set, Vertices):
            raise TypeError("hierarchy R partition requires a set or Vertices")
        values = root.A_levels
        if type(values) is not list or any(
            type(value) not in (set, Vertices) for value in values
        ):
            raise TypeError("hierarchy A-levels require bounded set storage")
        if any(type(value) is Vertices and value.n != root.graph.n for value in values):
            raise ValueError("hierarchy A-level universe differs")
        if type(root.N_levels) is not list or any(
            type(value) not in (set, Vertices) for value in root.N_levels
        ):
            raise TypeError("hierarchy N-levels require bounded set storage")
        if any(
            type(value) is Vertices and value.n != root.graph.n
            for value in root.N_levels
        ):
            raise ValueError("hierarchy N-level universe differs")
        if type(root.R_levels) is not list or any(
            type(value) not in (set, Vertices) for value in root.R_levels
        ):
            raise TypeError("hierarchy R levels require sets or Vertices")
        if type(root.L_levels) is not list or any(
            type(container) is not dict for container in root.L_levels
        ):
            raise TypeError("hierarchy indexes require plain lists and maps")

    def check(self) -> None:
        """Enforce owner-thread lifecycle and the retained root binding."""
        if get_ident() != self.thread:
            raise RuntimeError("hierarchy journal belongs to another thread")
        if not self.active or self.owner.hierarchies is not self:
            raise RuntimeError("hierarchy journal is not active here")
        if self.root is not None and self.root.journal is not self:
            raise RuntimeError("hierarchy journal binding changed")

    def change(self, edge: Edge, present: bool) -> None:
        """Record a deferred-edge membership before applying its new value."""
        self.check()
        if self.root is None:
            raise RuntimeError("there is no admitted hierarchy")
        if (
            type(edge) is not tuple
            or len(edge) != 2
            or any(type(vertex) is not int for vertex in edge)
        ):
            raise TypeError("deferred edge must be a pair of integer vertices")
        if edge not in self.edges:
            if len(self.edges) >= self.capacity:
                raise MemoryError("hierarchy journal capacity exceeded")
            self.edges[edge] = edge in self.root.deferred_deletions
        if present:
            self.root.deferred_deletions.add(edge)
        else:
            self.root.deferred_deletions.discard(edge)

    def clear(self) -> None:
        """Reserve all original cells before clearing the deferred-edge set."""
        self.check()
        if self.root is None:
            raise RuntimeError("there is no admitted hierarchy")
        for edge in self.root.deferred_deletions:
            if edge not in self.edges:
                if len(self.edges) >= self.capacity:
                    raise MemoryError("hierarchy journal capacity exceeded")
                self.edges[edge] = True
        self.root.deferred_deletions.clear()

    def validate(self) -> None:
        """Validate the retained hierarchy or a fresh rebuild candidate."""
        self.check()
        candidate = self.owner.multi
        if candidate is None:
            return
        if candidate is self.root:
            self.validate_record(candidate)
            return
        from axiom.hierarchy import Hierarchy

        if type(candidate) is not Hierarchy or candidate.journal is not None:
            raise TypeError("new hierarchy candidate must be an idle plain record")
        self.validate_record(candidate)

    def commit(self) -> None:
        """Release undo cells after publication succeeds."""
        self.check()
        if self.root is not None:
            object.__setattr__(self.root, "journal", None)
        self.edges.clear()
        self.state.clear()
        self.active = False
        object.__setattr__(self.owner, "hierarchies", None)

    def rollback(self) -> None:
        """Restore deferred membership and original hierarchy field identities."""
        self.check()
        if self.root is not None:
            for edge, present in self.edges.items():
                if present:
                    self.root.deferred_deletions.add(edge)
                else:
                    self.root.deferred_deletions.discard(edge)
            vars(self.root).clear()
            vars(self.root).update(self.state)
        self.edges.clear()
        self.state.clear()
        self.active = False
        object.__setattr__(self.owner, "hierarchies", None)
