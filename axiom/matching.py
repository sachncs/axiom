"""Matching helpers and maximality checks.

These are generic graph-algorithm utilities used by the dynamic-matching
engine.  They are not specific to the paper's subgraph-system framework;
they exist so that the rest of the codebase can rely on a small, well-
documented API for "give me a maximal matching of this graph" and
"is this matching maximal?".

Responsibilities:
    * Produce a maximal matching from scratch via a deterministic greedy
      scan (used as a baseline and as a fallback when repair fails).
    * Verify maximality in :math:`O(n + m)` by checking every vertex.
    * Provide :math:`O(|M|)` partner lookups and :math:`O(1)` partner
      maps used by the dynamic update code in :mod:`axiom.core`.

Assumptions:
    * The graph may be empty; every helper tolerates ``n == 0``.
    * The matching may be empty; maximality of the empty set on the
      empty graph is ``True`` by convention.
"""

from __future__ import annotations

from axiom.types import Graph, Matching, Vertex, canonical


def greedy(graph: Graph) -> Matching:
    """Return a maximal matching computed by a deterministic greedy scan.

    Vertices are processed in increasing order and the first available
    neighbour is chosen.  This guarantees determinism for a fixed graph
    regardless of the underlying set iteration order, since the loop
    always uses the same access pattern.  The construction is used as a
    baseline for the paper's incremental rebuild of ``M*`` and as a
    safe fallback whenever dynamic repair cannot recover maximality.

    Args:
        graph: The graph to match against.

    Returns:
        A maximal matching as a set of canonical edges.

    Complexity:
        Worst-case :math:`O(n + m)` because each vertex is processed at
        most once and each edge at most twice (once per endpoint).
    """
    matching: Matching = set()
    matched: set[Vertex] = set()
    for u in range(graph.n):
        if u in matched:
            continue
        for v in graph.neighbors(u):
            if v not in matched:
                matching.add(canonical(u, v))
                matched.add(u)
                matched.add(v)
                break
    return matching


def is_maximal_matching(graph: Graph, matching: Matching) -> bool:
    """Return ``True`` iff ``matching`` is maximal in ``graph``.

    A matching is maximal when every vertex is settled: either it is
    incident to a matching edge, or all of its neighbours are.  Note
    that maximal and maximum are distinct notions: a maximal matching
    cannot be enlarged by adding a single edge, but it need not be of
    maximum cardinality.

    Args:
        graph: The host graph.
        matching: Candidate matching to check.

    Returns:
        ``True`` iff ``matching`` is maximal.

    Complexity:
        :math:`O(n + m)` — every vertex is visited, and every neighbour
        of an unmatched vertex is inspected.
    """
    matched_vertices: set[Vertex] = set()
    for u, v in matching:
        matched_vertices.add(u)
        matched_vertices.add(v)

    for u in range(graph.n):
        if u in matched_vertices:
            continue
        for w in graph.neighbors(u):
            if w not in matched_vertices:
                return False
    return True


def partner_in(matching: Matching, v: Vertex) -> Vertex | None:
    """Return the vertex matched to ``v`` in ``matching``, or ``None``.

    Args:
        matching: The matching to query.
        v: The vertex whose partner is sought.

    Returns:
        The matched vertex or ``None`` if ``v`` is unmatched.

    Complexity:
        :math:`O(|M|)` linear scan.  Use :func:`partners` if the
        caller needs repeated partner lookups on the same matching.
    """
    for x, y in matching:
        if x == v:
            return y
        if y == v:
            return x
    return None


def partners(matching: Matching) -> dict[Vertex, Vertex]:
    """Return a dict mapping each matched vertex to its partner.

    The map is built by merging the two orientation dictionaries
    ``{u: v}`` and ``{v: u}`` for every matching edge, so each matched
    vertex maps to its unique partner in :math:`O(1)`.

    Args:
        matching: The matching to index.

    Returns:
        A dictionary whose keys are matched vertices and whose values
        are their partners.

    Complexity:
        :math:`O(|M|)` time and space.
    """
    return {x: y for x, y in matching} | {y: x for x, y in matching}
