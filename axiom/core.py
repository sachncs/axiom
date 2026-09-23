r"""Fully dynamic maximal matching algorithm.

This module implements the core dynamic matching interface with single-level
and recursive multi-level supporting systems.  The paper's exact asymptotic
guarantees require additional coloring and phase-maintenance machinery; this
module does not claim those bounds for the current Python implementation.

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

import copy
from collections.abc import Iterator
from contextlib import contextmanager

from axiom.augment import augment as _augment
from axiom.color import Vizing
from axiom.graph import Adjacency
from axiom.hierarchy import Hierarchy
from axiom.ledger import Ledger
from axiom.matching import is_maximal_matching, partners
from axiom.paper_coloring import PaperFanColorer
from axiom.rebuild import Basic, Multilevel
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
    * ``"multilevel"`` --- the recursive multi-level implementation.

    The instance is stateful: every :meth:`insert` and
    :meth:`delete` mutates the graph and matching and may trigger
    a full rebuild of the supporting :math:`z`-system.  Use
    :attr:`accountant` (or the convenience :attr:`stats`) to inspect
    the amortised cost.

    Attributes:
        n: Number of vertices (fixed).
        mode: ``"basic"`` or ``"multilevel"``.
        graph: The underlying graph.
        colorer: The edge coloring implementation.
        matched_edges: The maintained maximal matching.
        matched_vertices: Convenience cache of vertices incident to
            some edge of the matching.
        partner_map: Bidirectional partner map for O(1) partner lookup.
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
        accountant: Bookkeeping counters (Ledger).
        stats: Snapshot of :attr:`accountant` counters as a dict.

    Args:
        n: Number of vertices (fixed for the lifetime of the instance).
        mode: Either ``"basic"`` or ``"multilevel"``.
        graph: Optional graph implementation (defaults to ``Adjacency``).
        colorer: Optional edge colorer.  The default is ``Vizing`` for
            ``basic`` and the paper fan colorer for ``multilevel``.

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
    ) -> None:
        if not isinstance(n, int) or isinstance(n, bool):
            raise ValueError(f"n must be an integer, got {n!r}")
        if n < 0:
            raise ValueError(f"n must be non-negative, got {n}")
        if mode not in {"basic", "multilevel"}:
            raise ValueError(f"mode must be 'basic' or 'multilevel', got {mode}")
        if colorer is not None and not callable(getattr(colorer, "color", None)):
            raise ValueError(
                "colorer must provide a callable color(graph, delta) method"
            )
        self.n = n
        self.mode = mode
        self.graph = graph if graph is not None else Adjacency(n)
        self.__validate_graph(self.graph, n)
        self.colorer = (
            colorer
            if colorer is not None
            else PaperFanColorer()
            if mode == "multilevel"
            else Vizing()
        )
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
        self.phase_graph: Graph | None = None
        self.level_zs: list[int] = []
        self.level_phase_lengths: list[int] = []
        self.eta: int = 0
        self.k: int = 0
        self.inserted_edges: set[tuple[int, int]] = set()
        self.deleted_edges: set[tuple[int, int]] = set()
        self.inserted_incident_counts: dict[Vertex, int] = {
            vertex: 0 for vertex in range(n)
        }
        self.bad_vertices: set[Vertex] = set()
        self.H: dict[Vertex, set[Vertex]] = {}
        self.H_reverse: dict[Vertex, set[Vertex]] = {}
        self.H_tilde: set[tuple[Vertex, Vertex]] = set()
        self.S_hat: set[Vertex] = set()

        self.accountant = Ledger()

        self.policy = Basic() if mode == "basic" else Multilevel()
        self.policy.configure(self)
        self.policy.rebuild(self)

    @staticmethod
    def __validate_graph(graph: Graph, n: int) -> None:
        """Validate a custom graph before it enters mutable matcher state."""
        required = (
            "add_edge",
            "remove_edge",
            "has_edge",
            "degree",
            "neighbors",
            "edges",
            "num_edges",
        )
        missing = [
            name for name in required if not callable(getattr(graph, name, None))
        ]
        if missing:
            raise ValueError(
                "graph must implement the Graph protocol; missing " + ", ".join(missing)
            )
        graph_n = getattr(graph, "n", None)
        if not isinstance(graph_n, int) or isinstance(graph_n, bool):
            raise ValueError("graph.n must be an integer")
        if graph_n != n:
            raise ValueError(f"graph.n must equal matcher n ({n}), got {graph_n}")

        try:
            listed_edges = list(graph.edges())
            listed_count = graph.num_edges()
        except Exception as error:
            raise ValueError("graph edges and num_edges() must be readable") from error
        if not isinstance(listed_count, int) or isinstance(listed_count, bool):
            raise ValueError("graph.num_edges() must return an integer")
        if listed_count != len(listed_edges):
            raise ValueError("graph.num_edges() disagrees with graph.edges()")

        edge_set: set[tuple[int, int]] = set()
        for edge in listed_edges:
            if not isinstance(edge, tuple) or len(edge) != 2:
                raise ValueError("graph.edges() must yield 2-tuples")
            left, right = edge
            if (
                not isinstance(left, int)
                or isinstance(left, bool)
                or not isinstance(right, int)
                or isinstance(right, bool)
                or not 0 <= left < n
                or not 0 <= right < n
            ):
                raise ValueError("graph.edges() contains an out-of-range endpoint")
            if left >= right:
                raise ValueError("graph.edges() must yield canonical edges with u < v")
            if edge in edge_set:
                raise ValueError("graph.edges() contains duplicate edges")
            edge_set.add(edge)

        adjacency_edges: set[tuple[int, int]] = set()
        for vertex in range(n):
            try:
                neighbours = list(graph.neighbors(vertex))
                degree = graph.degree(vertex)
            except Exception as error:
                raise ValueError(
                    "graph neighbors() and degree() must be readable"
                ) from error
            if not isinstance(degree, int) or isinstance(degree, bool):
                raise ValueError("graph.degree() must return integers")
            if degree != len(neighbours) or len(set(neighbours)) != len(neighbours):
                raise ValueError("graph.degree() disagrees with graph.neighbors()")
            for neighbour in neighbours:
                if (
                    not isinstance(neighbour, int)
                    or isinstance(neighbour, bool)
                    or not 0 <= neighbour < n
                    or neighbour == vertex
                ):
                    raise ValueError("graph.neighbors() contains an invalid endpoint")
                adjacency_edges.add(canonical(vertex, neighbour))
                if not graph.has_edge(neighbour, vertex):
                    raise ValueError("graph adjacency must be symmetric")
        if adjacency_edges != edge_set:
            raise ValueError("graph.edges() disagrees with graph.neighbors()")

    def partition(self) -> None:
        if self.system is None:
            self.seed_matching = set()
            self.matchings = []
            return

        sub = Adjacency(self.n)
        for e in self.system.M:
            sub.add_edge(e[0], e[1])

        coloring = self.colorer.color(sub, self.z)

        if set(coloring) != set(self.system.M):
            missing = set(self.system.M) - set(coloring)
            extra = set(coloring) - set(self.system.M)
            raise RuntimeError(
                "edge colorer returned an incomplete coloring: "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )

        self.matchings = [set() for _ in range(self.z + 1)]
        incident_colors: dict[Vertex, set[int]] = {
            vertex: set() for vertex in range(self.n)
        }
        dropped = 0
        for e, c in coloring.items():
            if 0 <= c <= self.z:
                u, v = e
                if c in incident_colors[u] or c in incident_colors[v]:
                    raise RuntimeError(
                        "edge colorer returned a non-proper coloring: "
                        f"color {c} conflicts on edge {e}"
                    )
                incident_colors[u].add(c)
                incident_colors[v].add(c)
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

    def __rebuild_auxiliary(self) -> None:
        """Rebuild the directed H and H-tilde indexes from live state."""
        self.H = {}
        self.H_reverse = {}
        self.H_tilde = set()
        self.S_hat = set()
        if self.system is None:
            return

        self.S_hat = {
            vertex for vertex in self.system.S if vertex not in self.matched_vertices
        }

        for u in sorted(self.system.U):
            neighbours = {
                v
                for v in self.system.lambda_lists.get(u, [])
                if self.system.graph.has_edge(u, v)
            }
            if u not in self.matched_vertices:
                self.H[u] = neighbours
                for v in neighbours:
                    self.H_reverse.setdefault(v, set()).add(u)

        for left, right in self.inserted_edges:
            if left not in self.matched_vertices and right in self.bad_vertices:
                self.H_tilde.add((left, right))
            if right not in self.matched_vertices and left in self.bad_vertices:
                self.H_tilde.add((right, left))

    def __proc_update(self, vertex: Vertex) -> None:
        """Apply the paper's ProcUpdate transition for one vertex."""
        if self.system is None:
            return
        matched = vertex in self.matched_vertices
        if matched:
            self.S_hat.discard(vertex)
            if vertex in self.system.U:
                self.__remove_h_source(vertex)
        else:
            if vertex in self.system.S:
                self.S_hat.add(vertex)
            if vertex in self.system.U:
                # ProcUpdate replaces the source's outgoing H edges.  Remove
                # the old reverse-index entries first; otherwise a changed
                # Lambda list leaves phantom incoming H edges until the next
                # full auxiliary rebuild.
                self.__remove_h_source(vertex)
                targets = {
                    target
                    for target in self.system.lambda_lists.get(vertex, [])
                    if self.system.graph.has_edge(vertex, target)
                }
                self.H[vertex] = targets
                for target in targets:
                    self.H_reverse.setdefault(target, set()).add(vertex)

        if matched:
            # A matched vertex cannot remain an indexed source or target in
            # \tilde H.  Filtering both endpoints is required when the
            # vertex is the bad target of an edge owned by another source.
            self.H_tilde = {edge for edge in self.H_tilde if vertex not in edge}
        else:
            # For an unmatched vertex, replace only its outgoing entries;
            # incoming entries remain valid and are owned by their sources.
            self.H_tilde = {edge for edge in self.H_tilde if edge[0] != vertex}
        if not matched:
            for left, right in self.inserted_edges:
                if left == vertex and right in self.bad_vertices:
                    self.H_tilde.add((left, right))
                elif right == vertex and left in self.bad_vertices:
                    self.H_tilde.add((right, left))

    def __remove_h_source(self, source: Vertex) -> None:
        """Remove one source and all of its reverse-H index entries."""
        targets = self.H.pop(source, set())
        for target in targets:
            incoming = self.H_reverse.get(target)
            if incoming is not None:
                incoming.discard(source)
                if not incoming:
                    self.H_reverse.pop(target, None)

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
        self.__proc_update(u)
        self.__proc_update(v)

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
        self.__proc_update(u)
        self.__proc_update(v)

    def refresh(self) -> None:
        if self.system is None:
            raise RuntimeError(
                "cannot refresh matching without an active z-system; "
                "the rebuild invariant is corrupted"
            )

        matching: Matching = set()
        matched: set[Vertex] = set()
        # The seed is supplied by the edge-colouring phase and must already
        # be a matching.  Silently dropping conflicting edges would change
        # the algorithm and hide a broken colouring invariant.
        for e in self.seed_matching:
            u, v = e
            if not self.graph.has_edge(u, v):
                # A refined hierarchy may retain an ED' edge in its
                # auxiliary system.  Such an edge cannot enter the live
                # maximal matching until it is present in the host graph.
                continue
            if u in matched or v in matched:
                raise RuntimeError(
                    f"seed matching invariant violated: conflicting edge {e}"
                )
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
        self.__rebuild_auxiliary()

    def __check_subphase_boundary(self) -> bool:
        if self.update_count > 0 and self.update_count % self.subphase_length == 0:
            self.subphase_count += 1
            self.__augment_seed_at_subphase_boundary()
            self.accountant.record_subphase_rebuild()
            return True
        return False

    def __augment_seed_at_subphase_boundary(self) -> None:
        self.__augment_seed()

    def __augment_seed(self) -> int:
        """Run the subphase-boundary augmenting-path search over M_1.

        Walk every vertex of :math:`S = A \\cup B` and, for each vertex
        currently unmatched in the seed matching, run an alternating-path
        search.  Returns the
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
                if _augment(
                    self.seed_matching,
                    self.graph.neighbors,
                    s,
                    matched_in_seed.__contains__,
                ):
                    augmented += 1
                    matched_in_seed = {v for e in self.seed_matching for v in e}
        return augmented

    def insert(self, u: Vertex, v: Vertex) -> None:
        """Insert edge ``(u, v)`` and repair the maximal matching.

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        self.__validate_vertex(u)
        self.__validate_vertex(v)
        existed = self.graph.has_edge(u, v)
        if u == v or existed:
            # Self-loops are outside the graph model and duplicate insertions
            # do not constitute graph updates.  Validate endpoints through
            # has_edge above, then leave all dynamic state untouched.
            return
        with self.__atomic_update():
            self.graph.add_edge(u, v)
            if self.mode == "multilevel":
                edge = canonical(u, v)
                self.inserted_edges.add(edge)
                self.deleted_edges.discard(edge)
                # A reinserted edge cancels any deferred deletion retained
                # by the current recursive phase.  Keeping both states would
                # make sync_graph exclude the edge while the phase graph
                # invariant still expected it through E_D'.
                if self.multi is not None:
                    self.multi.deferred_deletions.discard(edge)
                for vertex in edge:
                    self.inserted_incident_counts[vertex] += 1
                    # The paper promotes a good vertex to bad at z + 1
                    # incident inserted edges, not at the z-th edge.
                    if self.inserted_incident_counts[vertex] >= self.z + 1:
                        self.bad_vertices.add(vertex)
            if self.multi is not None:
                self.multi.sync_graph(self.graph, excluded_edges=self.inserted_edges)
            else:
                self.__update_cached_lists(u, v, added=True)
            self.__proc_update(u)
            self.__proc_update(v)
            self.__handle_insertion(u, v)
            self.__advance_update_counter()

    def delete(self, u: Vertex, v: Vertex) -> None:
        """Delete edge ``(u, v)`` and repair the maximal matching.

        Args:
            u: One endpoint.
            v: The other endpoint.
        """
        self.__validate_vertex(u)
        self.__validate_vertex(v)
        if not self.graph.has_edge(u, v):
            self.accountant.record_deletion()
            return
        with self.__atomic_update():
            if self.mode == "multilevel":
                edge = canonical(u, v)
                if edge in self.inserted_edges:
                    self.inserted_edges.remove(edge)
                else:
                    self.deleted_edges.add(edge)
            self.graph.remove_edge(u, v)
            if self.multi is not None:
                self.multi.sync_graph(self.graph, excluded_edges=self.inserted_edges)
            else:
                self.__update_cached_lists(u, v, added=False)
            self.__proc_update(u)
            self.__proc_update(v)
            self.__handle_deletion(u, v)
            self.__advance_update_counter()

    @contextmanager
    def __atomic_update(self) -> Iterator[None]:
        """Make one accepted graph update all-or-nothing.

        Dynamic repair touches the live graph, matching views, recursive
        hierarchy, auxiliary indexes, and accounting counters.  A failed
        coloring or invariant check must not leave those structures split
        across two states.  Graph objects are preserved by identity so a
        caller-supplied implementation remains the authoritative storage.
        """
        original_edges = set(self.graph.edges())
        graph_objects = [self.graph, self.phase_graph]
        if self.system is not None:
            graph_objects.append(self.system.graph)
        if self.multi is not None:
            graph_objects.append(self.multi.graph)
            graph_objects.extend(level.graph for level in self.multi.levels)
        memo = {id(graph): graph for graph in graph_objects if graph is not None}
        snapshot = {
            name: copy.deepcopy(value, memo)
            for name, value in self.__dict__.items()
            if name not in {"graph", "colorer", "policy"}
        }
        try:
            yield
        except BaseException:
            current_edges = set(self.graph.edges())
            for left, right in current_edges - original_edges:
                self.graph.remove_edge(left, right)
            for left, right in original_edges - current_edges:
                self.graph.add_edge(left, right)
            self.__dict__.update(snapshot)
            raise

    def __handle_insertion(self, u: Vertex, v: Vertex) -> None:
        if self.system is not None and self.__try_fast_insert(u, v):
            return

        # Inserting an edge cannot invalidate an already maximal matching.
        # Apply the paper's local inserted-edge transition instead of
        # rebuilding M* from the seed.
        if u not in self.matched_vertices and v not in self.matched_vertices:
            self.add_match(u, v)
        self.accountant.record_insertion()

    def __update_cached_lists(self, u: Vertex, v: Vertex, *, added: bool) -> None:
        """Update basic-mode Lambda/L lists for one live edge transition."""
        if self.system is None or self.multi is not None:
            return
        endpoints = ((u, v), (v, u))
        for source, target in endpoints:
            if source in self.system.U and target in self.system.B | self.system.U:
                values = self.system.lambda_lists.setdefault(source, [])
                if added and target not in values:
                    values.append(target)
                    values.sort()
                elif not added and target in values:
                    values.remove(target)
            if source in self.system.A and target in self.system.U:
                values = self.system.L_lists.setdefault(source, [])
                if added and target not in values:
                    values.append(target)
                    values.sort()
                elif not added and target in values:
                    values.remove(target)

    def __try_fast_insert(self, u: Vertex, v: Vertex) -> bool:
        """Attempt the (A, U) fast path for inserting (u, v).

        Returns ``True`` if the fast path was taken and the matcher state
        was updated accordingly; ``False`` if the caller should fall back
        to a full refresh.
        """
        system = self.system
        assert system is not None
        in_a = (u in system.A, v in system.A)
        if in_a == (True, False):
            a, u_vert = u, v
        elif in_a == (False, True):
            a, u_vert = v, u
        else:
            return False
        if u_vert not in system.U:
            return False
        if u_vert not in self.matched_vertices or a in self.matched_vertices:
            return False
        partner_of_u = self.partner(u_vert)
        if partner_of_u is None:
            return False
        self.drop_match(u_vert, partner_of_u)
        self.add_match(a, u_vert)
        # Moving the match from U to the newly inserted A-U edge exposes the
        # former partner.  It must be processed immediately; otherwise an
        # unrelated edge incident to that partner can remain uncovered and
        # maximality is lost after the update.
        self.__rematch_vertex(partner_of_u)
        self.accountant.record_insertion()
        return True

    def __handle_deletion(self, u: Vertex, v: Vertex) -> None:
        if canonical(u, v) in self.matched_edges:
            self.drop_match(u, v)

        self.__cleanup_stale_edges()
        self.__rebuild_auxiliary()
        self.__rematch_vertex(u)
        self.__rematch_vertex(v)
        self.__cleanup_stale_edges()

        if not self.maximal():
            raise RuntimeError(
                "deletion repair violated maximality; refusing a heuristic "
                "greedy rebuild"
            )

        self.accountant.record_deletion()

    def __validate_vertex(self, vertex: Vertex) -> None:
        if not isinstance(vertex, int) or isinstance(vertex, bool):
            raise ValueError(
                f"vertex must be an integer in [0, {self.n}), got {vertex!r}"
            )
        if not 0 <= vertex < self.n:
            raise ValueError(f"vertex must be in [0, {self.n}), got {vertex}")

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
            raise RuntimeError(
                "cannot rematch a vertex without an active z-system; "
                "the rebuild invariant is corrupted"
            )

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
        # H is directed from an unmatched U source to its Lambda targets.
        # ProcRematchBU(u) therefore consumes incoming H edges for both U and
        # B vertices; scanning H[u] would inspect the wrong endpoint.
        for source in sorted(self.H_reverse.get(u, set())):
            if source not in self.matched_vertices and self.graph.has_edge(source, u):
                self.add_match(source, u)
                self.accountant.record_rematch_u_scan()
                return

        scanned = 0
        for w in sorted(self.S_hat):
            if w not in self.matched_vertices:
                if self.graph.has_edge(u, w):
                    self.add_match(u, w)
                    self.accountant.record_rematch_u_scan(scanned + 1)
                    return
            scanned += 1

        # Good vertices must inspect their incident inserted edges directly;
        # only bad vertices receive the bounded incoming-edge index in
        # ``H_tilde`` (ProcRematchBU, step 3 of the paper).
        if u not in self.bad_vertices:
            for left, right in sorted(self.inserted_edges):
                other = right if left == u else left if right == u else None
                if other is not None and other not in self.matched_vertices:
                    self.add_match(u, other)
                    self.accountant.record_rematch_u_scan(scanned + 1)
                    return
        # Bad vertices receive the bounded incoming-edge index in H_tilde
        # (ProcRematchBU, step 4); it is intentionally consulted last.
        for source, target in sorted(self.H_tilde):
            if (
                target == u
                and source not in self.matched_vertices
                and self.graph.has_edge(source, u)
            ):
                self.add_match(source, u)
                self.accountant.record_rematch_u_scan()
                return
        self.accountant.record_rematch_u_scan(scanned)

    def __rematch_b(self, b: Vertex) -> None:
        assert self.system is not None
        scanned = 0
        for u in sorted(self.H_reverse.get(b, set())):
            if u not in self.matched_vertices and self.graph.has_edge(u, b):
                self.add_match(u, b)
                self.accountant.record_rematch_b_scan(scanned + 1)
                return
            scanned += 1
        self.accountant.record_rematch_b_scan(scanned)

        for w in sorted(self.S_hat):
            if w not in self.matched_vertices:
                if self.graph.has_edge(b, w):
                    self.add_match(b, w)
                    return

        if b not in self.bad_vertices:
            for left, right in sorted(self.inserted_edges):
                other = right if left == b else left if right == b else None
                if other is not None and other not in self.matched_vertices:
                    self.add_match(b, other)
                    return
        else:
            for left, right in sorted(self.H_tilde):
                if right == b and left not in self.matched_vertices:
                    self.add_match(b, left)
                    return

    def __rematch_a(self, a: Vertex) -> None:
        assert self.system is not None
        level = self.__a_level(a)
        if level is not None:
            self.__rematch_a_level(level, a)
            return

        # Basic mode has one A-region and no higher-level recursion.
        self.__rematch_a_level(None, a)

    def __a_level(self, a: Vertex) -> int | None:
        """Return the recursive A-level containing ``a``."""
        if self.multi is None:
            return None
        for index, vertices in enumerate(self.multi.A_levels):
            if a in vertices:
                return index
        return None

    def __rematch_a_level(self, level: int | None, a: Vertex) -> None:
        """Run ProcRematchA for one level, including upward recursion."""
        assert self.system is not None
        system = self.system
        # ProcRematchA may inspect one candidate beyond the I3 allowance.
        # Keep this bound consistent with Hierarchy.check_i3, which uses
        # floor(2*tau) rather than 2*floor(tau).
        limit = (64 * self.phase_length) // self.z + 1 if self.z > 0 else 1
        scanned = 0

        if level is None:
            candidates = system.L_lists.get(a, [])
            allowed_region = None
            allowed_a = set(system.A)
        else:
            assert self.multi is not None
            candidates = self.multi.L_levels[level].get(a, [])
            allowed_region = self.multi.R_levels[level]
            allowed_a = set().union(*self.multi.A_levels[: level + 1])

        for u in candidates:
            if allowed_region is not None and u not in allowed_region:
                continue
            scanned += 1
            if scanned > limit:
                break
            if not self.graph.has_edge(a, u):
                continue
            if u not in self.matched_vertices:
                self.add_match(a, u)
                self.accountant.record_rematch_a_scan(scanned)
                return
            p = self.partner(u)
            if p is not None and p in allowed_a:
                continue
            if p is not None:
                self.drop_match(u, p)
            self.add_match(a, u)
            if p is not None:
                self.__rebuild_auxiliary()
                higher = self.__a_level(p)
                if higher is not None and (level is None or higher > level):
                    self.__rematch_a_level(higher, p)
                else:
                    self.__rematch_vertex(p)
            self.accountant.record_rematch_a_scan(scanned)
            return

        self.accountant.record_rematch_a_scan(scanned)

        # ProcRematchA scans the maintained S_hat set, not the whole graph.
        for w in sorted(self.S_hat):
            if w not in self.matched_vertices and self.graph.has_edge(a, w):
                self.add_match(a, w)
                return

        if a not in self.bad_vertices:
            for left, right in sorted(self.inserted_edges):
                other = right if left == a else left if right == a else None
                if other is not None and other not in self.matched_vertices:
                    self.add_match(a, other)
                    return
        else:
            for left, right in sorted(self.H_tilde):
                if right == a and left not in self.matched_vertices:
                    self.add_match(a, left)
                    return

    def __maintain_i3(self) -> int:
        """Repair any violation of invariant (I3) in multilevel mode.

        Call :meth:`Hierarchy.maintain_i3` on the active multi-level
        system.  In basic mode, there is no I3 invariant and this is a
        no-op.

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
            self.drop_match,
        )

    def __advance_update_counter(self) -> None:
        self.update_count += 1
        self.__check_subphase_boundary()
        self.__maintain_i3()
        # Matching transitions can expose vertices indirectly through a
        # recursive fan/I3 repair.  Rebuild the bounded auxiliary views from
        # the authoritative matching and current lambda lists before checking
        # invariants, so no stale H/H_reverse/H_tilde entry survives a repair.
        self.__rebuild_auxiliary()

        # I3 repair may reroute a matching edge recursively.  The final
        # settledness condition is authoritative; an exposed edge endpoint
        # is an invariant failure, never a reason to switch algorithms.
        if not self.maximal():
            raise RuntimeError(
                "update repair violated maximality; refusing a heuristic "
                "refresh fallback"
            )

        if self.multi is not None:
            if not self.multi.check():
                raise RuntimeError(
                    "multilevel hierarchy invariant violated after update; "
                    "refusing to continue with stale recursive state"
                )
            if not self.multi.check_i3(self.matched_edges, self.phase_length, self.z):
                raise RuntimeError(
                    "multilevel invariant I3 violated after update; refusing to "
                    "continue with stale recursive state"
                )
            expected_phase_edges = set(self.graph.edges()) - set(
                self.inserted_edges
            ) | set(self.multi.deferred_deletions)
            actual_phase_edges = set(self.multi.graph.edges())
            if actual_phase_edges != expected_phase_edges:
                raise RuntimeError(
                    "multilevel phase graph diverged from live graph: "
                    f"missing={sorted(expected_phase_edges - actual_phase_edges)}, "
                    f"unexpected={sorted(actual_phase_edges - expected_phase_edges)}"
                )
            if any(level.graph is not self.multi.graph for level in self.multi.levels):
                raise RuntimeError(
                    "multilevel levels do not share the authoritative phase graph"
                )

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
        return is_maximal_matching(self.graph, self.matched_edges)

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
