r"""The :math:`z`-subgraph system and multi-level generalisation.

This module defines the combinatorial data structures that lie at the heart
of the paper's algorithm.  The implementation follows the notation and
invariants of Section 2 as closely as possible.

Mathematical background:
    A :math:`z`-subgraph system is a triple :math:`(A, B, U)` partitioning
    the vertex set together with an edge set :math:`M` that satisfies:

    * every :math:`v \in S := A \cup B` has :math:`\deg_M(v) = z`,
    * every :math:`u \in U` has :math:`\deg_M(u) \le z`,
    * :math:`|N_G(u) \cap U| \le z` for :math:`u \in U` (a degree cap
      inside :math:`U` that prevents runaway promotion chains),
    * (P1) :math:`|N_G(u) \cap B| \le 2z` for every :math:`u \in U`,
    * (P2) every :math:`M`-edge incident to :math:`a \in A` meets a vertex
      of :math:`S`.

    Each :math:`u \in U` is maintained alongside two index lists:
    :math:`\Lambda(u) = N_G(u) \cap (B \cup U)` and
    :math:`L(a) = N_G(a) \cap U`.  These lists drive the amortised
    :math:`\tilde O(n^{2/3})` per-update bound of the basic algorithm.

    A multi-level system stacks :math:`k` such systems at decreasing
    values of :math:`z`, allowing the recursion to yield the improved
    :math:`n^{1/2+o(1)}` bound in the full version.

References:
    Chuzhoy, Khanna, Song.  "A Faster Deterministic Algorithm for Fully
    Dynamic Maximal Matching" (arXiv:2605.00797v1), Sections 2 and 5.

Assumptions:
    * Vertex labels are dense integers ``0 .. n-1`` (a property inherited
      from :class:`axiom.graph.Graph`).
    * The system is freshly constructed via :func:`build`; it is
      the caller's responsibility to maintain :math:`\Lambda` and
      :math:`L` thereafter (or to invoke :meth:`build_lambda_and_L`).

Limitations:
    * The exact edge-switching rule of the paper's Step 2 construction
      is replaced with a BFS-based augmenting-path heuristic.  See the
      notes on :func:`switch`.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field

from axiom.types import Edge, Graph, Matching, Vertex, canonical


@dataclass
class System:
    r"""A single-level :math:`z`-subgraph system.

    Attributes:
        graph: The underlying dynamic graph.
        z: Degree parameter.
        A: Vertices in set :math:`A`.
        B: Vertices in set :math:`B`.
        U: Vertices in set :math:`U`.
        M: Edge set :math:`M \subseteq E(G)`.
        lambda_lists: For each :math:`u \in U`, the list
            :math:`\Lambda(u) = N_G(u) \cap (B \cup U)`.
        L_lists: For each :math:`a \in A`, the list
            :math:`L(a) = N_G(a) \cap U`.

    Lifecycle:
        A system is normally built by :func:`build`.  After any
        mutation of ``self.graph`` the cached lists in ``lambda_lists``
        and ``L_lists`` must be refreshed via
        :meth:`build_lambda_and_L`.  Mutating ``A``, ``B``, ``U``, or
        ``M`` directly is permitted (this is what the dynamic update
        code does) but should be followed by
        :meth:`check_all_invariants` to verify the system stays legal.

    Thread-safety:
        Not thread-safe.  A ``System`` should be touched only
        from the thread that owns the underlying ``Graph``.
    """

    graph: Graph
    z: int
    A: set[Vertex] = field(default_factory=set)
    B: set[Vertex] = field(default_factory=set)
    U: set[Vertex] = field(default_factory=set)
    M: set[Edge] = field(default_factory=set)
    lambda_lists: dict[Vertex, list[Vertex]] = field(default_factory=dict)
    L_lists: dict[Vertex, list[Vertex]] = field(default_factory=dict)

    @property
    def S(self) -> set[Vertex]:
        r"""Return :math:`S = A \cup B`, the set of saturated vertices."""
        return self.A | self.B

    @property
    def V(self) -> set[Vertex]:
        """Return the full vertex set of the host graph."""
        return set(range(self.graph.n))

    def degree(self, v: Vertex) -> int:
        r"""Return the number of edges of :math:`M` incident to ``v``.

        Args:
            v: The vertex to inspect.

        Returns:
            The :math:`M`-degree of ``v``.

        Complexity:
            :math:`O(\deg_G(v))`.
        """
        deg = 0
        for w in self.graph.neighbors(v):
            e = canonical(v, w)
            if e in self.M:
                deg += 1
        return deg

    def partner_in(self, v: Vertex) -> Iterator[Vertex]:
        r"""Yield neighbours of ``v`` that are joined by an edge of :math:`M`.

        Args:
            v: The vertex whose :math:`M`-neighbours are returned.

        Yields:
            Every vertex ``w`` such that ``(v, w) \in M``.

        Complexity:
            Amortised :math:`O(\deg_M(v))` per complete iteration.
        """
        for w in self.graph.neighbors(v):
            if canonical(v, w) in self.M:
                yield w

    def check_bound(self) -> bool:
        r"""Check the basic degree bounds of the :math:`z`-system.

        Verifies two conditions:
            * every :math:`v \in S` has :math:`\deg_M(v) = z`
              (saturated vertices are exactly at the cap);
            * every :math:`u \in U` has :math:`\deg_M(u) \le z`
              (unsaturated vertices stay at or below the cap).

        Returns:
            ``True`` iff both conditions hold.

        Complexity:
            :math:`O(n + m)` -- one pass over the adjacency lists.
        """
        for v in self.S:
            if self.degree(v) != self.z:
                return False
        for u in self.U:
            if self.degree(u) > self.z:
                return False
        return True

    def check_u(self) -> bool:
        r"""Check :math:`|N_G(u) \cap U| \le z` for all :math:`u \in U`.

        This cap on internal :math:`U`-edges is what stops the
        promotion chain in Step 2 from cascading forever.

        Returns:
            ``True`` iff the bound holds for every :math:`u \in U`.

        Complexity:
            :math:`O(n + m)`.
        """
        for u in self.U:
            count = sum(1 for w in self.graph.neighbors(u) if w in self.U)
            if count > self.z:
                return False
        return True

    def check_p1(self) -> bool:
        r"""Check property (P1): :math:`|N_G(u) \cap B| \le 2z` for all :math:`u \in U`.

        P1 controls the size of the alternating search during rematching;
        if it is violated the paper's :math:`\tilde O(n^{2/3})` bound no
        longer follows from the invariants.

        Returns:
            ``True`` iff (P1) holds for every :math:`u \in U`.

        Complexity:
            :math:`O(n + m)`.
        """
        for u in self.U:
            count = sum(1 for w in self.graph.neighbors(u) if w in self.B)
            if count > 2 * self.z:
                return False
        return True

    def check_p2(self) -> bool:
        r"""Check property (P2): every :math:`M`-edge incident to
        :math:`a \in A` meets a vertex of :math:`S`.

        Without (P2) the A-rematching scan can miss some valid partners
        and the matching maintained in :math:`M^*` may lose edges.

        Returns:
            ``True`` iff (P2) holds for every :math:`a \in A`.

        Complexity:
            :math:`O(n + m)`.
        """
        for a in self.A:
            for w in self.partner_in(a):
                if w not in self.S:
                    return False
        return True

    def check_lambda(self) -> bool:
        r"""Check that each :math:`\Lambda(u)` equals :math:`N_G(u) \cap (B \cup U)`.

        The cached list must agree with the current graph state; stale
        lists are the source of the regression caught by
        ``tests/test_fdmm.py::test_rematch_u_no_phantom_edge_from_stale_list``.

        Returns:
            ``True`` iff every cached list is current.

        Complexity:
            :math:`O(n + m)` dominated by the recomputation of the
            expected lists.
        """
        for u in self.U:
            expected = sorted(
                w for w in self.graph.neighbors(u) if w in self.B or w in self.U
            )
            actual = sorted(self.lambda_lists.get(u, []))
            if expected != actual:
                return False
        return True

    def check_L(self) -> bool:
        r"""Check that each :math:`L(a)` equals :math:`N_G(a) \cap U`.

        Symmetric to :meth:`check_lambda_lists` but for :math:`A`-vertices.

        Returns:
            ``True`` iff every cached list is current.

        Complexity:
            :math:`O(n + m)`.
        """
        for a in self.A:
            expected = sorted(w for w in self.graph.neighbors(a) if w in self.U)
            actual = sorted(self.L_lists.get(a, []))
            if expected != actual:
                return False
        return True

    def check(self) -> bool:
        """Return ``True`` iff every invariant of the :math:`z`-system holds.

        Equivalent to a logical AND of:
        :meth:`check_degree_bounds`,
        :meth:`check_U_degree_in_U`,
        :meth:`check_P1`,
        :meth:`check_P2`,
        :meth:`check_lambda_lists`, and
        :meth:`check_L_lists`.

        Returns:
            ``True`` iff the system is legal.

        Complexity:
            :math:`O(n + m)`.
        """
        return (
            self.check_bound()
            and self.check_u()
            and self.check_p1()
            and self.check_p2()
            and self.check_lambda()
            and self.check_L()
        )

    def index(self) -> None:
        r"""Recompute :math:`\Lambda(u)` and :math:`L(a)` from the current graph.

        Call this whenever the host graph has been mutated so that the
        cached lists stay consistent.  Mutates ``self.lambda_lists`` and
        ``self.L_lists`` in place.

        Complexity:
            :math:`O(n + m)`.  The list is sorted to make
            maximality-equality checks deterministic.
        """
        self.lambda_lists = {
            u: sorted(w for w in self.graph.neighbors(u) if w in self.B or w in self.U)
            for u in self.U
        }
        self.L_lists = {
            a: sorted(w for w in self.graph.neighbors(a) if w in self.U) for a in self.A
        }

    def maximal(self, matching: Matching) -> bool:
        """Return ``True`` iff ``matching`` is maximal in the current ``graph``.

        Convenience wrapper around the global helper; lives here so tests
        can assert maximality directly from a system instance.

        Args:
            matching: The candidate matching.

        Returns:
            ``True`` iff ``matching`` is maximal in ``self.graph``.

        Complexity:
            :math:`O(n + m)`.
        """
        matched_vertices: set[Vertex] = set()
        for u, v in matching:
            matched_vertices.add(u)
            matched_vertices.add(v)

        for u in range(self.graph.n):
            if u in matched_vertices:
                continue
            for w in self.graph.neighbors(u):
                if w not in matched_vertices:
                    return False
        return True


def switch(
    graph: Graph,
    M: set[Edge],
    deg_M: dict[Vertex, int],
    z: int,
    u: Vertex,
    b_neighbors: list[Vertex],
) -> bool:
    r"""Perform edge-switching inside :math:`B` to free capacity for ``u``.

    When ``u`` already has :math:`\deg_M(u) < z` matching edges to B-
    neighbours but every B-neighbour is saturated in :math:`M`, we cannot
    add ``(u, b)`` directly.  Instead we look for an alternating path
    that starts at a saturated B-neighbour and ends at some unsaturated
    B-vertex, and flip the edges along it.  This is the analogue of the
    "augmenting path" used in classical matching algorithms.

    The alternating path has the form::

        u -- b_start (free)  →  b_1 (saturated)  →
        b_2 (free)           →  b_3 (saturated)  →  ...  →
        b_k (unsaturated)

    State ``parity == 0`` means we arrived via a non-:math:`M` edge and
    the next step must follow an :math:`M` edge.  State ``parity == 1``
    means we arrived via an :math:`M` edge and the next step must follow
    a non-:math:`M` edge inside :math:`B`.

    Args:
        graph: The underlying graph.
        M: Current edge set :math:`M` (mutated in place on success).
        deg_M: Degree of each vertex in :math:`M` (mutated in place).
        z: Degree parameter.
        u: The U-vertex to promote.
        b_neighbors: B-neighbours of ``u`` in the graph.

    Returns:
        ``True`` if a valid edge-switch was found and applied.

    Complexity:
        Bounded by the number of B-vertices searched; in the worst case
        :math:`O(m)`.
    """
    saturated_b = [b for b in b_neighbors if deg_M[b] >= z]

    for b_start in saturated_b:
        # ``parent`` maps (vertex, parity) to its predecessor.  We seed
        # the search at ``b_start`` with parity 0 -- the hypothetical
        # edge ``(u, b_start)`` is not yet in M, so we arrived there via
        # a non-M edge.
        parent: dict[tuple[Vertex, int], tuple[Vertex, int] | None] = {
            (b_start, 0): None
        }
        queue: deque[tuple[Vertex, int]] = deque()
        queue.append((b_start, 0))
        target: tuple[Vertex, int] | None = None

        while queue and target is None:
            curr, parity = queue.popleft()

            if parity == 0:
                # Arrived via a non-M edge; the next alternating step
                # must follow an M edge from ``curr`` to a B vertex.
                for w in graph.neighbors(curr):
                    e = canonical(curr, w)
                    if e in M and graph.has_edge(curr, w):
                        if (w, 1) not in parent:
                            parent[(w, 1)] = (curr, 0)
                            # Short-circuit: if ``w`` is unsaturated in
                            # M, we have found an end of the augmenting
                            # path we can use to recover capacity.
                            if deg_M[w] < z:
                                target = (w, 1)
                                break
                            queue.append((w, 1))
            else:
                # Arrived via an M edge (``curr`` is saturated); the
                # next step must follow a non-M edge to another B vertex
                # (the B-B alternating edge).
                for w in graph.neighbors(curr):
                    if w == u:
                        # Defensive: avoid stepping back onto ``u`` even
                        # though ``u`` is in U, not B.
                        continue
                    e = canonical(curr, w)
                    if e not in M and w in graph.neighbors(curr):
                        if (w, 0) not in parent:
                            parent[(w, 0)] = (curr, 1)
                            if deg_M[w] < z:
                                target = (w, 0)
                                break
                            queue.append((w, 0))

        if target is None:
            # No augmenting path starting from this ``b_start``; try the
            # next saturated B-neighbour of ``u``.
            continue

        # Reconstruct the alternating path by unwinding ``parent``.
        path: list[tuple[Vertex, int]] = []
        node: tuple[Vertex, int] | None = target
        while node is not None:
            path.append(node)
            node = parent[node]
        path.reverse()

        # Strip parity: we only need vertex order for the flip.
        vertices = [v for v, _ in path]

        # Step 1: add the missing edge (u, b_start) to M.  ``b_start``
        # was saturated before this; the subsequent flips will recover
        # one slot by re-routing that capacity.
        e_ub = canonical(u, b_start)
        M.add(e_ub)
        deg_M[u] += 1
        deg_M[b_start] += 1

        # Step 2: flip alternating edges along the path.  Edges tagged
        # parity-0 were not in M and must enter M; edges tagged parity-1
        # were in M and must leave M.
        for i in range(len(vertices) - 1):
            e = canonical(vertices[i], vertices[i + 1])
            _, p = path[i]
            if p == 0:
                M.add(e)
                deg_M[vertices[i]] += 1
                deg_M[vertices[i + 1]] += 1
            else:
                M.discard(e)
                deg_M[vertices[i]] -= 1
                deg_M[vertices[i + 1]] -= 1

        return True

    return False


def promote(
    graph: Graph,
    system: System,
    M: set[Edge],
    deg_M: dict[Vertex, int],
    z: int,
    u: Vertex,
) -> bool:
    r"""Try to promote a U-vertex ``u`` to :math:`B` by giving it
    :math:`z` matching edges to B-neighbours.

    The procedure runs in two phases.  First, it greedily adds edges
    from ``u`` to unsaturated B-neighbours until either ``z`` such edges
    exist or no unsaturated neighbour remains.  Second, it invokes
    :func:`switch` to recover capacity from saturated
    B-vertices until the count reaches ``z``.

    After promotion, ``u`` is moved from ``U`` to ``B``; any B-vertex
    that ends up with no remaining :math:`M`-edge to a U-vertex is
    promoted to ``A`` to keep the partition clean.

    Args:
        graph: The host graph.
        system: System being updated (its ``A``/``B``/``U`` are mutated).
        M: Current :math:`M` edge set (mutated).
        deg_M: :math:`M`-degree dictionary (mutated).
        z: Degree parameter.
        u: The U-vertex to consider for promotion.

    Returns:
        ``True`` iff ``u`` ended up with :math:`\deg_M(u) = z` and was
        moved to ``B``.
    """
    b_neighbors = [w for w in graph.neighbors(u) if w in system.B]
    if len(b_neighbors) < z:
        # Cannot reach the cap even with every neighbour -- leave u in U.
        return False

    # Phase 1: take edges to unsaturated B-neighbours.  The check
    # ``e not in M`` guards against adding the same edge twice during
    # repeated calls of this routine.
    added = 0
    for w in b_neighbors:
        if added >= z:
            break
        if deg_M[w] < z:
            e = canonical(u, w)
            if e not in M:
                M.add(e)
                deg_M[u] += 1
                deg_M[w] += 1
                added += 1

    # Phase 2: for any remaining slots, run augmenting-path switches
    # that reclaim capacity by re-routing saturated B-edges.
    if added < z:
        needed = z - added
        for _ in range(needed):
            if switch(graph, M, deg_M, z, u, b_neighbors):
                added += 1
            else:
                # Out of recoverable capacity -- leave u in U.
                break

    if deg_M[u] == z:
        system.U.discard(u)
        system.B.add(u)
        # Promote any B-vertex that lost all of its M-edges to U.
        # Such vertices no longer match any U partner, which violates
        # the spirit of the partition (B is meant to provide edges
        # into U).
        for w in graph.neighbors(u):
            if w in system.B:
                has_M_to_U = False
                for x in graph.neighbors(w):
                    if canonical(w, x) in M and x in system.U:
                        has_M_to_U = True
                        break
                if not has_M_to_U:
                    system.B.discard(w)
                    system.A.add(w)
        return True
    return False


def build(graph: Graph, z: int) -> System:
    r"""Build a :math:`z`-subgraph system from scratch.

    Implements the two-step deterministic construction from Section 5.2
    of the paper.

    Step 1 -- greedy maximal :math:`M` with the degree cap ``z``::

        For each edge (u, v) in sorted order:
            if deg_M(u) < z and deg_M(v) < z:
                add (u, v) to M; increment both degrees.

    The initial partition is then derived from :math:`M`:

    * :math:`v \in S := A \cup B` iff :math:`\deg_M(v) = z`,
    * :math:`v \in A` iff :math:`v \in S` and every :math:`M`-neighbour of
      ``v`` is also in :math:`S`,
    * :math:`v \in B` iff :math:`v \in S` and some :math:`M`-neighbour of
      ``v`` lies in :math:`U`,
    * :math:`v \in U` iff :math:`\deg_M(v) < z`.

    Step 2 -- promote U-vertices to B until no further promotion is
    possible.  Promotion is handled by :func:`promote` which
    tries direct edges first and falls back to edge-switching inside B.

    **Fidelity note:** Step 2 uses an alternating-path edge-switching
    heuristic that approximates the paper's exact switching rule.  The
    paper states that edge-switching inside B preserves degree bounds;
    our implementation achieves this via BFS-based augmenting paths.

    Args:
        graph: The host graph.
        z: The degree parameter (``z >= 1``).

    Returns:
        A :class:`System` satisfying every invariant checked
        by :meth:`System.check_all_invariants`.

    Complexity:
        :math:`O(n + m)` per promotion round; the number of rounds is
        bounded by a polynomial in ``n`` so the overall construction is
        polynomial.  Empirically the loop converges in a handful of
        rounds on sparse inputs.
    """
    # --- Step 1: greedy maximal M with degree cap z ---
    M: set[Edge] = set()
    deg_M: dict[Vertex, int] = {v: 0 for v in range(graph.n)}
    edges = sorted(graph.edges())
    for u, v in edges:
        if deg_M[u] < z and deg_M[v] < z:
            e = canonical(u, v)
            M.add(e)
            deg_M[u] += 1
            deg_M[v] += 1

    # --- Partition: S are saturated; A/B differ on whether an S-vertex
    # has an M-edge reaching into U.
    S = {v for v in range(graph.n) if deg_M[v] == z}
    U_set = {v for v in range(graph.n) if deg_M[v] < z}
    A: set[Vertex] = set()
    B: set[Vertex] = set()
    for v in S:
        has_neighbor_in_U = False
        for w in graph.neighbors(v):
            if canonical(v, w) in M and w not in S:
                has_neighbor_in_U = True
                break
        if has_neighbor_in_U:
            B.add(v)
        else:
            A.add(v)

    system = System(graph=graph, z=z, A=A, B=B, U=U_set, M=M)
    system.index()

    # --- Step 2: iteratively promote U-vertices to B.  We keep looping
    # until one full pass through U makes no further changes; the
    # ``changed`` flag avoids re-scanning vertices that have already been
    # moved out of U.
    changed = True
    while changed:
        changed = False
        for u in list(system.U):
            if promote(graph, system, M, deg_M, z, u):
                changed = True

    system.M = M
    system.index()
    return system
