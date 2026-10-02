"""Bounded first-write undo for the paper matcher's coupled matching views.

Existing containers retain identity. Rebuilt candidates are private replacements
and are discarded on failure. Other algorithm state is still snapshot-protected.
"""

from __future__ import annotations

import sys
import sysconfig
from threading import get_ident
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from axiom.core import Matcher


class Views:
    """Journal touched edges/endpoints without copying the complete matching."""

    def __init__(self, owner: Matcher, capacity: int = 65536) -> None:
        """Retain original views after checking distinct-field admission limits."""
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("view capacity must be a positive integer")
        if owner.views is not None:
            raise RuntimeError("matching transaction is already active")
        self.owner = owner
        self.capacity = capacity
        self.thread = get_ident()
        self.active = True
        self.edges = owner.matched_edges
        self.vertices = owner.matched_vertices
        self.partners = owner.partner_map
        if (
            type(self.edges) is not set
            or type(self.vertices) is not set
            or type(self.partners) is not dict
        ):
            raise TypeError("matching views require plain sets and dictionary")
        if id(self.edges) == id(self.vertices):
            raise ValueError("matching views cannot share a container")
        self.edge: dict[tuple[int, int], bool] = {}
        self.vertex: dict[int, tuple[bool, bool, object]] = {}
        self.isolate()
        object.__setattr__(owner, "views", self)

    def isolate(self) -> None:
        """Reject internal aliases whose mutations are not matching operations.

        GIL-enabled CPython can prove uniqueness from three references: the owner,
        this journal, and getrefcount's argument. Otherwise traverse owned Python
        state, not a local certificate. Native graphs have no Python containers.
        """
        if (
            sys.implementation.name == "cpython"
            and not sysconfig.get_config_var("Py_GIL_DISABLED")
            and sys.getrefcount(self.edges) == 3
            and sys.getrefcount(self.vertices) == 3
            and sys.getrefcount(self.partners) == 3
        ):
            return
        pending = [
            value
            for name, value in vars(self.owner).items()
            if name
            not in {
                "matched_edges",
                "matched_vertices",
                "partner_map",
                "views",
                "colorer",
                "policy",
            }
        ]
        seen = {id(self.owner)}
        while pending:
            value = pending.pop()
            if value is self.edges or value is self.vertices or value is self.partners:
                raise ValueError("matching view aliases other owned algorithm state")
            if value is None or type(value) in (int, bool, str, float, set, frozenset):
                continue
            address = id(value)
            if address in seen:
                continue
            seen.add(address)
            if type(value) in (list, tuple):
                pending.extend(value)
            elif type(value) is dict:
                pending.extend(value.values())
            elif hasattr(value, "__dict__") and not callable(value):
                pending.extend(vars(value).values())

    def check(self) -> bool:
        """Validate owner-thread lifecycle and coherent old/candidate references."""
        if get_ident() != self.thread:
            raise RuntimeError("matching journal belongs to another thread")
        if not self.active:
            raise RuntimeError("matching journal is closed")
        if self.owner.views is not self:
            raise RuntimeError("stale matching journal")
        old = (
            self.owner.matched_edges is self.edges,
            self.owner.matched_vertices is self.vertices,
            self.owner.partner_map is self.partners,
        )
        if any(old) and not all(old):
            raise RuntimeError("matching views are partially replaced")
        return all(old)

    def record(self, left: int, right: int) -> None:
        """Retain original edge and endpoint cells before any local view edit."""
        if not self.check():
            return
        edge = (min(left, right), max(left, right))
        if edge not in self.edge:
            self.reserve()
            self.edge[edge] = edge in self.edges
        for vertex in (left, right):
            if vertex not in self.vertex:
                self.reserve()
                self.vertex[vertex] = (
                    vertex in self.vertices,
                    vertex in self.partners,
                    self.partners.get(vertex),
                )

    def reserve(self) -> None:
        """Reject a new distinct cell before it or matching state is changed."""
        if len(self.edge) + len(self.vertex) >= self.capacity:
            raise MemoryError("matching journal capacity exceeded")

    def validate(self) -> None:
        """Check changed dependencies or the complete rebuilt candidate."""
        if not self.check():
            if (
                any(type(vertex) is not int for vertex in self.owner.matched_vertices)
                or any(type(vertex) is not int for vertex in self.owner.partner_map)
                or any(
                    type(partner) is not int
                    for partner in self.owner.partner_map.values()
                )
            ):
                raise RuntimeError("candidate matching value types are invalid")
            vertices: set[int] = set()
            for left, right in self.owner.matched_edges:
                self.pair(left, right)
                vertices.update((left, right))
            if (
                self.owner.matched_vertices != vertices
                or set(self.owner.partner_map) != vertices
            ):
                raise RuntimeError("candidate matching views are inconsistent")
            return
        for vertex in self.vertex:
            if (vertex in self.vertices) != (vertex in self.partners):
                raise RuntimeError("matching vertex/partner views disagree")
            if vertex in self.partners:
                partner = self.partners[vertex]
                if type(partner) is not int:
                    raise RuntimeError("matching partner value type is invalid")
                edge = (min(vertex, partner), max(vertex, partner))
                if (
                    self.partners.get(partner) != vertex
                    or partner not in self.vertices
                    or edge not in self.edges
                    or not self.owner.graph.has_edge(*edge)
                ):
                    raise RuntimeError("matching partner dependency is inconsistent")
        for edge in self.edge:
            if edge in self.edges:
                left, right = edge
                self.pair(left, right)

    def pair(self, left: int, right: int) -> None:
        """Certify a live canonical edge and all its coupled endpoint views."""
        if (
            type(left) is not int
            or type(right) is not int
            or left >= right
            or left not in self.owner.matched_vertices
            or right not in self.owner.matched_vertices
            or self.owner.partner_map.get(left) != right
            or self.owner.partner_map.get(right) != left
            or not self.owner.graph.has_edge(left, right)
        ):
            raise RuntimeError("matching edge/partner views disagree")

    def commit(self) -> None:
        """Release retained cells after publication."""
        self.check()
        self.edge.clear()
        self.vertex.clear()
        self.active = False
        object.__setattr__(self.owner, "views", None)

    def rollback(self) -> None:
        """Restore old cells and root references, even after a candidate refresh."""
        # A failure may have occurred between the three candidate assignments;
        # rollback must not demand coherent forward references to undo that.
        if (
            get_ident() != self.thread
            or not self.active
            or self.owner.views is not self
        ):
            raise RuntimeError("matching journal cannot roll back here")
        for edge, present in self.edge.items():
            if present:
                self.edges.add(edge)
            else:
                self.edges.discard(edge)
        for vertex, (present, paired, partner) in self.vertex.items():
            if present:
                self.vertices.add(vertex)
            else:
                self.vertices.discard(vertex)
            if paired:
                self.partners[vertex] = partner  # type: ignore[assignment]
            else:
                self.partners.pop(vertex, None)
        self.owner.matched_edges = self.edges
        self.owner.matched_vertices = self.vertices
        self.owner.partner_map = self.partners
        self.edge.clear()
        self.vertex.clear()
        self.active = False
        object.__setattr__(self.owner, "views", None)
