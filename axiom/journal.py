"""Bounded, owner-thread undo for existing integer attributes.

This primitive protects scalar replacements only. It does not track edits inside
containers, publish graph journals, persist anything, or impose a process quota.
Old values are retained before the first write so rollback never recomputes them.
"""

from __future__ import annotations

from inspect import getattr_static
from threading import get_ident

from axiom.capacity import JournalCapacityError


class Journal:
    """First-write scalar undo with a fixed distinct-field admission bound."""

    def __init__(self, owner: object, capacity: int) -> None:
        """Bind one object and thread, with positive integer entry capacity."""
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("journal capacity must be a positive integer")
        self.owner = owner
        self.capacity = capacity
        self.thread = get_ident()
        self.active = True
        self.entries: dict[str, int] = {}

    def check(self) -> None:
        """Reject closed or cross-thread operations before touching the owner."""
        if get_ident() != self.thread:
            raise RuntimeError("journal belongs to another thread")
        if not self.active:
            raise RuntimeError("journal is closed")

    def write(self, name: str, value: object) -> None:
        """Retain an existing integer attribute before assigning its new value."""
        self.check()
        if type(name) is not str or type(value) is not int:
            raise TypeError("journal writes require a field name and integer")
        attributes = vars(self.owner)
        if name not in attributes:
            raise AttributeError("journal requires an existing instance field")
        original = attributes[name]
        if type(original) is not int:
            raise TypeError("journal only protects existing integer fields")
        descriptor = getattr_static(type(self.owner), name, None)
        if hasattr(descriptor, "__set__"):
            raise TypeError("journal cannot protect descriptor-backed fields")
        if name not in self.entries:
            if len(self.entries) >= self.capacity:
                raise JournalCapacityError("journal entry capacity exceeded")
            # Allocation failure here occurs before the owner is mutated.
            self.entries[name] = original
        object.__setattr__(self.owner, name, value)

    def commit(self) -> None:
        """Release undo after the caller's publication prerequisites pass."""
        self.check()
        self.entries.clear()
        self.active = False

    def rollback(self) -> None:
        """Restore retained values without hooks, copying, or recomputation."""
        self.check()
        for name, original in self.entries.items():
            object.__setattr__(self.owner, name, original)
        self.entries.clear()
        self.active = False
