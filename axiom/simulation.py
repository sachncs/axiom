"""Simulation and replay utilities for dynamic update sequences.

These helpers are engineering utilities, not part of the paper's baseline
algorithm.  They allow reproducible experiments and stress tests by
producing fixed ``(insert | delete, u, v)`` traces that can be replayed
against any :class:`Matcher` instance.

Determinism:
    * All randomness is drawn from the caller-supplied :class:`random.Random`
      so two runs with the same seed produce identical sequences.
    * Yields operations in a single canonical edge order
      ``(min, max)`` so duplicate ``(u, v)`` and ``(v, u)`` are folded
      into the same logical edge.

Limitations:
    * The generator only produces edges that were previously absent or
      present, so the edge set at the end of a length-``steps`` run
      tends to fluctuate around a stationary density.  It cannot be
      used to construct "the worst case" of the algorithm directly.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import TYPE_CHECKING

from axiom.types import Vertex

if TYPE_CHECKING:
    from axiom.core import Matcher

Update = tuple[str, Vertex, Vertex]
"""Type of one operation in a simulated trace.

The first field is one of ``"insert"`` or ``"delete"``; the remaining
fields are the canonical endpoints.
"""


def random_updates(
    n: int,
    steps: int,
    rng: random.Random,
    existing: set[tuple[int, int]] | None = None,
) -> Iterator[Update]:
    """Yield a random sequence of insert/delete operations.

    Each step independently picks a random unordered pair of distinct
    vertices from ``0..n-1``.  If the pair is absent from the simulated
    edge set, an insert is emitted; otherwise a delete is emitted and
    the edge is removed from the simulated edge set.  This guarantees
    that the ``insert/delete`` choice is always *valid* against the
    current trace state.

    Args:
        n: Number of vertices.
        steps: Number of operations to generate.
        rng: Seeded random number generator.
        existing: Optional initial edge set to extend.

    Yields:
        Tuples ``("insert", u, v)`` or ``("delete", u, v)`` in canonical
        edge order (``u <= v``).

    Complexity:
        :math:`O(steps)` total time; each step is :math:`O(1)` average
        thanks to the hash set used for membership checks.
    """
    edges: set[tuple[int, int]] = set(existing) if existing else set()
    yielded = 0
    while yielded < steps:
        u = rng.randrange(n)
        v = rng.randrange(n)
        if u == v:
            continue
        e = (min(u, v), max(u, v))
        if e not in edges:
            edges.add(e)
            yield ("insert", e[0], e[1])
        else:
            edges.remove(e)
            yield ("delete", e[0], e[1])
        yielded += 1


def replay(algo: Matcher, updates: list[Update]) -> None:
    """Replay a prepared update sequence on ``algo``.

    Args:
        algo: The dynamic matcher.
        updates: List of operations, e.g. as produced by
            :func:`random_updates`.

    Raises:
        ValueError: If any entry in ``updates`` is not a recognised
            ``"insert"`` or ``"delete"`` opcode.  Such an entry
            indicates a corrupt trace; we halt rather than silently
            skipping.
    """
    for op, u, v in updates:
        if op == "insert":
            algo.insert(u, v)
        elif op == "delete":
            algo.delete(u, v)
        else:
            raise ValueError(f"Unknown operation: {op}")
