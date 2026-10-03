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
        self.members: dict[tuple[int, Any], bool] = {}
        self.keys: dict[tuple[int, Any], tuple[bool, Any]] = {}
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
        """Validate all candidate top-level auxiliary container types."""
        self.check()
        if any(type(getattr(self.owner, name)) is not dict for name in self.maps):
            raise TypeError("auxiliary candidate requires plain dictionaries")
        if any(type(getattr(self.owner, name)) is not set for name in self.sets):
            raise TypeError("auxiliary candidate requires plain sets")

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
        self.roots.clear()
        self.mapsbyid.clear()
        self.setsbyid.clear()
        self.active = False
        object.__setattr__(self.owner, "auxiliary", None)
