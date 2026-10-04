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
      :math:`L` thereafter (or to invoke :meth:`index`).

Limitations:
    * :func:`switch` remains available as a standalone alternating-path
      utility, but the canonical builder uses the paper's witness swaps.
"""

from __future__ import annotations

from array import array
from bisect import bisect_left
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeAlias, Union

from axiom.graph import Adjacency
from axiom.storage import Packed
from axiom.types import Edge, Graph, Matching, Vertex, canonical
from axiom.vertices import Vertices

CacheRow: TypeAlias = Union[list[Vertex], "array[int]"]

if TYPE_CHECKING:
    from axiom.systems import Systems


def degrees(n: int) -> array[int]:
    """Allocate compact zeroed matching-degree counters for a vertex range."""
    if type(n) is not int or n < 0:
        raise ValueError("degree counter length must be a nonnegative integer")
    typecode = "I" if n <= Vertices.empty and array("I").itemsize >= 4 else "Q"
    return array(typecode, [0]) * n


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
        lambda_lists: Nonempty rows :math:`\Lambda(u) = N_G(u) \cap (B \cup U)`;
            a missing key represents an empty row.
        L_lists: Nonempty rows :math:`L(a) = N_G(a) \cap U`;
            a missing key represents an empty row.

    Lifecycle:
        A system is normally built by :func:`build`.  After any
        mutation of ``self.graph`` the cached lists in ``lambda_lists``
        and ``L_lists`` must be refreshed via
        :meth:`index`.  Mutating ``A``, ``B``, ``U``, or
        ``M`` directly is permitted (this is what the dynamic update
        code does) but should be followed by
        :meth:`check` to verify the system stays legal.

    Thread-safety:
        Not thread-safe.  A ``System`` should be touched only
        from the thread that owns the underlying ``Graph``.
    """

    graph: Graph
    z: int
    A: set[Vertex] | Vertices = field(default_factory=set)
    B: set[Vertex] | Vertices = field(default_factory=set)
    U: set[Vertex] | Vertices = field(default_factory=set)
    M: set[Edge] = field(default_factory=set)
    lambda_lists: dict[Vertex, CacheRow] = field(default_factory=dict)
    L_lists: dict[Vertex, CacheRow] = field(default_factory=dict)
    journal: Systems | None = field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Compact dense partitions while retaining ordinary sparse sets."""
        if self.graph.n > 0:
            if type(self.A) is set and len(self.A) * 8 >= self.graph.n:
                self.A = Vertices(self.graph.n, self.A, ordered=False)
            if type(self.B) is set and len(self.B) * 8 >= self.graph.n:
                self.B = Vertices(self.graph.n, self.B, ordered=False)
            if type(self.U) is set and len(self.U) * 12 >= self.graph.n:
                self.U = Vertices(self.graph.n, self.U)

    @property
    def S(self) -> set[Vertex]:
        r"""Return :math:`S = A \cup B`, the set of saturated vertices."""
        return self.A | self.B

    def saturated(self) -> Iterator[Vertex]:
        r"""Yield saturated vertices without allocating the :math:`A \cup B` set.

        Internal scans use this iterator when they only need traversal. The
        public ``S`` property remains a set for callers that require membership,
        mutation, or a detached snapshot.
        """
        yield from self.A
        yield from self.B

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
        for v in self.saturated():
            if self.degree(v) != self.z:
                return False
        for u in self.U:
            if self.degree(u) > self.z:
                return False
        return True

    def check_edges(self) -> bool:
        r"""Check that every stored :math:`M` edge is a live canonical edge.

        Degree checks iterate the host graph and therefore cannot observe an
        edge that was left stale in ``M`` after a graph transition.  Rejecting
        such state explicitly keeps the subgraph-system certificate tied to
        its graph rather than silently ignoring the stale edge.
        """
        for left, right in self.M:
            if (
                not isinstance(left, int)
                or isinstance(left, bool)
                or not isinstance(right, int)
                or isinstance(right, bool)
                or not 0 <= left < self.graph.n
                or not 0 <= right < self.graph.n
                or left >= right
                or not self.graph.has_edge(left, right)
            ):
                return False
        return True

    def check_no_u_u_edges(self) -> bool:
        r"""Check that no edge in :math:`M` has both endpoints in :math:`U`.

        The paper's initial construction removes these edges after the
        degree-capped greedy pass.  Keeping the condition explicit prevents
        a base-level system from being accepted with a weaker invariant than
        the recursive construction requires.
        """
        return all(left not in self.U or right not in self.U for left, right in self.M)

    def check_partition(self) -> bool:
        """Check that ``A``, ``B``, and ``U`` partition the graph vertices."""
        if len(self.A) + len(self.B) + len(self.U) != self.graph.n:
            return False
        if type(self.U) is Vertices:
            for vertex in self.A:
                if (
                    type(vertex) is not int
                    or not 0 <= vertex < self.graph.n
                    or vertex in self.B
                    or vertex in self.U
                ):
                    return False
            for vertex in self.B:
                if (
                    type(vertex) is not int
                    or not 0 <= vertex < self.graph.n
                    or vertex in self.U
                ):
                    return False
            return True
        groups = (self.A, self.B, self.U)
        for group in groups:
            for vertex in group:
                if type(vertex) is not int or not 0 <= vertex < self.graph.n:
                    return False
        return not (
            any(vertex in self.B or vertex in self.U for vertex in self.A)
            or any(vertex in self.U for vertex in self.B)
        )

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
        r"""Check property (P2) for every matching edge incident to A.

        Without (P2) the A-rematching scan can miss some valid partners
        and the matching maintained in :math:`M^*` may lose edges.

        Returns:
            ``True`` iff (P2) holds for every :math:`a \in A`.

        Complexity:
            :math:`O(n + m)`.
        """
        for a in self.A:
            for w in self.partner_in(a):
                if w not in self.A and w not in self.B:
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
        if (
            type(self.lambda_lists) is not dict
            or any(vertex not in self.U for vertex in self.lambda_lists)
            or any(
                not self.valid_cache_row(row) or not row
                for row in self.lambda_lists.values()
            )
        ):
            return False
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

        Symmetric to :meth:`check_lambda` but for :math:`A`-vertices.

        Returns:
            ``True`` iff every cached list is current.

        Complexity:
            :math:`O(n + m)`.
        """
        if (
            type(self.L_lists) is not dict
            or any(vertex not in self.A for vertex in self.L_lists)
            or any(
                not self.valid_cache_row(row) or not row
                for row in self.L_lists.values()
            )
        ):
            return False
        for a in self.A:
            expected = sorted(w for w in self.graph.neighbors(a) if w in self.U)
            actual = sorted(self.L_lists.get(a, []))
            if expected != actual:
                return False
        return True

    def check(self) -> bool:
        """Return ``True`` iff every invariant of the :math:`z`-system holds.

        Equivalent to a logical AND of :meth:`check_edges`,
        :meth:`check_no_u_u_edges`, :meth:`check_partition`,
        :meth:`check_bound`, :meth:`check_u`, :meth:`check_p1`,
        :meth:`check_p2`, :meth:`check_lambda`, and :meth:`check_L`.

        Returns:
            ``True`` iff the system is legal.

        Complexity:
            :math:`O(n + m)`.
        """
        return (
            self.check_edges()
            and self.check_no_u_u_edges()
            and self.check_partition()
            and self.check_bound()
            and self.check_u()
            and self.check_p1()
            and self.check_p2()
            and self.check_lambda()
            and self.check_L()
        )

    def index(self) -> None:
        r"""Recompute :math:`\Lambda(u)` and :math:`L(a)` from the current graph.

        Call this whenever the host graph has been mutated so that the
        cached lists stay consistent. Replaces ``self.lambda_lists`` and
        ``self.L_lists`` with maps containing only nonempty rows; old rows are
        not edited in place.

        Complexity:
            :math:`O(n + m)`.  The list is sorted to make
            maximality-equality checks deterministic.
        """
        self.lambda_lists = {}
        for u in self.U:
            values = sorted(
                w for w in self.graph.neighbors(u) if w in self.B or w in self.U
            )
            if values:
                self.lambda_lists[u] = self.cache_row(values)
        self.L_lists = {}
        for a in self.A:
            values = sorted(w for w in self.graph.neighbors(a) if w in self.U)
            if values:
                self.L_lists[a] = self.cache_row(values)

    def cache_row(self, values: list[Vertex]) -> CacheRow:
        """Choose compact fixed-width rows only for the owned Packed backend."""
        if type(self.graph) is Packed:
            return array("I", values)
        return values

    def valid_cache_row(self, values: object) -> bool:
        """Require backend-appropriate mutable row storage and 32-bit labels."""
        if type(self.graph) is Packed:
            return (
                type(values) is array
                and values.typecode == "I"
                and values.itemsize == 4
            )
        return type(values) is list

    @staticmethod
    def change(values: CacheRow, value: Vertex, added: bool) -> None:
        """Apply a delta to a sorted unique list without sorting the whole row.

        Lookup is logarithmic; insertion/removal still shifts O(row length)
        entries. Duplicate insertion and absent deletion leave the row untouched.
        Owners provide valid labels and sorted lists, not arbitrary raw edits.
        """
        position = bisect_left(values, value)
        present = position < len(values) and values[position] == value
        if added and not present:
            values.insert(position, value)
        elif not added and present:
            values.pop(position)

    def update(self, left: Vertex, right: Vertex, added: bool) -> None:
        r"""Update Lambda/L endpoint rows after their graph delta is applied.

        Basic and recursive owners use this same mutation boundary. Membership
        tests never materialize B union U. Other rows and their identities remain
        untouched. This method does not edit the graph or provide standalone undo;
        the owner must serialize access and restore coupled state on failure.
        """
        if type(added) is not bool:
            raise ValueError("system delta requires a boolean")
        if (
            any(
                type(vertex) is not int or not 0 <= vertex < self.graph.n
                for vertex in (left, right)
            )
            or left == right
        ):
            raise ValueError("system delta requires distinct vertices in [0, n)")
        if self.graph.has_edge(left, right) != added:
            raise ValueError("system graph delta must precede cache update")
        for source, target in ((left, right), (right, left)):
            if source in self.U and (target in self.B or target in self.U):
                if self.journal is None:
                    values = self.lambda_lists.get(source)
                    if values is None and added:
                        values = self.cache_row([])
                        self.lambda_lists[source] = values
                    if values is not None:
                        self.change(values, target, added)
                        if not added and not values:
                            self.lambda_lists.pop(source, None)
                else:
                    self.journal.edit(self.lambda_lists, source, target, added)
                    if not added and not self.lambda_lists.get(source):
                        self.journal.forget(self.lambda_lists, source)
            if source in self.A and target in self.U:
                if self.journal is None:
                    values = self.L_lists.get(source)
                    if values is None and added:
                        values = self.cache_row([])
                        self.L_lists[source] = values
                    if values is not None:
                        self.change(values, target, added)
                        if not added and not values:
                            self.L_lists.pop(source, None)
                else:
                    self.journal.edit(self.L_lists, source, target, added)
                    if not added and not self.L_lists.get(source):
                        self.journal.forget(self.L_lists, source)

    def restrict(self, allowed: set[Edge] | Graph) -> None:
        """Keep matching edges present in an allowed set or graph snapshot."""
        if self.journal is None:
            if isinstance(allowed, set):
                self.M.intersection_update(allowed)
            else:
                removed = tuple(edge for edge in self.M if not allowed.has_edge(*edge))
                self.M.difference_update(removed)
        else:
            self.journal.restrict(self.M, allowed)

    def __setattr__(self, name: str, value: object) -> None:
        """Protect the active transaction handle using Python protocol spelling."""
        if name == "journal" and getattr(self, "journal", None) is not None:
            raise RuntimeError("active system journal cannot be replaced")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        """Reject deletion of bound undo while allowing ordinary field access."""
        if name == "journal" and self.journal is not None:
            raise RuntimeError("active system journal cannot be deleted")
        object.__delattr__(self, name)

    def maximal(self, matching: Matching) -> bool:
        """Return ``True`` iff ``matching`` is maximal in the current ``graph``.

        Validate a candidate matching directly against this system's graph.

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
                for w in sorted(graph.neighbors(curr)):
                    e = canonical(curr, w)
                    if w != u and e in M and graph.has_edge(curr, w):
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
                for w in sorted(graph.neighbors(curr)):
                    if w == u:
                        # Defensive: avoid stepping back onto ``u`` even
                        # though ``u`` is in U, not B.
                        continue
                    e = canonical(curr, w)
                    if e not in M:
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

        e_ub = canonical(u, b_start)
        changes = {e_ub: True}
        for i in range(len(vertices) - 1):
            e = canonical(vertices[i], vertices[i + 1])
            _, p = path[i]
            changes[e] = p != 0

        before_edges = {edge: edge in M for edge in changes}
        deltas: dict[Vertex, int] = {}
        for edge, present in changes.items():
            if before_edges[edge] == present:
                continue
            delta = 1 if present else -1
            deltas[edge[0]] = deltas.get(edge[0], 0) + delta
            deltas[edge[1]] = deltas.get(edge[1], 0) + delta

        before_degrees = {vertex: deg_M[vertex] for vertex in deltas}
        after_degrees = {
            vertex: before_degrees[vertex] + delta for vertex, delta in deltas.items()
        }
        if any(degree > z for degree in after_degrees.values()) or any(
            before_degrees[vertex] == z and vertex != u and degree != z
            for vertex, degree in after_degrees.items()
        ):
            continue

        try:
            for edge, present in changes.items():
                if before_edges[edge] == present:
                    continue
                if present:
                    M.add(edge)
                else:
                    M.discard(edge)
            for vertex, degree in after_degrees.items():
                deg_M[vertex] = degree
        except Exception:
            for edge, present in before_edges.items():
                if present:
                    M.add(edge)
                else:
                    M.discard(edge)
            for vertex, degree in before_degrees.items():
                deg_M[vertex] = degree
            raise

        return True

    return False


def promote(
    graph: Graph,
    system: System,
    M: set[Edge],
    deg_M: array[int],
    z: int,
    u: Vertex,
) -> bool:
    r"""Try to promote a U-vertex to B with z matching edges to B-neighbors.

    The procedure follows the paper's ``ProcProcessU`` construction.  It
    selects B-neighbours and, for each saturated neighbour, swaps out its
    existing B-U witness edge before inserting the new edge.

    After promotion, ``u`` is moved from ``U`` to ``B``; any B-vertex
    that ends up with no remaining :math:`M`-edge to a U-vertex is
    promoted to ``A`` to keep the partition clean.

    Args:
        graph: The host graph.
        system: System being updated (its ``A``/``B``/``U`` are mutated).
        M: Current :math:`M` edge set (mutated).
        deg_M: Packed :math:`M`-degree counters (mutated).
        z: Degree parameter.
        u: The U-vertex to consider for promotion.

    Returns:
        ``True`` iff ``u`` ended up with :math:`\deg_M(u) = z` and was
        moved to ``B``.
    """
    b_neighbors = [
        w
        for w in sorted(graph.neighbors(u))
        if w in system.B and canonical(u, w) not in M
    ]
    needed = z - deg_M[u]
    if needed <= 0:
        system.U.discard(u)
        system.B.add(u)
        return True
    if len(b_neighbors) < needed:
        # Cannot reach the cap even with every neighbour -- leave u in U.
        return False

    candidates: list[tuple[Vertex, Edge | None]] = []
    for b in b_neighbors:
        if deg_M[b] < z:
            candidates.append((b, None))
            continue
        witnesses = sorted(
            edge
            for edge in M
            if b in edge and (edge[0] in system.U or edge[1] in system.U)
        )
        if not witnesses:
            raise RuntimeError(
                f"B invariant violated: saturated vertex {b} has no U witness"
            )
        candidates.append((b, witnesses[0]))

    if len(candidates) < needed:
        return False

    for b, witness in candidates[:needed]:
        if witness is not None:
            M.remove(witness)
            for endpoint in witness:
                deg_M[endpoint] -= 1
        edge = canonical(u, b)
        M.add(edge)
        deg_M[u] += 1
        deg_M[b] += 1

    if deg_M[u] == z:
        system.U.discard(u)
        if any(
            endpoint in system.U
            for edge in M
            if u in edge
            for endpoint in edge
            if endpoint != u
        ):
            system.B.add(u)
            system.A.discard(u)
        else:
            system.A.add(u)
            system.B.discard(u)

        for b in list(system.B):
            if not any(
                b in edge and (edge[0] in system.U or edge[1] in system.U) for edge in M
            ):
                system.B.discard(b)
                system.A.add(b)
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
    possible.  Promotion is handled by :func:`promote` using the paper's
    direct B/U witness-swap construction.

    Args:
        graph: The host graph.
        z: The degree parameter (``z >= 1``).

    Returns:
        A :class:`System` satisfying every invariant checked
        by :meth:`System.check`.

    Complexity:
        :math:`O(n + m)` per promotion round; the number of rounds is
        bounded by a polynomial in ``n`` so the overall construction is
        polynomial.  Empirically the loop converges in a handful of
        rounds on sparse inputs.
    """
    if not isinstance(z, int) or isinstance(z, bool) or z <= 0:
        raise ValueError(f"z must be a positive integer, got {z!r}")
    # If the cap exceeds every host degree, the greedy M can never saturate a
    # vertex. Thus S=A=B=empty, U=V, and the paper's U-U removal discards every
    # greedy edge. Construct that exact final state directly instead of
    # transiently retaining all graph edges in a Python set and scanning a
    # million unchanged U vertices in the promotion loop.
    if type(graph) in (Adjacency, Packed) and all(
        graph.degree(vertex) < z for vertex in range(graph.n)
    ):
        system = System(
            graph=graph,
            z=z,
            U=Vertices(graph.n, range(graph.n)),
        )
        system.index()
        return system
    # --- Step 1: greedy maximal M with degree cap z ---
    M: set[Edge] = set()
    # Matching degrees are bounded integers indexed by dense vertex labels;
    # a Python dict stores substantial per-entry hash-table and object overhead.
    deg_M = degrees(graph.n)
    if type(graph) in (Adjacency, Packed):
        # Both owned graph implementations stream rows in increasing vertex
        # and neighbor order. Keep the sparse rebuild path streaming to avoid
        # an O(m) Python edge-tuple/list copy and O(m log m) global sort.
        edges = graph.edges()
    else:
        # Preserve deterministic construction for third-party Graph
        # implementations whose edge iterator has no ordering guarantee.
        edges = iter(sorted(graph.edges()))
    for u, v in edges:
        if deg_M[u] < z and deg_M[v] < z:
            e = canonical(u, v)
            M.add(e)
            deg_M[u] += 1
            deg_M[v] += 1

    # --- Partition: S are saturated; A/B differ on whether an S-vertex
    # has an M-edge reaching into U.  The paper removes all U-U edges from
    # the greedy edge set before creating the system.  S is determined from
    # the capped greedy pass, while deg_M below is updated to describe the
    # actual matching retained by the system.
    saturated_count = sum(degree == z for degree in deg_M)
    S: set[Vertex] | Vertices
    if graph.n and saturated_count * 8 >= graph.n:
        S = Vertices(graph.n, (v for v in range(graph.n) if deg_M[v] == z))
    else:
        S = {v for v in range(graph.n) if deg_M[v] == z}
    ucount = graph.n - len(S)
    U_set: set[Vertex] | Vertices
    if graph.n and ucount * 12 >= graph.n:
        U_set = Vertices(graph.n, (v for v in range(graph.n) if deg_M[v] < z))
    else:
        U_set = {v for v in range(graph.n) if deg_M[v] < z}
    # Do not materialize a second graph-sized set of matching edges here.
    # On large sparse graphs this temporary overlaps both the greedy M and
    # the Lambda/L row maps constructed by index(), substantially increasing
    # the build peak.  Stream the host edges instead; only matching edges
    # whose endpoints are both in U can be removed by the paper's rule.
    for u, v in graph.edges():
        if u in U_set and v in U_set and (u, v) in M:
            M.remove((u, v))
            deg_M[u] -= 1
            deg_M[v] -= 1
    # CPython sets retain a large hash table after mass removals.  In the
    # common low-z-saturation case all greedy M edges are U-U, so explicitly
    # release that table before the persistent neighbor indexes are built.
    if not M:
        M.clear()

    A_values: list[Vertex] = []
    B_values: list[Vertex] = []
    for v in S:
        has_neighbor_in_U = False
        for w in sorted(graph.neighbors(v)):
            if canonical(v, w) in M and w not in S:
                has_neighbor_in_U = True
                break
        if has_neighbor_in_U:
            B_values.append(v)
        else:
            A_values.append(v)

    A: set[Vertex] | Vertices = (
        Vertices(graph.n, A_values)
        if graph.n and len(A_values) * 8 >= graph.n
        else set(A_values)
    )
    B: set[Vertex] | Vertices = (
        Vertices(graph.n, B_values)
        if graph.n and len(B_values) * 8 >= graph.n
        else set(B_values)
    )

    system = System(graph=graph, z=z, A=A, B=B, U=U_set, M=M)
    # These construction-only containers can be large on production graphs.
    # Release them before materializing the persistent Lambda/L indexes.
    del S, A_values, B_values
    system.index()

    # --- Step 2: iteratively promote U-vertices to B.  We keep looping
    # until one full pass through U makes no further changes; the
    # ``changed`` flag avoids re-scanning vertices that have already been
    # moved out of U.
    changed = True
    while changed:
        changed = False
        for u in sorted(system.U):
            if promote(graph, system, M, deg_M, z, u):
                changed = True

    system.M = M
    system.index()
    return system
