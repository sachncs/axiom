r"""Fully dynamic maximal matching algorithm.

This module implements the core algorithm of the paper: maintaining a
maximal matching in a graph undergoing edge insertions and deletions.
Both the basic :math:`\tilde O(n^{2/3})` version and the multi-level
:math:`n^{1/2+o(1)}` version are provided.

Responsibilities:
    * Own the live :class:`axiom.graph.Adjacency` and the maintained
      maximal matching.
    * Keep an up-to-date :math:`z`-system (or :math:`k`-level system) and
      the auxiliary directed graph :math:`H`.
    * Handle insertions and deletions with local repair.
    * Surface a small query / statistics API for callers and tests.

Algorithm sketch:

    The algorithm decomposes the vertex set into :math:`A, B, U` where
    :math:`S = A \cup B` is the set of vertices that are saturated in
    :math:`M` (degree exactly ``z`` in :math:`M`) and ``U`` is the rest.
    A first colour class of an edge-colouring of :math:`M` is used as a
    "seed" matching; greedily extending it to a maximal matching gives
    the reported matching.  Updates are handled locally by scanning the
    cached lists :math:`\Lambda(u)` and :math:`L(a)` (of size
    :math:`O(z)` for the basic algorithm), with a full rebuild after
    every ``phase_length = n^{4/3}`` updates to amortise the rebuild cost.

Thread-safety:
    Each :class:`Matcher` instance is intended to be used from
    a single thread.  Concurrent updates on the same instance are not
    supported.
"""

from __future__ import annotations

from axiom.color import Greedy
from axiom.graph import Adjacency
from axiom.hierarchy import Hierarchy
from axiom.invariant import check_maximal_matching
from axiom.ledger import Ledger
from axiom.matching import greedy, partners
from axiom.rebuild import Rebuild, from_mode
from axiom.system import System
from axiom.types import (
    Colorer,
    Graph,
    Matching,
    Vertex,
    canonical,
)


class Matcher:
    r"""Maintains a maximal matching under edge insertions and deletions.

    The algorithm can operate in two modes:

    * ``"basic"`` --- the :math:`\tilde O(n^{2/3})` version (single level).
    * ``"multilevel"`` --- the :math:`n^{1/2+o(1)}` version with
      :math:`k = \Theta(\log n)` levels.

    The instance is stateful: every :meth:`insert_edge` and
    :meth:`delete_edge` mutates the graph and matching and may trigger
    a full rebuild of the supporting :math:`z`-system.  Use
    :meth:`statistics` to inspect the amortised cost.

    Attributes:
        n: Number of vertices (fixed).
        mode: ``"basic"`` or ``"multilevel"``.
        graph: The underlying graph.
        colorer: The edge coloring implementation.
        matched_edges: The maintained maximal matching.
        matched_vertices: Convenience cache of vertices incident to
            some edge of the matching.
        partners: Bidirectional partner map for O(1) partner lookup.
        z: Degree parameter of the active :math:`z`-system.
        phase_length: Number of updates between full rebuilds.
        subphase_length: Number of updates between lightweight seed
            augmentations.
        update_count: Number of updates since the last full rebuild.
        subphase_count: Number of subphase augmentations performed.
        system: Active :math:`z`-system, or ``None``.
        matchings: Colour classes of the most recent edge-colouring.
        seed_matching: First colour class, kept as the seed.
        multi: Multi-level system, present in ``"multilevel"`` mode.
        level_zs: Per-level :math:`z` values in decreasing order.
        k: Number of levels in ``multi``.
        accountant: Bookkeeping counters.

    Args:
        n: Number of vertices (fixed for the lifetime of the instance).
        mode: Either ``"basic"`` or ``"multilevel"``.
        graph: Optional graph implementation (defaults to ``Adjacency``).
        colorer: Optional edge colorer (defaults to ``Greedy``).

    Raises:
        ValueError: If ``n`` is negative or ``mode`` is unknown.

    Example:
        >>> algo = Matcher(n=10, mode="basic")
        >>> algo.insert(0, 1)
        >>> algo.insert(2, 3)
        >>> algo.maximal()
        True
        >>> sorted(algo.matching())
        [(0, 1), (2, 3)]
    """

    def __init__(
        self,
        n: int,
        mode: str = "basic",
        graph: Graph | None = None,
        colorer: Colorer | None = None,
        policy: Rebuild | None = None,
    ) -> None:
        if n < 0:
            raise ValueError(f"n must be non-negative, got {n}")
        if mode not in {"basic", "tiered", "multilevel"}:
            raise ValueError(
                f"mode must be 'basic', 'tiered', or 'multilevel', got {mode}"
            )
        self.n = n
        self.mode = mode
        self.graph = graph if graph is not None else Adjacency(n)
        self.colorer = colorer if colorer is not None else Greedy()
        self.matched_edges: Matching = set()
        self.matched_vertices: set[Vertex] = set()
        self.partner_map: dict[Vertex, Vertex] = {}

        self.z: int = 0
        self.phase_length: int = 0
        self.subphase_length: int = 0
        self.update_count: int = 0
        self.subphase_count: int = 0
        self.system: System | None = None
        self.matchings: list[Matching] = []
        self.seed_matching: Matching = set()

        self.multi: Hierarchy | None = None
        self.level_zs: list[int] = []
        self.k: int = 0

        self.accountant = Ledger()

        if policy is None:
            policy = from_mode(mode)
        self.policy = policy
        self.policy.configure(self)
        self.policy.rebuild(self)

    def partition(self) -> None:
        if self.system is None:
            self.seed_matching = set()
            self.matchings = []
            return

        sub = Adjacency(self.n)
        for e in self.system.M:
            sub.add_edge(e[0], e[1])

        coloring = self.colorer.color(sub, self.z)

        self.matchings = [set() for _ in range(self.z + 1)]
        dropped = 0
        for e, c in coloring.items():
            if 0 <= c <= self.z:
                self.matchings[c].add(e)
            else:
                dropped += 1
        if dropped:
            raise RuntimeError(
                f"partition_m_into_matchings: {dropped} edge(s) received "
                f"out-of-range color (expected 0..{self.z})."
            )

        self.seed_matching = self.matchings[0] if self.matchings else set()

    def _partners_from_matching(self) -> None:
        """Rebuild ``self.partner_map`` from ``self.matched_edges``.

        Iterates the matching once and populates the bidirectional partner
        map.  Each edge contributes both directions; if ``matched_edges``
        is well-formed (every vertex in at most one edge), the result is
        exactly the partner map.  Used by :meth:`refresh` after a
        full rebuild.
        """
        result: dict[Vertex, Vertex] = {}
        for u, v in self.matched_edges:
            result[u] = v
            result[v] = u
        self.partner_map = result

    def add_match(self, u: Vertex, v: Vertex) -> None:
        """Add edge ``(u, v)`` to the maintained matching.

        Updates all three matching views (edge set, vertex set, partner
        map) atomically.  If ``u`` or ``v`` is already matched to some
        other vertex, that prior match is dropped first via a recursive
        :meth:`drop_match` call so the partner map stays in lockstep with
        the matching at every step.

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        e = canonical(u, v)
        # Drop any prior matches of u and v so the new edge is the
        # only match incident to either endpoint.
        for endpoint in (u, v):
            prior = self.partner_map.get(endpoint)
            if prior is not None and prior not in (u, v):
                self.drop_match(endpoint, prior)
        self.matched_edges.add(e)
        self.matched_vertices.add(u)
        self.matched_vertices.add(v)
        self.partner_map[u] = v
        self.partner_map[v] = u

    def drop_match(self, u: Vertex, v: Vertex) -> None:
        """Remove edge ``(u, v)`` from the maintained matching.

        Updates all three matching views (edge set, vertex set, partner
        map) atomically.  Callers must ensure that ``(u, v)`` is in the
        matching.

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        e = canonical(u, v)
        self.matched_edges.discard(e)
        self.matched_vertices.discard(u)
        self.matched_vertices.discard(v)
        self.partner_map.pop(u, None)
        self.partner_map.pop(v, None)

    def refresh(self) -> None:
        if self.system is None:
            self.matched_edges = greedy(self.graph)
            self.matched_vertices = {v for e in self.matched_edges for v in e}
            self._partners_from_matching()
            self.accountant.record_greedy_rebuild(self.n)
            return

        matching: Matching = set()
        matched: set[Vertex] = set()
        # Take seed edges that respect the well-formed matching invariant:
        # each vertex appears in at most one edge. If the seed is corrupt
        # (the colorer produced two edges sharing a vertex with the same
        # color), drop the duplicates so the greedy extension can run.
        for e in self.seed_matching:
            u, v = e
            if u in matched or v in matched:
                continue
            matching.add(e)
            matched.add(u)
            matched.add(v)

        for u in range(self.n):
            if u in matched:
                continue
            for v in self.graph.neighbors(u):
                if v not in matched:
                    matching.add(canonical(u, v))
                    matched.add(u)
                    matched.add(v)
                    break

        self.matched_edges = matching
        self.matched_vertices = matched
        self._partners_from_matching()

    def __check_subphase_boundary(self) -> bool:
        if self.update_count > 0 and self.update_count % self.subphase_length == 0:
            self.subphase_count += 1
            self.__augment_seed_at_subphase_boundary()
            self.accountant.record_subphase_rebuild()
            return True
        return False

    def __augment_seed_at_subphase_boundary(self) -> None:
        self.augment()

    def augment(self) -> int:
        """Run the subphase-boundary augmenting-path search over M_1.

        Public API.  Walks every vertex of :math:`S = A \\cup B` and,
        for each vertex currently unmatched in the seed matching, runs an
        alternating-path search via :meth:`try_augment`.  Returns the
        number of augmenting paths successfully applied.

        Returns:
            The number of vertices of :math:`S` whose seed-match status
            was repaired by an augmenting path.
        """
        if self.system is None or not self.matchings:
            return 0

        matched_in_seed: set[Vertex] = set()
        for u, v in self.seed_matching:
            matched_in_seed.add(u)
            matched_in_seed.add(v)

        augmented = 0
        for s in self.system.S:
            if s not in matched_in_seed:
                if self.try_augment(s, matched_in_seed):
                    augmented += 1
                    matched_in_seed = {v for e in self.seed_matching for v in e}
        return augmented

    def try_augment(self, start: Vertex, matched: set[Vertex]) -> bool:
        """Try to augment the seed matching along an alternating path.

        Public API.  Delegates to :func:`axiom.augment.augment`.  See
        that function for the algorithm.

        Args:
            start: An unmatched vertex where the search begins.
            matched: The set of vertices currently matched in the seed.

        Returns:
            ``True`` if an augmenting path was found and applied.
        """
        from axiom.augment import augment

        return augment(
            self.seed_matching,
            self.graph.neighbors,
            start,
            matched.__contains__,
        )

    def flip(self, path: list[Vertex]) -> None:
        """Flip alternating edges in ``path`` in the seed matching.

        Public API.  Delegates to :func:`axiom.augment.flip`.  Exposed
        so callers can experiment with custom augmentation policies.

        Args:
            path: An alternating vertex path of even length >= 2.
        """
        from axiom.augment import flip

        flip(self.seed_matching, path)

    def insert(self, u: Vertex, v: Vertex) -> None:
        """Insert edge ``(u, v)`` and repair the maximal matching.

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        self.graph.add_edge(u, v)
        self.__handle_insertion(u, v)
        self.__advance_update_counter()

    def delete(self, u: Vertex, v: Vertex) -> None:
        """Delete edge ``(u, v)`` and repair the maximal matching.

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        if not self.graph.has_edge(u, v):
            self.accountant.record_deletion()
            return
        self.graph.remove_edge(u, v)
        self.__handle_deletion(u, v)
        self.__advance_update_counter()

    def __handle_insertion(self, u: Vertex, v: Vertex) -> None:
        if self.system is not None:
            a = u if u in self.system.A else (v if v in self.system.A else None)
            u_vert = v if a == u else (u if v in self.system.A else None)
            if a is not None and u_vert is not None and u_vert in self.system.U:
                if u_vert in self.matched_vertices and a not in self.matched_vertices:
                    partner_of_u = self.partner(u_vert)
                    if partner_of_u is not None:
                        self.drop_match(u_vert, partner_of_u)
                        self.add_match(a, u_vert)
                        self.accountant.record_insertion()
                        return
                    else:
                        self.accountant.record_greedy_rebuild()

        self.refresh()
        self.accountant.record_insertion()

    def __handle_deletion(self, u: Vertex, v: Vertex) -> None:
        if canonical(u, v) in self.matched_edges:
            self.drop_match(u, v)

        self.__cleanup_stale_edges()
        self.__rematch_vertex(u)
        self.__rematch_vertex(v)
        self.__cleanup_stale_edges()

        if not self.maximal():
            self.refresh()

        self.accountant.record_deletion()

    def __cleanup_stale_edges(self) -> None:
        stale = [e for e in self.matched_edges if not self.graph.has_edge(e[0], e[1])]
        for e in stale:
            self.drop_match(e[0], e[1])
        if stale:
            self.accountant.record_stale_cleanup(len(stale))

    def __rematch_vertex(self, v: Vertex) -> None:
        if v in self.matched_vertices:
            return
        if self.system is None:
            for w in self.graph.neighbors(v):
                if w not in self.matched_vertices:
                    self.add_match(v, w)
                    return
            return

        if v in self.system.U:
            self.__rematch_u(v)
            return
        if v in self.system.B:
            self.__rematch_b(v)
            return
        if v in self.system.A:
            self.__rematch_a(v)
            return

        for w in self.graph.neighbors(v):
            if w not in self.matched_vertices:
                self.add_match(v, w)
                return

    def __rematch_u(self, u: Vertex) -> None:
        assert self.system is not None
        system = self.system
        for w in system.lambda_lists.get(u, []):
            if w not in self.matched_vertices and self.graph.has_edge(u, w):
                self.add_match(u, w)
                self.accountant.record_rematch_u_scan()
                return

        scanned = 0
        for w in system.S:
            if w not in self.matched_vertices:
                if self.graph.has_edge(u, w):
                    self.add_match(u, w)
                    self.accountant.record_rematch_u_scan(scanned + 1)
                    return
            scanned += 1
        self.accountant.record_rematch_u_scan(scanned)

    def __rematch_b(self, b: Vertex) -> None:
        assert self.system is not None
        system = self.system
        scanned = 0
        for u in system.U:
            if (
                u not in self.matched_vertices
                and b in system.lambda_lists.get(u, [])
                and self.graph.has_edge(u, b)
            ):
                self.add_match(u, b)
                self.accountant.record_rematch_b_scan(scanned + 1)
                return
            scanned += 1
        self.accountant.record_rematch_b_scan(scanned)

        for w in system.S:
            if w not in self.matched_vertices:
                if self.graph.has_edge(b, w):
                    self.add_match(b, w)
                    return

    def __rematch_a(self, a: Vertex) -> None:
        assert self.system is not None
        system = self.system
        tau = (32 * self.phase_length) // self.z if self.z > 0 else 0
        limit = 2 * tau + 1
        scanned = 0

        if self.multi is not None and a in self.multi.A1:
            for u in system.L_lists.get(a, []):
                if u not in self.multi.R1:
                    continue
                scanned += 1
                if scanned > limit:
                    break
                if u not in self.matched_vertices and self.graph.has_edge(a, u):
                    self.add_match(a, u)
                    self.accountant.record_rematch_a_scan(scanned)
                    return
                p = self.partner(u)
                if p is not None and p in system.A:
                    continue
                if p is not None:
                    self.drop_match(u, p)
                if self.graph.has_edge(a, u):
                    self.add_match(a, u)
                    if p is not None:
                        self.__rematch_vertex(p)
                    self.accountant.record_rematch_a_scan(scanned)
                    return
        else:
            for u in system.L_lists.get(a, []):
                scanned += 1
                if scanned > limit:
                    break
                if u not in self.matched_vertices and self.graph.has_edge(a, u):
                    self.add_match(a, u)
                    self.accountant.record_rematch_a_scan(scanned)
                    return
                p = self.partner(u)
                if p is not None and p not in system.A:
                    if self.graph.has_edge(a, u):
                        self.drop_match(u, p)
                        self.add_match(a, u)
                        if p is not None:
                            self.__rematch_vertex(p)
                        self.accountant.record_rematch_a_scan(scanned)
                        return

        self.accountant.record_rematch_a_scan(scanned)

        for w in self.graph.neighbors(a):
            if w not in self.matched_vertices:
                self.add_match(a, w)
                return

    def maintain_i3(self) -> int:
        """Repair any violation of invariant (I3) in tiered mode.

        Calls :meth:`Hierarchy.maintain_i3` on the active multi-level
        system.  In basic mode, there is no I3 invariant and the
        method is a no-op.

        Returns:
            The number of A_1 -> R_1 edges broken and rematched.
            ``0`` in basic mode or when the invariant already holds.
        """
        if self.multi is None or self.system is None:
            return 0
        return self.multi.maintain_i3(
            self.matched_edges,
            self.phase_length,
            self.z,
            self.partner,
            self.__rematch_vertex,
        )

    def __advance_update_counter(self) -> None:
        self.update_count += 1
        self.__check_subphase_boundary()
        self.maintain_i3()

        if self.update_count >= self.phase_length:
            self.policy.rebuild(self)

    def matching(self) -> Matching:
        """Return a copy of the current maximal matching.

        Returns:
            A copy of the matching set.

        Complexity:
            O(|M*|) to copy.
        """
        return set(self.matched_edges)

    def maximal(self) -> bool:
        """Return True iff the current matching is maximal in the graph.

        Complexity:
            O(n + m).
        """
        return check_maximal_matching(self.graph, self.matched_edges)

    def size(self) -> int:
        """Return the number of edges in the current matching."""
        return len(self.matched_edges)

    def partner(self, v: Vertex) -> Vertex | None:
        """Return the vertex matched to v, or None.

        Args:
            v: The vertex to look up.

        Returns:
            v's partner, or None if unmatched.

        Complexity:
            O(1) via the partner map maintained in lockstep with the
            matching.
        """
        return self.partner_map.get(v)

    def partners(self) -> dict[Vertex, Vertex]:
        """Return a dict mapping each matched vertex to its partner.

        Returns:
            Dictionary of vertex to partner mappings.

        Complexity:
            O(|M*|) time and space.
        """
        return partners(self.matched_edges)

    def stats(self) -> dict[str, int]:
        """Return a dictionary of runtime statistics.

        Returns:
            A flat dict suitable for logging or CSV export.
        """
        stats: dict[str, int] = {
            "n": self.n,
            "m": self.graph.num_edges(),
            "matching_size": len(self.matched_edges),
            "updates_since_rebuild": self.update_count,
            "phase_length": self.phase_length,
            "subphase_length": self.subphase_length,
            "subphase_count": self.subphase_count,
            "z": self.z,
        }
        stats.update(self.accountant.snapshot())
        return stats
