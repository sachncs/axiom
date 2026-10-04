"""Bounded first-write undo for mutable multilevel phase-clock cells."""

from __future__ import annotations

from threading import get_ident
from typing import TYPE_CHECKING

from axiom.capacity import JournalCapacityError

if TYPE_CHECKING:
    from axiom.core import Matcher


class Clocks:
    """Retain clock roots and changed cells without recursive copying."""

    names = ("level_phase_updates", "level_phase_indices")

    def __init__(self, owner: Matcher, capacity: int = 65536) -> None:
        """Retain supported list roots before an atomic update begins."""
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("clock capacity must be a positive integer")
        if owner.clocks is not None:
            raise RuntimeError("clock transaction is already active")
        self.owner = owner
        self.thread = get_ident()
        self.active = True
        self.roots = {name: getattr(owner, name) for name in self.names}
        if any(type(value) is not list for value in self.roots.values()):
            raise TypeError("phase clocks require plain lists")
        self.capacity = capacity
        self.cells: dict[tuple[int, int], int] = {}
        object.__setattr__(owner, "clocks", self)

    def check(self) -> None:
        """Reject cross-thread use or a stale transaction handle."""
        if get_ident() != self.thread:
            raise RuntimeError("clock journal belongs to another thread")
        if not self.active or self.owner.clocks is not self:
            raise RuntimeError("clock journal is not active here")

    def validate(self) -> None:
        """Ensure candidate clock roots retain the supported list shape."""
        self.check()
        if any(type(getattr(self.owner, name)) is not list for name in self.names):
            raise TypeError("candidate phase clocks require plain lists")

    def write(self, values: list[int], index: int, value: int) -> None:
        """Retain the first old value before changing one clock cell."""
        self.check()
        if type(values) is not list or type(index) is not int or type(value) is not int:
            raise TypeError("clock writes require a plain integer list cell")
        original = any(values is root for root in self.roots.values())
        if original:
            cell = id(values), index
            if cell not in self.cells:
                if len(self.cells) >= self.capacity:
                    raise JournalCapacityError("clock journal capacity exceeded")
                self.cells[cell] = values[index]
        values[index] = value

    def rollback(self) -> None:
        """Restore original list identities and values exactly."""
        self.check()
        byid = {id(value): value for value in self.roots.values()}
        for (address, index), value in self.cells.items():
            byid[address][index] = value
        for name, value in self.roots.items():
            object.__setattr__(self.owner, name, value)
        self.cells.clear()
        self.active = False
        object.__setattr__(self.owner, "clocks", None)

    def commit(self) -> None:
        """Release retained clock state after publication."""
        self.check()
        self.roots.clear()
        self.cells.clear()
        self.active = False
        object.__setattr__(self.owner, "clocks", None)
