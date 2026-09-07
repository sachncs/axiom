"""Rebuild policy strategy for the dynamic matcher.

This module defines the abstract :class:`Rebuild` strategy and its two
concrete implementations (:class:`Basic` and :class:`Tiered`).  The
:class:`axiom.core.Matcher` holds a single :class:`Rebuild` instance and
delegates configuration (z, phase_length, subphase_length, k, level_zs)
and full phase rebuilds to it.  Subclasses choose the rebuild policy at
construction time, either explicitly via the ``policy=`` argument or
implicitly via the ``mode=`` string.

Single responsibility:
    Decide *when* and *how* to rebuild the supporting z-system or
    hierarchy after a phase boundary.  The Matcher owns the actual
    graph and matching state; the policy owns the z-system choices
    and the rebuild procedure.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol

from axiom.hierarchy import Hierarchy
from axiom.system import build

if TYPE_CHECKING:
    from axiom.core import Matcher


class Rebuild(Protocol):
    """Strategy interface for phase-level rebuilds.

    Implementations decide how to set up the z-system(s) (basic or
    multi-level) and how to rebuild them at phase boundaries.  They
    mutate the :class:`Matcher` instance they receive by setting
    parameters (z, phase_length, subphase_length, k, level_zs) and by
    re-running the construction routine.
    """

    name: str

    def configure(self, matcher: Matcher) -> None:
        """Set up z, phase_length, subphase_length, etc. on the matcher."""
        ...

    def rebuild(self, matcher: Matcher) -> None:
        """Run a full z-system rebuild and refresh M*."""
        ...


class Basic:
    """Single-level Ο̃(n^{2/3}) amortised rebuild policy."""

    name = "basic"

    def configure(self, matcher: Matcher) -> None:
        matcher.z = math.ceil(matcher.n ** (2.0 / 3.0)) if matcher.n > 0 else 1
        matcher.phase_length = (
            math.ceil(matcher.n ** (4.0 / 3.0)) if matcher.n > 0 else 1
        )
        matcher.subphase_length = max(1, matcher.phase_length // matcher.z)
        matcher.k = 0
        matcher.level_zs = []

    def rebuild(self, matcher: Matcher) -> None:
        matcher.system = build(matcher.graph, matcher.z)
        matcher.partition()
        matcher.refresh()
        matcher.update_count = 0
        matcher.subphase_count = 0
        matcher.accountant.record_phase_rebuild()


class Tiered:
    """Multi-level n^{1/2+o(1)} amortised rebuild policy.

    Splits the vertex set into ``k`` levels at decreasing ``z`` values,
    building a :class:`axiom.hierarchy.Hierarchy`.  The innermost
    (largest-z) level is consulted on a per-update basis; the full
    hierarchy is rebuilt only at phase boundaries.
    """

    name = "tiered"

    def configure(self, matcher: Matcher) -> None:
        if matcher.n <= 1:
            matcher.k = 1
            matcher.level_zs = [1]
        else:
            z = matcher.n
            zs: list[int] = []
            while z >= math.isqrt(matcher.n):
                zs.append(z)
                z = max(1, z // 2)
            matcher.level_zs = zs
            matcher.k = len(zs)
        matcher.phase_length = (
            math.ceil(matcher.n ** (4.0 / 3.0)) if matcher.n > 0 else 1
        )
        # matcher.z is 0 here for tiered mode; default to the largest level.
        if matcher.z == 0 and matcher.level_zs:
            matcher.z = matcher.level_zs[-1]
        matcher.subphase_length = (
            max(1, matcher.phase_length // matcher.z) if matcher.z > 0 else 1
        )

    def rebuild(self, matcher: Matcher) -> None:
        matcher.multi = Hierarchy(graph=matcher.graph, k=matcher.k)
        matcher.multi.levels = []
        for z in matcher.level_zs:
            level = build(matcher.graph, z)
            matcher.multi.levels.append(level)

        if matcher.multi.levels:
            level1 = matcher.multi.levels[0]
            sorted_a = sorted(level1.A)
            split = len(sorted_a) // 2
            matcher.multi.A1 = set(sorted_a[:split])
            matcher.multi.A2 = set(sorted_a[split:])
            matcher.multi.N1 = matcher.multi.A2 | level1.B
            matcher.multi.R1 = set(range(matcher.graph.n)) - (
                matcher.multi.A1 | matcher.multi.N1
            )

        if matcher.multi.levels:
            matcher.system = matcher.multi.levels[-1]
            matcher.z = matcher.level_zs[-1]
            matcher.subphase_length = max(1, matcher.phase_length // matcher.z)
            matcher.partition()
        else:
            matcher.system = None
            matcher.seed_matching = set()
            matcher.matchings = []

        matcher.refresh()
        matcher.update_count = 0
        matcher.subphase_count = 0
        matcher.accountant.record_phase_rebuild()


def from_mode(mode: str) -> Rebuild:
    """Translate a legacy ``mode`` string into a :class:`Rebuild` instance.

    Kept for backwards compatibility with the v0.4.x CLI signature.  New
    code should construct :class:`Basic` or :class:`Tiered` directly.
    """
    if mode == "basic":
        return Basic()
    if mode == "tiered" or mode == "multilevel":
        return Tiered()
    raise ValueError(
        f"unknown mode: {mode!r} (expected 'basic', 'tiered', or 'multilevel')"
    )
