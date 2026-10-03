"""First-write undo for phase color classes and the paper seed matching.

Only registered removals mutate retained sets. Partitioning and augmentation
build private replacement sets; rollback discards them and restores old aliases.
This is not a journal for System, Hierarchy or auxiliary indexes.
"""

from __future__ import annotations

import sys
import sysconfig
from threading import get_ident
from typing import TYPE_CHECKING

from axiom.types import Edge, Matching

if TYPE_CHECKING:
    from axiom.core import Matcher


class Classes:
    """Retain original class/seed identities with bounded edge-cell undo."""

    def __init__(self, owner: Matcher, capacity: int = 65536) -> None:
        """Admit plain owned containers and bound retained sets plus undo cells."""
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("class capacity must be a positive integer")
        if owner.classes is not None:
            raise RuntimeError("class transaction is already active")
        if type(owner.matchings) is not list or type(owner.seed_matching) is not set:
            raise TypeError("classes require a plain list and seed set")
        if len(owner.matchings) + 1 > capacity:
            raise MemoryError("class journal capacity exceeded")
        if any(type(value) is not set for value in owner.matchings):
            raise TypeError("color classes require plain sets")
        self.owner = owner
        self.capacity = capacity
        self.thread = get_ident()
        self.active = True
        self.list = owner.matchings
        self.seed = owner.seed_matching
        self.slots = tuple(self.list)
        self.sets = {id(value): value for value in (*self.slots, self.seed)}
        self.entries: dict[tuple[int, Edge], bool] = {}
        self.isolate()
        object.__setattr__(owner, "classes", self)

    def isolate(self) -> None:
        """Reject aliases into state whose writes bypass class removal hooks.

        Seed/class sharing and repeated class references are intentional. Other
        owned aliases cannot be silently protected by a different snapshot.
        GIL-enabled CPython can prove unique ownership, including intentional
        sharing, from strong-reference counts. Otherwise admission is global.
        """
        if (
            sys.implementation.name == "cpython"
            and not sysconfig.get_config_var("Py_GIL_DISABLED")
            and sys.getrefcount(self.list) == 3
        ):
            counts: dict[int, int] = {}
            for address in map(id, self.slots):
                counts[address] = counts.get(address, 0) + 1
            # Each class occurrence is retained by the original list and slots.
            # Every set also has one registry and one getrefcount argument ref;
            # the seed has two more (owner.seed_matching and self.seed).
            if all(
                sys.getrefcount(self.sets[address])
                == 2
                + 2 * counts.get(address, 0)
                + 2 * (self.sets[address] is self.seed)
                for address in self.sets
            ):
                return
        pending = [
            value
            for name, value in vars(self.owner).items()
            if name
            not in {
                "matchings",
                "seed_matching",
                "classes",
                "views",
                "colorer",
                "policy",
            }
        ]
        seen = {id(self.owner)}
        while pending:
            value = pending.pop()
            address = id(value)
            if value is self.list or address in self.sets:
                raise ValueError("color class aliases other owned algorithm state")
            if value is None or type(value) in (int, bool, str, float, set, frozenset):
                continue
            if address in seen:
                continue
            seen.add(address)
            if type(value) in (list, tuple):
                pending.extend(value)
            elif type(value) is dict:
                pending.extend(value.values())
            elif hasattr(value, "__dict__") and not callable(value):
                pending.extend(vars(value).values())

    def check(self) -> None:
        """Enforce owner binding, active lifecycle and serialized thread use."""
        if get_ident() != self.thread:
            raise RuntimeError("class journal belongs to another thread")
        if not self.active or self.owner.classes is not self:
            raise RuntimeError("class journal is not active here")

    def remove(self, matching: Matching, edge: Edge) -> None:
        """Retain an original membership before removal; candidates are private."""
        self.check()
        address = id(matching)
        # A delete is broadcast to every color class, but an edge belongs to
        # only a small subset of those classes.  Recording absent memberships
        # spends journal capacity without protecting a mutation: ``discard``
        # leaves those sets unchanged.  This fan-out made a single valid delete
        # fail on large colorings despite touching very little retained state.
        if address in self.sets and edge in matching:
            key = (address, edge)
            if key not in self.entries:
                if len(self.sets) + len(self.entries) >= self.capacity:
                    raise MemoryError("class journal capacity exceeded")
                self.entries[key] = True
        matching.discard(edge)

    def validate(self) -> None:
        """Require supported roots before existing matching/phase certificates."""
        self.check()
        if (
            type(self.owner.matchings) is not list
            or type(self.owner.seed_matching) is not set
            or any(type(value) is not set for value in self.owner.matchings)
        ):
            raise TypeError("color class candidate requires plain containers")

    def commit(self) -> None:
        """Release old cells only after graph publication succeeds."""
        self.check()
        self.entries.clear()
        self.active = False
        object.__setattr__(self.owner, "classes", None)

    def rollback(self) -> None:
        """Restore original sets, list slots, roots and shared references in place."""
        self.check()
        for (address, edge), present in self.entries.items():
            matching = self.sets[address]
            if present:
                matching.add(edge)
            else:
                matching.discard(edge)
        self.list[:] = self.slots
        self.owner.matchings = self.list
        self.owner.seed_matching = self.seed
        self.entries.clear()
        self.active = False
        object.__setattr__(self.owner, "classes", None)
