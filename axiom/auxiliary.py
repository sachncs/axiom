"""Bounded first-write undo for Matcher overlays and rematching indexes."""

from __future__ import annotations

from threading import get_ident
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from axiom.core import Matcher


class Auxiliary:
    """Retain auxiliary roots and journal only their changed map/set cells."""

    maps = (
        "inserted_incident_edges",
        "inserted_incident_counts",
        "H",
        "H_reverse",
        "H_tilde_reverse",
    )
    sets = ("inserted_edges", "deleted_edges", "bad_vertices", "H_tilde", "S_hat")

    def __init__(self, owner: Matcher, capacity: int = 65536) -> None:
        """Admit exact builtin containers without traversing their contents."""
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("auxiliary capacity must be a positive integer")
        if owner.auxiliary is not None:
            raise RuntimeError("auxiliary transaction is already active")
        self.owner = owner
        self.capacity = capacity
        self.thread = get_ident()
        self.active = True
        self.roots = {name: getattr(owner, name) for name in (*self.maps, *self.sets)}
        if any(type(self.roots[name]) is not dict for name in self.maps):
            raise TypeError("auxiliary indexes require plain dictionaries")
        if any(type(self.roots[name]) is not set for name in self.sets):
            raise TypeError("auxiliary indexes require plain sets")
        self.mapsbyid = {id(self.roots[name]): self.roots[name] for name in self.maps}
        self.setsbyid = {id(self.roots[name]): self.roots[name] for name in self.sets}
        self.mapnames = {id(self.roots[name]): name for name in self.maps}
        self.setnames = {id(self.roots[name]): name for name in self.sets}
        self.members: dict[tuple[int, Any], bool] = {}
        self.keys: dict[tuple[int, Any], tuple[bool, Any]] = {}
        self.affected: set[int] = set()
        self.changedinserted: set[Any] = set()
        self.changedtilde: set[Any] = set()
        self.changedkeys: dict[str, set[Any]] = {}
        self.system = owner.system
        self.size = len(self.roots)
        if self.size > capacity:
            raise MemoryError("auxiliary journal capacity exceeded")
        object.__setattr__(owner, "auxiliary", self)

    def check(self) -> None:
        """Enforce active owner-thread use and original root bindings."""
        if get_ident() != self.thread:
            raise RuntimeError("auxiliary journal belongs to another thread")
        if not self.active or self.owner.auxiliary is not self:
            raise RuntimeError("auxiliary journal is not active here")

    def reserve(self) -> None:
        """Reserve one new key or membership undo cell before mutation."""
        self.check()
        if self.size >= self.capacity:
            raise MemoryError("auxiliary journal capacity exceeded")
        self.size += 1

    def member(self, values: set[Any], item: Any, present: bool) -> None:
        """Add or discard one membership in an admitted original set."""
        self.check()
        if type(values) is not set:
            raise TypeError("auxiliary membership requires a plain set")
        address = id(values)
        rootname = self.setnames.get(address)
        if rootname == "inserted_edges":
            self.changedinserted.add(item)
        elif rootname == "H_tilde":
            self.changedtilde.add(item)
        elif rootname == "bad_vertices":
            self.affect(item)
        key = address, item
        if address in self.setsbyid and key not in self.members:
            self.reserve()
            self.members[key] = item in values
        if present:
            values.add(item)
        else:
            values.discard(item)

    def assign(self, container: dict[Any, Any], key: Any, value: Any) -> None:
        """Set one key while retaining its original presence and value."""
        self.check()
        if type(container) is not dict:
            raise TypeError("auxiliary key edit requires a plain dictionary")
        address = id(container)
        rootname = self.mapnames.get(address)
        if rootname is not None:
            self.changedkeys.setdefault(rootname, set()).add(key)
        cell = address, key
        if address in self.mapsbyid and cell not in self.keys:
            self.reserve()
            self.keys[cell] = key in container, container.get(key)
        container[key] = value

    def remove(self, container: dict[Any, Any], key: Any) -> None:
        """Remove one key after retaining its original presence and value."""
        self.check()
        if type(container) is not dict:
            raise TypeError("auxiliary key edit requires a plain dictionary")
        address = id(container)
        rootname = self.mapnames.get(address)
        if rootname is not None:
            self.changedkeys.setdefault(rootname, set()).add(key)
        cell = address, key
        if address in self.mapsbyid and cell not in self.keys:
            self.reserve()
            self.keys[cell] = key in container, container.get(key)
        container.pop(key, None)

    def add(self, container: dict[Any, set[Any]], key: Any, item: Any) -> None:
        """Add to an indexed edge bucket, journaling bucket and key separately."""
        self.check()
        if type(container) is not dict:
            raise TypeError("auxiliary edge index requires a plain dictionary")
        address = id(container)
        rootname = self.mapnames.get(address)
        if rootname in ("H_reverse", "H_tilde_reverse"):
            self.changedkeys.setdefault(rootname, set()).add(key)
        values = container.get(key)
        if values is None:
            values = set()
            self.assign(container, key, values)
        elif type(values) is not set:
            raise TypeError("auxiliary edge bucket requires a plain set")
        else:
            cell = address, key
            if cell in self.keys:
                original = self.keys[cell]
                owned = original[0] and original[1] is values
            else:
                owned = (
                    self.mapsbyid.get(address) is container
                    and container.get(key) is values
                )
            if owned:
                self.setsbyid[id(values)] = values
        self.member(values, item, True)

    def discard(
        self,
        container: dict[Any, set[Any]],
        key: Any,
        item: Any,
        empty: bool = False,
    ) -> None:
        """Discard one indexed edge and optionally remove its empty bucket."""
        self.check()
        rootname = self.mapnames.get(id(container))
        if rootname in ("H_reverse", "H_tilde_reverse"):
            self.changedkeys.setdefault(rootname, set()).add(key)
        values = container.get(key)
        if values is None:
            return
        if type(values) is not set:
            raise TypeError("auxiliary edge bucket requires a plain set")
        address = id(container)
        cell = address, key
        if cell in self.keys:
            original = self.keys[cell]
            owned = original[0] and original[1] is values
        else:
            owned = (
                self.mapsbyid.get(address) is container and container.get(key) is values
            )
        if owned:
            self.setsbyid[id(values)] = values
        self.member(values, item, False)
        if empty and not values:
            self.remove(container, key)

    def clear(self, container: dict[Any, Any] | set[Any]) -> None:
        """Journal every original entry before clearing a root container."""
        self.check()
        address = id(container)
        if type(container) is dict:
            if address in self.mapsbyid:
                for key, value in container.items():
                    cell = address, key
                    if cell not in self.keys:
                        self.reserve()
                        self.keys[cell] = True, value
            container.clear()
            return
        if type(container) is set:
            if address in self.setsbyid:
                for item in container:
                    key = address, item
                    if key not in self.members:
                        self.reserve()
                        self.members[key] = True
            container.clear()
            return
        raise TypeError("auxiliary clear requires a plain map or set")

    def validate(self) -> None:
        """Certify local auxiliary deltas or fully audit a rebuilt candidate."""
        self.check()
        if any(type(getattr(self.owner, name)) is not dict for name in self.maps):
            raise TypeError("auxiliary candidate requires plain dictionaries")
        if any(type(getattr(self.owner, name)) is not set for name in self.sets):
            raise TypeError("auxiliary candidate requires plain sets")
        if not self.certify():
            raise RuntimeError("auxiliary index delta certificate failed")

    def affect(self, *vertices: int) -> None:
        """Include vertices whose graph/matching status changes in the audit."""
        self.check()
        for vertex in vertices:
            if type(vertex) is not int:
                raise TypeError("affected auxiliary vertices must be integers")
            self.affected.add(vertex)

    def certify(self) -> bool:
        """Check exact changed rows; rebuild candidates use the full oracle.

        Previous committed state is assumed valid. Every relation that can
        change is induced by the edited edge, a matching endpoint, a newly bad
        vertex, or a journaled auxiliary cell. Those endpoints and cells are
        checked against the authoritative graph/System and their reverse rows.
        A root/System replacement is a full rebuild and retains the complete
        independent audit.
        """
        self.check()
        if self.owner.system is not self.system or any(
            getattr(self.owner, name) is not value
            for name, value in self.roots.items()
        ):
            return self.complete(self.owner)

        owner = self.owner
        for edge in self.changedinserted:
            if type(edge) is not tuple or len(edge) != 2:
                return False
            left, right = edge
            present = edge in owner.inserted_edges
            for vertex in (left, right):
                bucketrow = owner.inserted_incident_edges.get(vertex)
                if bucketrow is not None and type(bucketrow) is not set:
                    return False
                if (bucketrow is not None and edge in bucketrow) != present:
                    return False
        for vertex in self.affected:
            incident = owner.inserted_incident_edges.get(vertex)
            if incident is not None and (
                type(incident) is not set
                or not incident
                or any(
                    edge not in owner.inserted_edges or vertex not in edge
                    for edge in incident
                )
            ):
                return False

        system = owner.system
        if system is None:
            return not (
                owner.H
                or owner.H_reverse
                or owner.H_tilde
                or owner.H_tilde_reverse
                or owner.S_hat
            )

        for vertex in self.affected:
            expected_s_hat = (
                (vertex in system.A or vertex in system.B)
                and vertex not in owner.matched_vertices
            )
            if (vertex in owner.S_hat) != expected_s_hat:
                return False

        sources = set(self.affected)
        sources.update(self.changedkeys.get("H", ()))
        for source in sources:
            if source not in system.U:
                expected: set[int] = set()
            elif source in owner.matched_vertices:
                expected = set()
            else:
                expected = {
                    target
                    for target in system.lambda_lists.get(source, ())
                    if owner.graph.has_edge(source, target)
                }
            actual = owner.H.get(source, set())
            if actual != expected or (not expected and source in owner.H):
                return False
            old = self.keys.get((id(owner.H), source))
            targets = set(actual)
            if old is not None and old[0] and type(old[1]) is set:
                targets.update(old[1])
            targets.update(expected)
            for target in targets:
                if (source in owner.H_reverse.get(target, set())) != (
                    target in expected
                ):
                    return False

        for target in self.changedkeys.get("H_reverse", ()):
            incoming = owner.H_reverse.get(target, set())
            if any(target not in owner.H.get(source, set()) for source in incoming):
                return False

        candidateedges = set(self.changedinserted)
        for vertex in self.affected:
            candidateedges.update(owner.inserted_incident_edges.get(vertex, ()))
        for edge in self.changedtilde:
            if type(edge) is tuple and len(edge) == 2:
                candidateedges.add((min(edge), max(edge)))
        for edge in candidateedges:
            if type(edge) is not tuple or len(edge) != 2:
                return False
            left, right = edge
            for source, target in ((left, right), (right, left)):
                wantededge = (
                    edge in owner.inserted_edges
                    and source not in owner.matched_vertices
                    and target in owner.bad_vertices
                )
                directed = source, target
                if (directed in owner.H_tilde) != wantededge:
                    return False
                if (source in owner.H_tilde_reverse.get(target, set())) != wantededge:
                    return False

        for target in self.changedkeys.get("H_tilde_reverse", ()):
            for source in owner.H_tilde_reverse.get(target, set()):
                if (source, target) not in owner.H_tilde:
                    return False

        for edge in self.changedtilde:
            if type(edge) is not tuple or len(edge) != 2:
                return False
            source, target = edge
            wantededge = (
                (min(source, target), max(source, target)) in owner.inserted_edges
                and source not in owner.matched_vertices
                and target in owner.bad_vertices
            )
            if (edge in owner.H_tilde) != wantededge:
                return False
            if (source in owner.H_tilde_reverse.get(target, set())) != wantededge:
                return False
        return True

    @staticmethod
    def complete(owner: Matcher) -> bool:
        """Independently reconstruct and compare all auxiliary indexes."""
        expected_inserted: dict[int, set[Any]] = {}
        for edge in owner.inserted_edges:
            left, right = edge
            expected_inserted.setdefault(left, set()).add(edge)
            expected_inserted.setdefault(right, set()).add(edge)
        if owner.inserted_incident_edges != expected_inserted:
            return False
        if owner.system is None:
            return not (
                owner.H
                or owner.H_reverse
                or owner.H_tilde
                or owner.H_tilde_reverse
                or owner.S_hat
            )
        system = owner.system
        expected_s_hat = {
            vertex
            for vertex in system.saturated()
            if vertex not in owner.matched_vertices
        }
        if owner.S_hat != expected_s_hat:
            return False
        expected_h: dict[int, set[int]] = {}
        for source in system.U:
            if source in owner.matched_vertices:
                continue
            targets = {
                target
                for target in system.lambda_lists.get(source, ())
                if owner.graph.has_edge(source, target)
            }
            if targets:
                expected_h[source] = targets
        if owner.H != expected_h:
            return False
        expected_reverse: dict[int, set[int]] = {}
        for source, targets in expected_h.items():
            for target in targets:
                expected_reverse.setdefault(target, set()).add(source)
        if owner.H_reverse != expected_reverse:
            return False
        expected_tilde: set[tuple[int, int]] = set()
        for left, right in owner.inserted_edges:
            if left not in owner.matched_vertices and right in owner.bad_vertices:
                expected_tilde.add((left, right))
            if right not in owner.matched_vertices and left in owner.bad_vertices:
                expected_tilde.add((right, left))
        if owner.H_tilde != expected_tilde:
            return False
        expected_tilde_reverse: dict[int, set[int]] = {}
        for source, target in expected_tilde:
            expected_tilde_reverse.setdefault(target, set()).add(source)
        return owner.H_tilde_reverse == expected_tilde_reverse

    def restore(self) -> None:
        """Restore set cells, map keys and original root references in place."""
        self.check()
        for (address, item), present in self.members.items():
            values = self.setsbyid[address]
            if present:
                values.add(item)
            else:
                values.discard(item)
        for (address, key), (present, value) in self.keys.items():
            container = self.mapsbyid[address]
            if present:
                container[key] = value
            else:
                container.pop(key, None)
        for name, value in self.roots.items():
            object.__setattr__(self.owner, name, value)

    def commit(self) -> None:
        """Discard old-root undo cells after successful publication."""
        self.check()
        self.members.clear()
        self.keys.clear()
        self.affected.clear()
        self.changedinserted.clear()
        self.changedtilde.clear()
        self.changedkeys.clear()
        self.roots.clear()
        self.mapsbyid.clear()
        self.setsbyid.clear()
        self.active = False
        object.__setattr__(self.owner, "auxiliary", None)

    def rollback(self) -> None:
        """Undo auxiliary changes and detach the owner handle."""
        self.restore()
        self.members.clear()
        self.keys.clear()
        self.affected.clear()
        self.changedinserted.clear()
        self.changedtilde.clear()
        self.changedkeys.clear()
        self.roots.clear()
        self.mapsbyid.clear()
        self.setsbyid.clear()
        self.active = False
        object.__setattr__(self.owner, "auxiliary", None)
