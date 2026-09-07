"""Augmenting-path utilities for the seed matching.

The basic algorithm uses augmenting-path searches over the seed
matching M_1 to repair the maximal matching M* across subphase
boundaries.  This module hosts the two building blocks as
free functions so they can be reused, tested, and reasoned about
independently of the :class:`axiom.core.Matcher` orchestrator.

Functions:
    flip: flip alternating edges in a path, swapping membership
        in the matching.
    augment: try to augment a matching along an alternating path
        starting at an unmatched vertex.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable

from axiom.types import Edge, Vertex, canonical


def flip(coloring: set[Edge], path: list[Vertex]) -> None:
    """Flip alternating edges along ``path`` in the matching ``coloring``.

    The path must have even length (vertices alternating matched/unmatched
    under the matching).  Edges at even positions are removed from the
    matching; edges at odd positions are added.  The matching ``coloring``
    is mutated in place.

    Args:
        coloring: The matching to mutate.
        path: An alternating vertex path of even length >= 2.
    """
    for i in range(0, len(path) - 1, 2):
        e = canonical(path[i], path[i + 1])
        if e in coloring:
            coloring.discard(e)
        else:
            coloring.add(e)


def augment(
    matching: set[Edge],
    neighbors: Callable[[Vertex], Iterable[Vertex]],
    start: Vertex,
    is_matched: Callable[[Vertex], bool],
) -> bool:
    """Try to augment ``matching`` by an alternating path starting at ``start``.

    Performs a BFS that alternates between non-matching edges (out of an
    unmatched vertex) and matching edges (out of a matched vertex), looking
    for an unmatched endpoint.  On success, flips the discovered alternating
    path in place via :func:`flip` and returns ``True``.

    Args:
        matching: The matching to augment (mutated on success).
        neighbors: Callable yielding the neighbours of a vertex.
        start: The unmatched vertex where the search begins.
        is_matched: Callable returning whether a vertex is matched.

    Returns:
        ``True`` if an augmenting path was found and applied.
    """
    visited: set[tuple[Vertex, bool]] = {(start, False)}
    queue: deque[tuple[Vertex, bool, list[Vertex]]] = deque()
    queue.append((start, False, [start]))

    while queue:
        curr, via_match, path = queue.popleft()

        for w in neighbors(curr):
            e = canonical(curr, w)
            is_match = e in matching

            if via_match and not is_match:
                if (w, True) not in visited:
                    new_path = path + [w]
                    if not is_matched(w):
                        flip(matching, new_path)
                        return True
                    visited.add((w, True))
                    queue.append((w, True, new_path))
            elif not via_match and is_match:
                if (w, False) not in visited:
                    visited.add((w, False))
                    queue.append((w, False, path + [w]))

    return False
