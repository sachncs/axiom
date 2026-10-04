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

import math
from array import array
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import get_ident
from typing import TypedDict
from weakref import WeakKeyDictionary

from axiom.augment import augment as augment
from axiom.auxiliary import Auxiliary
from axiom.classes import Classes
from axiom.clocks import Clocks
from axiom.color import Vizing
from axiom.graph import Adjacency, empty
from axiom.hierarchies import Hierarchies
from axiom.hierarchy import Hierarchy
from axiom.ledger import Ledger
from axiom.matching import partners
from axiom.matching_index import MatchingIndex
from axiom.paper_coloring import Paper
from axiom.partners import Partners
from axiom.rebuild import Basic, Multilevel
from axiom.storage import Packed, publish
from axiom.system import System
from axiom.systems import Systems
from axiom.types import (
    Colorer,
    Edge,
    Graph,
    Matching,
    Vertex,
    canonical,
)
from axiom.vertices import Vertices
from axiom.views import Views


class BatchState(TypedDict):
    """Bounded ephemeral coordination data for one open Matcher batch."""

    entered: bool
    failed: bool
    thread: int
    count: int
    limit: int
    before_publish: Callable[[], None] | None


batch_states: WeakKeyDictionary[Matcher, BatchState] = WeakKeyDictionary()


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
        graph: Optional graph implementation (defaults to bounded ``Packed``).
        colorer: Optional edge colorer.  The default is ``Vizing`` for
            ``basic`` and the paper fan colorer for ``multilevel``.
        budget: Native storage budget when ``graph`` is omitted.

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
        budget: int = 1 << 30,
    ) -> None:
        """Initialize the selected matching mode and its graph and rebuild state."""
        if not isinstance(n, int) or isinstance(n, bool):
            raise ValueError(f"n must be an integer, got {n!r}")
        if n < 0:
            raise ValueError(f"n must be non-negative, got {n}")
        if not isinstance(mode, str) or mode not in {"basic", "multilevel"}:
            raise ValueError(f"mode must be 'basic' or 'multilevel', got {mode}")
        if colorer is not None and not callable(getattr(colorer, "color", None)):
            raise ValueError(
                "colorer must provide a callable color(graph, delta) method"
            )
        if (
            mode == "multilevel"
            and colorer is not None
            and not isinstance(colorer, Paper)
        ):
            raise ValueError(
                "multilevel requires the deterministic Paper; "
                "custom colorers are supported only in basic mode"
            )
        self.n = n
        self.failed = False
        self.mode = mode
        self.graph = graph if graph is not None else Packed(n, budget=budget)
        self.__validate_graph(self.graph, n)
        self.colorer = (
            colorer
            if colorer is not None
            else Paper()
            if mode == "multilevel"
            else Vizing()
        )
        matching_budget = (
            self.graph.memory()["budget"] if isinstance(self.graph, Packed) else budget
        )
        self.matched_edges: Matching = MatchingIndex(n, budget=matching_budget)
        self.matched_vertices = Vertices(n)
        self.partner_map = Partners(n)
        self.views: Views | None = None
        self.classes: Classes | None = None
        self.systems: Systems | None = None
        self.hierarchies: Hierarchies | None = None
        self.auxiliary: Auxiliary | None = None
        self.clocks: Clocks | None = None

        self.z: int = 0
        self.phase_length: int = 0
        self.subphase_length: int = 0
        self.update_count: int = 0
        self.subphase_count: int = 0
        self.system: System | None = None
        self.matchings: list[Matching] = []
        self.seed_matching: Matching = set()
        self.activecolors: set[int] = set()

        self.multi: Hierarchy | None = None
        # Active A1-to-R1 matching edges are indexed as matching edits occur;
        # phase rebuilds recertify and replace this bounded view.
        self.i3_crossings: set[tuple[int, int]] = set()
        self.phase_graph: Graph | None = None
        self.phase_base_graph: Graph | None = None
        self.phase_base_system: System | None = None
        self.level_zs: list[int] = []
        self.level_phase_lengths: list[int] = []
        # Nested phase clocks are independent of ``update_count``.  The
        # latter is the finest-level rebuild budget and is reset at every
        # finest rebuild; these clocks retain parent-level progress across
        # those rebuilds.
        self.level_phase_updates: list[int] = []
        self.level_phase_indices: list[int] = []
        self.eta: int = 0
        self.k: int = 0
        self.inserted_edges: set[tuple[int, int]] = set()
        # E_I is typically a small parent-phase overlay. Allocate buckets only
        # for its live endpoints, never an empty Python set for every vertex.
        self.inserted_incident_edges: dict[Vertex, set[tuple[int, int]]] = {}
        self.deleted_edges: set[tuple[int, int]] = set()
        self.inserted_incident_counts: dict[Vertex, int] = {}
        self.bad_vertices: set[Vertex] = set()
        self.H: dict[Vertex, set[Vertex]] = {}
        self.H_reverse: dict[Vertex, set[Vertex]] = {}
        self.H_tilde: set[tuple[Vertex, Vertex]] = set()
        self.Htildeoutgoing: dict[Vertex, set[Vertex]] = {}
        self.H_tilde_reverse: dict[Vertex, set[Vertex]] = {}
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

        if isinstance(graph, Packed):
            # Packed is the fixed-contract, audited native graph backend. Its
            # certificate checks row links, degrees, blocks, counts and index
            # invariants without retaining an O(m) Python edge list plus two
            # duplicate edge sets. Keep the exhaustive protocol cross-check
            # below for caller-defined Graph implementations.
            if not graph.check():
                raise ValueError("packed graph failed its native integrity check")
            return

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
        """Color the active system matching and select its first color class."""
        self.ready()
        if self.system is None:
            if self.classes is not None:
                self.classes.rootchange()
            self.seed_matching = set()
            self.matchings = []
            self.activecolors = set()
            return

        if self.system.M or type(self.colorer) not in (Vizing, Paper):
            sub = empty(self.graph)
            for e in self.system.M:
                sub.add_edge(e[0], e[1])
            coloring = self.colorer.color(sub, self.z)
        elif "color" in vars(self.colorer):
            # Preserve instance-level instrumentation/overrides even for a
            # built-in colorer while keeping its ordinary empty case sparse.
            sub = empty(self.graph)
            coloring = self.colorer.color(sub, self.z)
        else:
            # The empty edge set has exactly one complete proper coloring: the
            # empty map. Avoid an O(n) native graph allocation for this common
            # sparse-system case, especially during million-vertex startup.
            coloring = {}

        coloring_edges = coloring.keys()
        if coloring_edges != self.system.M:
            missing = self.system.M - coloring_edges
            extra = coloring_edges - self.system.M
            raise RuntimeError(
                "edge colorer returned an incomplete coloring: "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )

        if self.classes is not None:
            self.classes.rootchange()
        self.matchings = [set() for _ in range(self.z + 1)]
        activecolors: set[int] = set()
        incident_colors: dict[Vertex, set[int]] = {}
        dropped = 0
        for e, c in coloring.items():
            if 0 <= c <= self.z:
                u, v = e
                left_colors = incident_colors.setdefault(u, set())
                right_colors = incident_colors.setdefault(v, set())
                if c in left_colors or c in right_colors:
                    raise RuntimeError(
                        "edge colorer returned a non-proper coloring: "
                        f"color {c} conflicts on edge {e}"
                    )
                left_colors.add(c)
                right_colors.add(c)
                self.matchings[c].add(e)
                activecolors.add(c)
            else:
                dropped += 1
        if dropped:
            raise RuntimeError(
                f"partition_m_into_matchings: {dropped} edge(s) received "
                f"out-of-range color (expected 0..{self.z})."
            )

        self.seed_matching = self.matchings[0] if self.matchings else set()
        self.activecolors = activecolors

    def __rebuild_auxiliary(self) -> None:
        """Rebuild the directed H and H-tilde indexes from live state."""
        self.H = {}
        self.H_reverse = {}
        self.H_tilde = set()
        self.Htildeoutgoing = {}
        self.H_tilde_reverse = {}
        self.S_hat = set()
        if self.system is None:
            return

        self.S_hat = {
            vertex
            for vertex in self.system.saturated()
            if vertex not in self.matched_vertices
        }

        # Integer-set iteration is deterministic for a fixed partition, and
        # compact Vertices already owns its member array. Avoid a graph-sized
        # sorted copy while rebuilding these local directed indexes.
        for u in self.system.U:
            if u in self.matched_vertices:
                continue
            neighbours = None
            for v in self.system.lambda_lists.get(u, []):
                if self.graph.has_edge(u, v):
                    if neighbours is None:
                        neighbours = set()
                    neighbours.add(v)
            if neighbours:
                self.H[u] = neighbours
                for v in neighbours:
                    self.H_reverse.setdefault(v, set()).add(u)

        for left, right in self.inserted_edges:
            if left not in self.matched_vertices and right in self.bad_vertices:
                self.__add_h_tilde((left, right))
            if right not in self.matched_vertices and left in self.bad_vertices:
                self.__add_h_tilde((right, left))

    def __proc_update(self, vertex: Vertex) -> None:
        """Apply the paper's ProcUpdate transition for one vertex."""
        if self.system is None:
            return
        matched = vertex in self.matched_vertices
        if matched:
            if self.auxiliary is None:
                self.S_hat.discard(vertex)
            else:
                self.auxiliary.member(self.S_hat, vertex, False)
            if vertex in self.system.U:
                self.__remove_h_source(vertex)
        else:
            if vertex in self.system.A or vertex in self.system.B:
                if self.auxiliary is None:
                    self.S_hat.add(vertex)
                else:
                    self.auxiliary.member(self.S_hat, vertex, True)
            if vertex in self.system.U:
                # ProcUpdate replaces the source's outgoing H edges.  Remove
                # the old reverse-index entries first; otherwise a changed
                # Lambda list leaves phantom incoming H edges until the next
                # full auxiliary rebuild.
                self.__remove_h_source(vertex)
                targets = {
                    target
                    for target in self.system.lambda_lists.get(vertex, [])
                    if self.graph.has_edge(vertex, target)
                }
                if targets:
                    if self.auxiliary is None:
                        self.H[vertex] = targets
                    else:
                        self.auxiliary.assign(self.H, vertex, targets)
                for target in targets:
                    if self.auxiliary is None:
                        self.H_reverse.setdefault(target, set()).add(vertex)
                    else:
                        self.auxiliary.add(self.H_reverse, target, vertex)

        # ProcUpdate removes only edges leaving a status-changing vertex.
        # Incoming edges to a bad target remain valid: their sources may
        # still be unmatched and must remain discoverable by ProcRematchBU.
        self.__remove_h_tilde_source(vertex)
        if not matched:
            for left, right in self.__inserted_edges_at(vertex):
                if left == vertex and right in self.bad_vertices:
                    self.__add_h_tilde((left, right))
                elif right == vertex and left in self.bad_vertices:
                    self.__add_h_tilde((right, left))

    def __remove_h_source(self, source: Vertex) -> None:
        """Remove one source and all of its reverse-H index entries."""
        if self.auxiliary is None:
            targets = self.H.pop(source, set())
        else:
            targets = self.H.get(source, set())
            self.auxiliary.remove(self.H, source)
        for target in targets:
            incoming = self.H_reverse.get(target)
            if incoming is not None:
                if self.auxiliary is None:
                    incoming.discard(source)
                    if not incoming:
                        self.H_reverse.pop(target, None)
                else:
                    self.auxiliary.discard(self.H_reverse, target, source, empty=True)

    def __add_h_tilde(self, edge: tuple[Vertex, Vertex]) -> None:
        """Insert one ``H_tilde`` edge and both endpoint indexes."""
        source, target = edge
        if edge in self.H_tilde:
            return
        if self.auxiliary is None:
            self.H_tilde.add(edge)
            self.Htildeoutgoing.setdefault(source, set()).add(target)
            self.H_tilde_reverse.setdefault(target, set()).add(source)
        else:
            self.auxiliary.member(self.H_tilde, edge, True)
            self.auxiliary.add(self.Htildeoutgoing, source, target)
            self.auxiliary.add(self.H_tilde_reverse, target, source)

    def __remove_h_tilde_source(self, source: Vertex) -> None:
        """Remove all outgoing ``H_tilde`` edges for one source."""
        outgoing = self.Htildeoutgoing.get(source, set())
        for target in sorted(outgoing):
            edge = source, target
            if self.auxiliary is None:
                self.H_tilde.remove(edge)
                outgoing.remove(target)
                if not outgoing:
                    self.Htildeoutgoing.pop(source, None)
            else:
                self.auxiliary.member(self.H_tilde, edge, False)
                self.auxiliary.discard(self.Htildeoutgoing, source, target, empty=True)
            incoming = self.H_tilde_reverse.get(target)
            if incoming is not None:
                if self.auxiliary is None:
                    incoming.discard(source)
                    if not incoming:
                        self.H_tilde_reverse.pop(target, None)
                else:
                    self.auxiliary.discard(
                        self.H_tilde_reverse, target, source, empty=True
                    )

    def __add_inserted_edge(self, edge: tuple[Vertex, Vertex]) -> None:
        """Add an ``E_I`` edge to the incident index used by rematching."""
        if self.auxiliary is None:
            self.inserted_edges.add(edge)
        else:
            self.auxiliary.member(self.inserted_edges, edge, True)
        left, right = edge
        if self.auxiliary is None:
            self.inserted_incident_edges.setdefault(left, set()).add(edge)
            self.inserted_incident_edges.setdefault(right, set()).add(edge)
        else:
            self.auxiliary.add(self.inserted_incident_edges, left, edge)
            self.auxiliary.add(self.inserted_incident_edges, right, edge)

    def __remove_inserted_edge(self, edge: tuple[Vertex, Vertex]) -> None:
        """Remove an ``E_I`` edge from its two incident index buckets."""
        if self.auxiliary is None:
            self.inserted_edges.discard(edge)
        else:
            self.auxiliary.member(self.inserted_edges, edge, False)
        left, right = edge
        for vertex in (left, right):
            if self.auxiliary is None:
                values = self.inserted_incident_edges[vertex]
                values.discard(edge)
                if not values:
                    del self.inserted_incident_edges[vertex]
            else:
                self.auxiliary.discard(
                    self.inserted_incident_edges, vertex, edge, empty=True
                )

    def __inserted_edges_at(self, vertex: Vertex) -> list[tuple[Vertex, Vertex]]:
        """Return incident inserted edges in deterministic order."""
        return sorted(self.inserted_incident_edges.get(vertex, ()))

    def __check_auxiliary_indexes(self) -> bool:
        """Validate H, reverse-H, H-tilde, and S-hat against live state."""
        return Auxiliary.complete(self)

    def __check_matching_state(self) -> bool:
        """Validate the matching, vertex cache, and partner map together."""
        edge_count = len(self.matched_edges)
        if (
            not isinstance(self.matched_vertices, (set, Vertices))
            or isinstance(self.matched_vertices, Vertices)
            and not self.matched_vertices.check()
            or len(self.matched_vertices) != 2 * edge_count
            or len(self.partner_map) != 2 * edge_count
        ):
            return False
        for left, right in self.matched_edges:
            if (
                left >= right
                or not self.graph.has_edge(left, right)
                or left not in self.matched_vertices
                or right not in self.matched_vertices
                or self.partner_map.get(left) != right
                or self.partner_map.get(right) != left
            ):
                return False
        # Exact cardinalities plus both endpoint checks prove there are no
        # stray cache entries and no shared matching vertices. Avoid building
        # a second vertex set and partner dictionary proportional to |M|.
        return True

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
        self.ready()
        e = canonical(u, v)
        # Drop any prior matches of u and v so the new edge is the
        # only match incident to either endpoint.
        for endpoint in (u, v):
            prior = self.partner_map.get(endpoint)
            if prior is not None and prior not in (u, v):
                self.drop_match(endpoint, prior)
        if self.views is not None:
            self.views.record(u, v)
        self.matched_edges.add(e)
        self.matched_vertices.add(u)
        self.matched_vertices.add(v)
        self.partner_map[u] = v
        self.partner_map[v] = u
        self.update_i3_index(e, True)
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
        self.ready()
        e = canonical(u, v)
        if self.views is not None:
            self.views.record(u, v)
        self.matched_edges.discard(e)
        self.matched_vertices.discard(u)
        self.matched_vertices.discard(v)
        self.partner_map.pop(u, None)
        self.partner_map.pop(v, None)
        self.update_i3_index(e, False)
        if e in self.seed_matching:
            self.remove_seed_edge(e)
        self.__proc_update(u)
        self.__proc_update(v)

    def update_i3_index(self, edge: tuple[int, int], added: bool) -> None:
        """Keep the active hierarchy's A1/R1 matching-edge index current."""
        edge = canonical(*edge)
        hierarchy = self.multi
        included = added and hierarchy is not None and hierarchy.has_i3_crossing(edge)
        present = edge in self.i3_crossings
        if included == present:
            return
        if self.views is not None:
            self.views.crossing(edge, included)
        elif included:
            self.i3_crossings.add(edge)
        else:
            self.i3_crossings.discard(edge)

    def remove_seed_edge(self, edge: tuple[int, int]) -> None:
        """Remove a dropped matching edge from the seed class immediately."""
        if edge in self.seed_matching:
            if self.classes is None:
                self.seed_matching.discard(edge)
                if self.matchings and self.seed_matching is self.matchings[0]:
                    if not self.matchings[0]:
                        self.activecolors.discard(0)
            else:
                color = (
                    0
                    if self.matchings and self.seed_matching is self.matchings[0]
                    else None
                )
                self.classes.remove(self.seed_matching, edge, color)
        if self.matchings and edge in self.matchings[0]:
            if self.classes is None:
                self.matchings[0].discard(edge)
                if not self.matchings[0]:
                    self.activecolors.discard(0)
            else:
                self.classes.remove(self.matchings[0], edge, 0)

    def refresh(self) -> None:
        """Extend the seed to a maximal matching and rebuild its partner indexes."""
        self.ready()
        if self.system is None:
            raise RuntimeError(
                "cannot refresh matching without an active z-system; "
                "the rebuild invariant is corrupted"
            )

        matching_budget = (
            self.graph.memory()["budget"] if isinstance(self.graph, Packed) else 1 << 30
        )
        matching = self.matched_edges
        if (
            type(matching) is not MatchingIndex
            or len(matching)
            or self.update_count != 0
            or self.views is not None
        ):
            matching = MatchingIndex(self.n, budget=matching_budget)
        matched = self.matched_vertices
        if (
            not isinstance(matched, Vertices)
            or len(matched)
            or self.update_count != 0
            or self.views is not None
        ):
            matched = Vertices(self.n)
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
            for v in sorted(self.graph.neighbors(u)):
                if v not in matched:
                    matching.add(canonical(u, v))
                    matched.add(u)
                    matched.add(v)
                    break

        self.matched_edges = matching
        self.matched_vertices = matched
        result = self.partner_map
        if len(result) or self.update_count != 0 or self.views is not None:
            result = Partners(self.n)
        for u, v in self.matched_edges:
            result[u] = v
            result[v] = u
        self.partner_map = result
        self.__rebuild_auxiliary()
        if not self.__check_matching_state():
            raise RuntimeError("refresh produced inconsistent matching views")
        if not self.__check_auxiliary_indexes():
            raise RuntimeError("refresh produced inconsistent auxiliary indexes")
        if not self.maximal():
            raise RuntimeError("refresh produced a non-maximal matching")

    def __check_subphase_boundary(self) -> bool:
        if self.update_count > 0 and self.update_count % self.subphase_length == 0:
            self.subphase_count += 1
            self.__augment_seed_at_subphase_boundary()
            self.accountant.record_subphase_rebuild()
            return True
        return False

    def __augment_seed_at_subphase_boundary(self) -> None:
        if self.system is None or not self.matchings:
            return

        # M_1 is maintained across subphases, so remove adversarially deleted
        # edges before searching for augmenting paths.  The seed must remain a
        # matching contained in the live graph.
        stale_seed = any(
            not self.graph.has_edge(edge[0], edge[1]) for edge in self.seed_matching
        )
        if not stale_seed and not self.system.A and not self.system.B:
            # No stale seed edge remains and the augmentation search domain
            # A union B is empty. Its class, auxiliary indexes, and maximal
            # reported matching remain valid; avoid sorting all of U to rebuild
            # H and auditing all of V at this empty boundary.
            return
        self.seed_matching = {
            edge for edge in self.seed_matching if self.graph.has_edge(edge[0], edge[1])
        }
        self.__augment_seed()
        if self.classes is not None:
            self.classes.rootchange()
        self.matchings[0] = set(self.seed_matching)
        if self.classes is None:
            if self.seed_matching:
                self.activecolors.add(0)
            else:
                self.activecolors.discard(0)
        else:
            self.classes.color(0, bool(self.seed_matching))

        # Keep the paper's M_1 subset M* invariant explicit.  A newly added
        # seed edge may displace an older M* edge at either endpoint; those
        # displaced vertices are rematched after all seed edges are installed
        # so the transition is deterministic and does not recurse through a
        # partially updated seed.
        displaced: set[Vertex] = set()
        for left, right in sorted(self.seed_matching):
            edge = canonical(left, right)
            if edge in self.matched_edges:
                continue
            for endpoint in (left, right):
                prior = self.partner_map.get(endpoint)
                if prior is not None and canonical(endpoint, prior) != edge:
                    self.drop_match(endpoint, prior)
                    displaced.add(prior)
            self.add_match(left, right)

        self.__rebuild_auxiliary()
        protected = {vertex for edge in self.seed_matching for vertex in edge}
        for vertex in sorted(displaced):
            if vertex not in self.matched_vertices:
                # Rematch only against currently unmatched, non-seed
                # vertices.  The normal recursive dispatcher is allowed to
                # replace an existing partner, which could evict a seed edge
                # that was just installed.
                for neighbor in sorted(self.graph.neighbors(vertex)):
                    if (
                        neighbor not in protected
                        and neighbor not in self.matched_vertices
                    ):
                        self.add_match(vertex, neighbor)
                        break
        if not self.seed_matching <= self.matched_edges:
            raise RuntimeError(
                "subphase seed synchronization failed to preserve M1 subset M*"
            )
        if not self.maximal():
            raise RuntimeError("subphase seed synchronization violated maximality")

    def __augment_seed(self) -> int:
        r"""Run the subphase-boundary augmenting-path search over M_1.

        Walk every vertex of :math:`S = A \cup B` and, for each vertex
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
        for s in sorted(self.system.saturated()):
            if s not in matched_in_seed:
                if augment(
                    self.seed_matching,
                    lambda vertex: sorted(self.graph.neighbors(vertex)),
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
        self.__count_batch_operation()
        state = batch_states.get(self)
        try:
            self.__validate_vertex(u)
            self.__validate_vertex(v)
        except BaseException:
            if state is not None:
                state["failed"] = True
            raise
        try:
            existed = self.graph.has_edge(u, v)
        except BaseException:
            if state is not None:
                state["failed"] = True
            raise
        if u == v or existed:
            # Self-loops are outside the graph model and duplicate insertions
            # do not constitute graph updates.  Validate endpoints through
            # has_edge above, then leave all dynamic state untouched.
            return
        with self.__atomic_update():
            self.__edit(u, v, added=True)
            if self.mode == "multilevel":
                edge = canonical(u, v)
                was_deferred = (
                    self.multi is not None and edge in self.multi.deferred_deletions
                )
                restores_phase_edge = was_deferred or edge in self.deleted_edges
                if not restores_phase_edge:
                    self.__add_inserted_edge(edge)
                if self.auxiliary is None:
                    self.deleted_edges.discard(edge)
                else:
                    self.auxiliary.member(self.deleted_edges, edge, False)
                if self.multi is not None:
                    self.multi.undefer(edge)
                newly_bad: list[Vertex] = []
                if not was_deferred:
                    for vertex in edge:
                        count = self.inserted_incident_counts.get(vertex, 0) + 1
                        if self.auxiliary is None:
                            self.inserted_incident_counts[vertex] = count
                        else:
                            self.auxiliary.assign(
                                self.inserted_incident_counts, vertex, count
                            )
                        # The paper's insertion protocol marks a vertex bad
                        # when its incident E_I count reaches z.  ``self.z``
                        # is the active (finest) multilevel parameter; using
                        # sqrt(n) as a floor would delay promotion in dense
                        # type-2 schedules and make the tilde-H index stale.
                        insertion_budget = max(1, self.z)
                        if (
                            self.inserted_incident_counts[vertex] >= insertion_budget
                            and vertex not in self.bad_vertices
                        ):
                            if self.auxiliary is None:
                                self.bad_vertices.add(vertex)
                            else:
                                self.auxiliary.member(self.bad_vertices, vertex, True)
                            newly_bad.append(vertex)
                # A newly bad target must expose every already-live inserted
                # edge to it whose other endpoint is currently unmatched.
                # ProcUpdate only visits the two endpoints of this update;
                # without this backfill, older inserted edges would remain
                # invisible in H_tilde until a full phase rebuild.
                for bad in newly_bad:
                    for left, right in self.__inserted_edges_at(bad):
                        if right == bad and left not in self.matched_vertices:
                            self.__add_h_tilde((left, right))
                        if left == bad and right not in self.matched_vertices:
                            self.__add_h_tilde((right, left))
            if self.multi is not None:
                self.multi.sync_graph(
                    self.graph,
                    excluded_edges=self.inserted_edges,
                    changed_edge=edge,
                    journaled=True,
                )
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
        self.__count_batch_operation()
        state = batch_states.get(self)
        try:
            self.__validate_vertex(u)
            self.__validate_vertex(v)
        except BaseException:
            if state is not None:
                state["failed"] = True
            raise
        try:
            exists = self.graph.has_edge(u, v)
        except BaseException:
            if state is not None:
                state["failed"] = True
            raise
        if not exists:
            if state is not None and state["entered"]:
                try:
                    self.accountant.record_deletion()
                except BaseException:
                    state["failed"] = True
                    raise
                return
            accountant = self.accountant
            journal = accountant.begin()
            try:
                accountant.record_deletion()
                accountant.commit(journal)
            except BaseException:
                try:
                    accountant.rollback(journal)
                except BaseException as failure:
                    self.failed = True
                    raise RuntimeError(
                        "accounting rollback failed; discard matcher"
                    ) from failure
                raise
            return
        with self.__atomic_update():
            if self.mode == "multilevel":
                edge = canonical(u, v)
                if edge in self.inserted_edges:
                    self.__remove_inserted_edge(edge)
                    if self.multi is not None:
                        self.multi.undefer(edge)
                else:
                    if self.auxiliary is None:
                        self.deleted_edges.add(edge)
                    else:
                        self.auxiliary.member(self.deleted_edges, edge, True)
                    if self.multi is not None:
                        # Keep adversarially deleted phase edges in the
                        # decremental snapshot until the next recursive
                        # rebuild.  The live matching is repaired against
                        # the host graph immediately, while the z-system
                        # retains this edge to preserve its degree bound.
                        self.multi.defer(edge)
            # The paper removes an adversarially deleted edge from M_1
            # immediately.  Keeping it in the seed until the next subphase
            # would violate M_1 subset M* between boundaries.
            edge = canonical(u, v)
            if self.classes is None:
                raise RuntimeError("deletion requires class undo")
            seed_color = (
                0
                if self.matchings and self.seed_matching is self.matchings[0]
                else None
            )
            self.classes.remove(self.seed_matching, edge, seed_color)
            for color in sorted(self.activecolors):
                self.classes.remove(self.matchings[color], edge, color)
            self.__edit(u, v, added=False)
            if self.multi is not None:
                self.multi.sync_graph(
                    self.graph,
                    excluded_edges=self.inserted_edges,
                    changed_edge=edge,
                    journaled=True,
                )
            else:
                self.__update_cached_lists(u, v, added=False)
            self.__proc_update(u)
            self.__proc_update(v)
            self.__handle_deletion(u, v)
            self.__advance_update_counter()

    def __edit(self, u: Vertex, v: Vertex, *, added: bool) -> None:
        """Certify an edge mutation without scanning sealed native storage.

        Packed mutators reserve before editing precisely the two endpoint rows;
        differential/sanitizer tests establish that storage contract. Check its
        local membership, degrees, edge count, and logical version immediately.
        Opaque graph implementations retain the full edge-set certificate.
        """
        graph = self.graph
        mutate = graph.add_edge if added else graph.remove_edge
        if self.views is not None:
            self.views.affect(u)
            self.views.affect(v)
        if self.auxiliary is not None:
            self.auxiliary.affect(u, v)
        if isinstance(graph, Packed) or type(graph) is Adjacency:
            version = graph.version if isinstance(graph, Packed) else 0
            count = graph.num_edges()
            left, right = graph.degree(u), graph.degree(v)
            mutate(u, v)
            change = 1 if added else -1
            if (
                (isinstance(graph, Packed) and graph.version != version + 1)
                or graph.num_edges() != count + change
                or graph.degree(u) != left + change
                or graph.degree(v) != right + change
                or graph.has_edge(u, v) != added
                or graph.has_edge(v, u) != added
            ):
                raise RuntimeError("native edge mutation failed its local certificate")
            return
        before = set(graph.edges())
        mutate(u, v)
        after = set(graph.edges())
        edge = canonical(u, v)
        expected = before | {edge} if added else before - {edge}
        if after != expected:
            method = "add_edge" if added else "remove_edge"
            raise RuntimeError(
                f"graph.{method} changed an unexpected edge set: "
                f"missing={sorted(expected - after)}, "
                f"unexpected={sorted(after - expected)}"
            )

    @contextmanager
    def batch(
        self,
        max_operations: int = 256,
        before_publish: Callable[[], None] | None = None,
    ) -> Iterator[Matcher]:
        """Apply a bounded update group under one paper-state transaction.

        All successful calls to :meth:`insert` and :meth:`delete` inside the
        context share one set of first-write journals. Validation and graph
        publication happen once, when the context exits. Any failed operation
        poisons the batch even if its exception is caught by the caller.

        ``before_publish`` runs after paper invariants pass and before graph
        journals are published. Durable owners can persist their transaction
        there; if the callback fails, paper state is rolled back. A failure
        after the callback has durably committed is necessarily an uncertain
        cross-resource outcome and the matcher fails closed.

        Args:
            max_operations: Positive upper bound on attempted insert/delete
                calls, including no-ops. Hard capped at 4096.
            before_publish: Optional persistence hook called once on success.

        Raises:
            ValueError: If the bound or callback is invalid.
            MemoryError: If bounded component journal admission is exceeded.
            RuntimeError: If an update or validation fails, or a batch is nested.
        """
        if type(max_operations) is not int or not 1 <= max_operations <= 4096:
            raise ValueError("max_operations must be between 1 and 4096")
        if before_publish is not None and not callable(before_publish):
            raise TypeError("before_publish must be callable or None")
        if self.failed:
            raise RuntimeError("matcher has failed; discard it")
        state = batch_states.get(self)
        if state is not None:
            if state["thread"] != get_ident():
                raise RuntimeError("matcher batch belongs to another thread")
            raise RuntimeError("matcher batches cannot be nested")
        state = {
            "entered": False,
            "failed": False,
            "thread": get_ident(),
            "count": 0,
            "limit": max_operations,
            "before_publish": before_publish,
        }
        batch_states[self] = state
        try:
            with self.__atomic_update():
                state["entered"] = True
                yield self
                if state["failed"]:
                    raise RuntimeError("paper batch was aborted by a failed operation")
        finally:
            batch_states.pop(self, None)

    def __count_batch_operation(self) -> None:
        """Charge an attempted graph update against the active batch bound."""
        state = batch_states.get(self)
        if state is None:
            return
        if state["thread"] != get_ident():
            raise RuntimeError("matcher batch belongs to another thread")
        if state["failed"]:
            raise RuntimeError("paper batch is already aborted")
        if state["count"] >= state["limit"]:
            state["failed"] = True
            raise MemoryError("paper batch operation limit exceeded")
        state["count"] += 1

    @contextmanager
    def __atomic_update(self) -> Iterator[None]:
        """Roll back before publication; fail-stop on uncertain publication.

        Dynamic repair touches the live graph, matching views, recursive
        hierarchy, auxiliary indexes, and accounting counters.  A failed
        coloring or invariant check must not leave those structures split
        across two states.  Graph objects are preserved by identity so a
        caller-supplied implementation remains the authoritative storage.
        """
        state = batch_states.get(self)
        if state is not None and state["entered"]:
            try:
                yield
            except BaseException:
                state["failed"] = True
                raise
            return

        graph_objects = [self.graph, self.phase_graph, self.phase_base_graph]
        if self.phase_base_system is not None:
            graph_objects.append(self.phase_base_system.graph)
        if self.system is not None:
            graph_objects.append(self.system.graph)
        if self.multi is not None:
            graph_objects.append(self.multi.graph)
            graph_objects.extend(level.graph for level in self.multi.levels)
        managed = {id(graph): graph for graph in graph_objects if graph is not None}
        graph_snapshots: list[tuple[Graph, set[Edge]]] = []
        journals: list[tuple[Packed, int]] = []
        adjlogs: list[tuple[Adjacency, int]] = []
        accountant = self.accountant
        accounting = None
        views = None
        classes = None
        systems = None
        hierarchies = None
        auxiliary = None
        clocks = None
        snapshot = None
        published = False
        durable_callback_completed = False
        try:
            views = Views(self)
            classes = Classes(self)
            systems = Systems(self, audit=False)
            hierarchies = Hierarchies(self)
            auxiliary = Auxiliary(self)
            clocks = Clocks(self)
            for graph in managed.values():
                if isinstance(graph, Packed) or type(graph) is Adjacency:
                    token = graph.begin()
                    try:
                        if isinstance(graph, Packed):
                            journals.append((graph, token))
                        else:
                            adjlogs.append((graph, token))
                    except BaseException:
                        graph.rollback(token)
                        raise
                else:
                    graph_snapshots.append((graph, set(graph.edges())))
            accounting = accountant.begin()
            # All mutable roots are retained by their owner journals; the
            # root snapshot records assignments without traversing contents.
            snapshot = {
                name: value
                for name, value in self.__dict__.items()
                if name
                not in {
                    "graph",
                    "colorer",
                    "policy",
                    "views",
                    "classes",
                    "systems",
                    "hierarchies",
                    "auxiliary",
                    "clocks",
                }
            }
            yield
            if self.accountant is not accountant:
                raise RuntimeError("update replaced its accounting owner")
            if not views.certify_maximal():
                raise RuntimeError(
                    "update repair violated maximality at an affected endpoint"
                )
            accountant.validate(accounting)
            views.validate()
            classes.validate()
            systems.validate()
            hierarchies.validate()
            auxiliary.validate()
            clocks.validate()
            if state is not None and state["before_publish"] is not None:
                state["before_publish"]()
                durable_callback_completed = True
            publish(journals)
            published = True
            for graph, token in adjlogs:
                graph.commit(token)
            accountant.commit(accounting)
            views.commit()
            classes.commit()
            systems.commit()
            hierarchies.commit()
            auxiliary.commit()
            clocks.commit()
        except BaseException as error:
            if published:
                self.failed = True
                raise RuntimeError(
                    "publication cleanup failed; discard matcher"
                ) from error
            try:
                for native, token in reversed(journals):
                    native.rollback(token)
                for graph, token in reversed(adjlogs):
                    graph.rollback(token)
                if accounting is not None:
                    accountant.rollback(accounting)
                if systems is not None:
                    systems.rollback()
                if hierarchies is not None:
                    hierarchies.rollback()
                if auxiliary is not None:
                    auxiliary.rollback()
                if clocks is not None:
                    clocks.rollback()
                if classes is not None:
                    classes.rollback()
                if views is not None:
                    views.rollback()
                # Restore every graph object in place.  Multilevel rebuilds can
                # mutate a phase graph or an inherited level graph before a later
                # invariant check fails; restoring only ``self.graph`` would leave
                # those same-identity objects observably split from the snapshot.
                for graph, expected_edges in graph_snapshots:
                    current_edges = set(graph.edges())
                    for left, right in current_edges - expected_edges:
                        graph.remove_edge(left, right)
                    for left, right in expected_edges - current_edges:
                        graph.add_edge(left, right)
                    if set(graph.edges()) != expected_edges:
                        raise RuntimeError(
                            "atomic rollback could not restore a managed graph"
                        )
                if snapshot is not None:
                    self.__dict__.update(snapshot)
            except BaseException as failure:
                self.failed = True
                raise RuntimeError("rollback failed; discard matcher") from failure
            if durable_callback_completed:
                self.failed = True
                raise RuntimeError(
                    "durable callback completed but graph publication failed; "
                    "discard matcher"
                ) from error
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
        self.system.update(u, v, added)

    def __try_fast_insert(self, u: Vertex, v: Vertex) -> bool:
        """Attempt the (A, U) fast path for inserting (u, v).

        Returns ``True`` if the fast path was taken and the matcher state
        was updated accordingly; ``False`` if the insertion does not match
        this local transition and normal insertion handling should continue.
        """
        system = self.system
        if system is None:
            raise RuntimeError("fast insertion requires an active z-system")
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

        self.__rematch_vertex(u)
        self.__rematch_vertex(v)

        if self.views is None and not self.maximal():
            raise RuntimeError(
                "deletion repair violated maximality; refusing a heuristic "
                "greedy rebuild"
            )

        self.accountant.record_deletion()

    def __validate_vertex(self, vertex: Vertex) -> None:
        self.ready()
        if not isinstance(vertex, int) or isinstance(vertex, bool):
            raise ValueError(
                f"vertex must be an integer in [0, {self.n}), got {vertex!r}"
            )
        if not 0 <= vertex < self.n:
            raise ValueError(f"vertex must be in [0, {self.n}), got {vertex}")

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

        raise RuntimeError(
            "active z-system does not partition the vertex being rematched: "
            f"vertex={v}, missing from A/B/U"
        )

    def sathat(self, vertex: Vertex) -> tuple[Vertex | None, int]:
        """Return the lowest eligible S-hat neighbor and local probe count.

        The old fallback sorted and scanned all unmatched saturated vertices.
        A graph-neighbor traversal is equivalent because it selects the same
        lowest-numbered common member, while its work is bounded by the queried
        vertex's degree and creates no whole-S-hat snapshot.
        """
        candidate = None
        probed = 0
        for neighbor in self.graph.neighbors(vertex):
            probed += 1
            if (
                neighbor in self.S_hat
                and neighbor not in self.matched_vertices
                and (candidate is None or neighbor < candidate)
            ):
                candidate = neighbor
        return candidate, probed

    def __rematch_u(self, u: Vertex) -> None:
        if self.system is None:
            raise RuntimeError("U rematching requires an active z-system")
        # H is directed from an unmatched U source to its Lambda targets.
        # ProcRematchBU(u) therefore consumes incoming H edges for both U and
        # B vertices; scanning H[u] would inspect the wrong endpoint.
        for source in sorted(self.H_reverse.get(u, set())):
            if source not in self.matched_vertices and self.graph.has_edge(source, u):
                self.add_match(source, u)
                self.accountant.record_rematch_u_scan()
                return

        scanned = 0
        candidate, probed = self.sathat(u)
        if candidate is not None:
            self.add_match(u, candidate)
            self.accountant.record_rematch_u_scan(scanned + probed)
            return
        scanned += probed

        # Good vertices must inspect their incident inserted edges directly;
        # only bad vertices receive the bounded incoming-edge index in
        # ``H_tilde`` (ProcRematchBU, step 3 of the paper).
        if u not in self.bad_vertices:
            for left, right in self.__inserted_edges_at(u):
                other = right if left == u else left
                if other is not None and other not in self.matched_vertices:
                    self.add_match(u, other)
                    self.accountant.record_rematch_u_scan(scanned + 1)
                    return
        # Bad vertices receive the bounded incoming-edge index in H_tilde
        # (ProcRematchBU, step 4); it is intentionally consulted last.
        for source in sorted(self.H_tilde_reverse.get(u, set())):
            if source not in self.matched_vertices and self.graph.has_edge(source, u):
                self.add_match(source, u)
                self.accountant.record_rematch_u_scan()
                return
        self.accountant.record_rematch_u_scan(scanned)

    def __rematch_b(self, b: Vertex) -> None:
        if self.system is None:
            raise RuntimeError("B rematching requires an active z-system")
        scanned = 0
        for u in sorted(self.H_reverse.get(b, set())):
            if u not in self.matched_vertices and self.graph.has_edge(u, b):
                self.add_match(u, b)
                self.accountant.record_rematch_b_scan(scanned + 1)
                return
            scanned += 1
        self.accountant.record_rematch_b_scan(scanned)

        candidate, _ = self.sathat(b)
        if candidate is not None:
            self.add_match(b, candidate)
            return

        if b not in self.bad_vertices:
            for left, right in self.__inserted_edges_at(b):
                other = right if left == b else left
                if other is not None and other not in self.matched_vertices:
                    self.add_match(b, other)
                    return
        else:
            for source in sorted(self.H_tilde_reverse.get(b, set())):
                if source not in self.matched_vertices:
                    self.add_match(b, source)
                    return

    def __rematch_a(self, a: Vertex) -> None:
        if self.system is None:
            raise RuntimeError("A rematching requires an active z-system")
        level = self.__a_level(a)
        if level is not None:
            self.__rematch_a_level(level, a)
            return

        # Basic mode has one A-region and no higher-level recursion.
        self.__rematch_a_level(None, a)

    def __rematch_a_scan_limit(self) -> int:
        """Return the paper's bounded ``L(a)`` scan length.

        The bound is based on the phase's level-1 ``z`` parameter and the
        graph size, not on the finest-level rebuild interval.  Using the
        latter can make a recursive phase scan the entire inherited list and
        silently destroy the update-time bound.
        """
        if self.n <= 1:
            return 1
        phase_z = self.level_zs[0] if self.level_zs else self.z
        if phase_z <= 0:
            raise RuntimeError("cannot bound ProcRematchA without a positive z")
        log_n = max(1, math.ceil(math.log2(self.n)))
        return (18 * self.n * log_n * log_n) // phase_z + 1

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
        if self.system is None:
            raise RuntimeError("A-level rematching requires an active z-system")
        system = self.system
        # The paper permits only the first 18*n*log^2(n)/z + 1 entries.
        limit = self.__rematch_a_scan_limit()
        scanned = 0

        if level is None:
            candidates = system.L_lists.get(a, [])
            allowed_region = None
        else:
            if self.multi is None:
                raise RuntimeError(
                    "recursive A-level rematching requires an active hierarchy"
                )
            candidates = self.multi.L_levels[level].get(a, [])
            allowed_region = self.multi.R_levels[level]

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
            if p is not None:
                if level is None and p in system.A:
                    continue
                if (
                    level is not None
                    and self.multi is not None
                    and any(
                        p in self.multi.A_levels[index] for index in range(level + 1)
                    )
                ):
                    continue
            if p is not None:
                self.drop_match(u, p)
            self.add_match(a, u)
            if p is not None:
                higher = self.__a_level(p)
                if higher is not None and (level is None or higher > level):
                    self.__rematch_a_level(higher, p)
                else:
                    self.__rematch_vertex(p)
            self.accountant.record_rematch_a_scan(scanned)
            return

        self.accountant.record_rematch_a_scan(scanned)

        candidate, _ = self.sathat(a)
        if candidate is not None:
            self.add_match(a, candidate)
            return

        if a not in self.bad_vertices:
            for left, right in self.__inserted_edges_at(a):
                other = right if left == a else left
                if other is not None and other not in self.matched_vertices:
                    self.add_match(a, other)
                    return
        else:
            for source in sorted(self.H_tilde_reverse.get(a, set())):
                if source not in self.matched_vertices:
                    self.add_match(a, source)
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
            self.i3_crossings,
        )

    def __advance_update_counter(self) -> None:
        self.update_count += 1
        if self.mode == "multilevel":
            if not isinstance(self.policy, Multilevel):
                raise RuntimeError(
                    "multilevel matcher has a non-multilevel rebuild policy"
                )
            self.policy.advance_phase_clocks(self)
        self.__check_subphase_boundary()
        self.__maintain_i3()

        if self.multi is not None:
            if not self.multi.check_i3_count(
                len(self.i3_crossings), self.phase_length, self.z
            ):
                raise RuntimeError(
                    "multilevel invariant I3 violated after update; refusing to "
                    "continue with stale recursive state"
                )
            expected_phase_count = (
                self.graph.num_edges()
                - len(self.inserted_edges)
                + len(self.multi.deferred_deletions)
            )
            if (
                expected_phase_count < 0
                or self.multi.graph.num_edges() != expected_phase_count
            ):
                raise RuntimeError(
                    "multilevel phase graph edge count diverged from live graph"
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
        self.ready()
        return set(self.matched_edges)

    def maximal(self) -> bool:
        """Return True iff the current matching is maximal in the graph.

        Complexity:
        O(n + m).
        """
        self.ready()
        return self.__maximal_with_indexes()

    def __maximal_with_indexes(self) -> bool:
        """Check maximality using the already-maintained matched-vertex index."""
        for vertex in range(self.n):
            if vertex in self.matched_vertices:
                continue
            for neighbor in self.graph.neighbors(vertex):
                if neighbor not in self.matched_vertices:
                    return False
        return True

    def audit(self) -> bool:
        """Run a full audit of stable matching and paper-engine state.

        This is an explicit, state-sized diagnostic suitable for durable
        recovery, backup, and operator checks; it is not part of the update
        hot path. Color classes and the seed are retained phase structures,
        so this validates their live-edge/matching/index properties without
        requiring them to partition the current graph. In Basic mode the
        System's A/B/U partition and live Lambda/L caches are maintained
        between rebuilds, but its M edge set and degree/P1/P2 certificates
        are phase-owned: deleted phase edges and changing matching degrees
        make those stronger checks invalid until rebuild. Multilevel's
        Hierarchy.check() is specifically defined for its live, deferred-edge
        representation and validates the currently applicable hierarchy
        invariants. Finally, the full auxiliary certificate reconstructs the
        inserted-edge, H, reverse-H, H-tilde, and S-hat indexes. Vizing fans
        are operation-local colorer state, not retained Matcher roots; their
        compatibility is checked by the coloring operations that create/use
        them rather than by this stable-state audit.

        Returns:
            ``True`` iff the retained matching, coloring classes, and
            mode-specific phase state are internally consistent.
        """
        self.ready()
        if self.mode == "basic":
            if not isinstance(self.policy, Basic) or self.multi is not None:
                return False
            if self.system is None or self.system.graph is not self.graph:
                return False
            if not (
                self.system.check_partition()
                and self.system.check_lambda()
                and self.system.check_L()
            ):
                return False
        elif self.mode == "multilevel":
            if not isinstance(self.policy, Multilevel) or self.multi is None:
                return False
            hierarchy = self.multi
            if (
                hierarchy.graph is not self.phase_graph
                or self.system
                is not (hierarchy.levels[-1] if hierarchy.levels else None)
                or not hierarchy.check()
                or not hierarchy.check_i3(self.matched_edges, self.phase_length, self.z)
            ):
                return False
            expected_edges = (
                self.graph.num_edges()
                - len(self.inserted_edges)
                + len(hierarchy.deferred_deletions)
            )
            if expected_edges < 0 or hierarchy.graph.num_edges() != expected_edges:
                return False
        else:
            return False

        if not self.__check_auxiliary_indexes():
            return False

        if (
            type(self.matchings) is not list
            or type(self.seed_matching) is not set
            or type(self.activecolors) is not set
            or any(type(matching) is not set for matching in self.matchings)
        ):
            return False
        expected_colors = {
            color for color, matching in enumerate(self.matchings) if matching
        }
        if self.activecolors != expected_colors:
            return False
        expected_seed = self.matchings[0] if self.matchings else set()
        if (
            self.seed_matching != expected_seed
            or not self.seed_matching <= self.matched_edges
        ):
            return False

        seen = array("I", [0]) * self.n
        for index, matching in enumerate(self.matchings, 1):
            for edge in matching:
                if (
                    type(edge) is not tuple
                    or len(edge) != 2
                    or type(edge[0]) is not int
                    or type(edge[1]) is not int
                    or not 0 <= edge[0] < edge[1] < self.n
                    or not self.graph.has_edge(*edge)
                    or seen[edge[0]] == index
                    or seen[edge[1]] == index
                ):
                    return False
                seen[edge[0]] = index
                seen[edge[1]] = index

        if not self.__check_matching_state():
            return False
        return self.__maximal_with_indexes()

    def size(self) -> int:
        """Return the number of edges in the current matching."""
        self.ready()
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
        self.__validate_vertex(v)
        return self.partner_map.get(v)

    def partners(self) -> dict[Vertex, Vertex]:
        """Return a dict mapping each matched vertex to its partner.

        Returns:
            Dictionary of vertex to partner mappings.

        Complexity:
            O(|M*|) time and space.
        """
        self.ready()
        return partners(self.matched_edges)

    def stats(self) -> dict[str, int]:
        """Return a dictionary of runtime statistics.

        Returns:
            A flat dict suitable for logging or CSV export.
        """
        self.ready()
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

    def ready(self) -> None:
        """Refuse updates and queries after uncertain publication or rollback."""
        if self.failed:
            raise RuntimeError("matcher has failed; discard matcher")

    def __setattr__(self, name: str, value: object) -> None:
        """Reject replacement of active matching undo, using protocol spelling."""
        if (
            name
            in {"views", "classes", "systems", "hierarchies", "auxiliary", "clocks"}
            and getattr(self, name, None) is not None
        ):
            raise RuntimeError("active matching journal cannot be replaced")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        """Prevent deletion of the active matching transaction handle."""
        if (
            name
            in {"views", "classes", "systems", "hierarchies", "auxiliary", "clocks"}
            and getattr(self, name, None) is not None
        ):
            raise RuntimeError("active matching journal cannot be deleted")
        object.__delattr__(self, name)
