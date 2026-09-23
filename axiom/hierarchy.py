r"""The multi-level :math:`z`-subgraph system.

This module defines :class:`Hierarchy`, the :math:`k`-level generalisation
of the single-level :class:`axiom.system.System`.  It represents the
recursive structure used by the paper's multilevel algorithm; this module
does not claim the paper's exact asymptotic bound until the complete dynamic
maintenance pipeline is implemented.

Structure:
    The :class:`Hierarchy` owns ``k`` :class:`axiom.system.System`
    instances and the level-1 partition of :math:`A` into
    :math:`A_1, A_2` together with the derived sets
    :math:`N_1 \\subseteq A_2 \\cup B` and
    :math:`R_1 = V \\setminus (A_1 \\cup N_1)`.

Invariant I3 (paper, Section 6.2):
    At most :math:`2\\tau` vertices of :math:`A_1` are matched by
    :math:`M^*` into :math:`R_1`, where :math:`\\tau = 32 r / z`.
    This module implements :meth:`Hierarchy.check_i3` with the paper's
    :math:`2\\tau` constant and :meth:`Hierarchy.maintain_i3` that repairs
    any violation by re-routing :math:`A_1`-vertices out of :math:`R_1`.

References:
    Chuzhoy, Khanna, Song.  "A Faster Deterministic Algorithm for Fully
    Dynamic Maximal Matching" (arXiv:2605.00797v1), Section 6.2.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

from axiom.paper_coloring import PaperFanColorer
from axiom.system import System
from axiom.system import build as build_z_system
from axiom.types import Colorer, Edge, Graph, Vertex, canonical


@dataclass
class Hierarchy:
    r"""A :math:`k`-level subgraph system.

    Attributes:
        graph: The underlying dynamic graph.
        k: Number of levels.
        levels: A list of :class:`axiom.system.System` instances, one per level.
        A1: Partition of level-1 :math:`A` into :math:`A_1`.
        A2: Partition of level-1 :math:`A` into :math:`A_2`.
        N1: Subset :math:`N_1 \subseteq A_2 \cup B`.
        R1: :math:`R_1 = V \setminus (A_1 \cup N_1)`.

    Thread-safety:
        Not thread-safe.
    """

    graph: Graph
    k: int
    levels: list[System] = field(default_factory=list)
    A1: set[Vertex] = field(default_factory=set)
    A2: set[Vertex] = field(default_factory=set)
    N1: set[Vertex] = field(default_factory=set)
    R1: set[Vertex] = field(default_factory=set)
    A_levels: list[set[Vertex]] = field(default_factory=list)
    N_levels: list[set[Vertex]] = field(default_factory=list)
    R_levels: list[set[Vertex]] = field(default_factory=list)
    L_levels: list[dict[Vertex, list[Vertex]]] = field(default_factory=list)
    deferred_deletions: set[Edge] = field(default_factory=set)

    def sync_graph(
        self, graph: Graph, *, excluded_edges: set[Edge] | None = None
    ) -> None:
        """Synchronize the phase graph and its adjacency indexes.

        ``graph`` is the live graph, while ``excluded_edges`` contains
        inserted edges held in the paper's ``E_I``/``\tilde H`` structures.
        They are deliberately absent from the phase hierarchy until the next
        recursive rebuild.  This keeps the level invariants scoped to the
        decremental graph represented by the hierarchy.
        """
        if graph.n != self.graph.n:
            raise ValueError(
                "cannot synchronize a hierarchy with a graph of a different size"
            )
        from axiom.graph import Adjacency

        excluded = excluded_edges or set()
        phase_graph = Adjacency(graph.n)
        phase_edges = set(graph.edges()) | set(self.deferred_deletions)
        for left, right in phase_edges:
            if canonical(left, right) not in excluded:
                phase_graph.add_edge(left, right)
        self.graph = phase_graph
        for system in self.levels:
            system.graph = phase_graph
            system.index()
        self.L_levels = [
            _level_lists(phase_graph, vertices, self.R_levels[index])
            for index, vertices in enumerate(self.A_levels)
        ]

    def check(self) -> bool:
        """Validate the multi-level subgraph-system invariants."""
        if not self.levels or len(self.levels) != self.k:
            return False
        if not (
            len(self.A_levels)
            == len(self.N_levels)
            == len(self.R_levels)
            == len(self.L_levels)
            == self.k
        ):
            return False
        if (
            self.A1 != self.A_levels[0]
            or self.A2 != set().union(*self.A_levels[1:])
            or self.N1 != self.N_levels[0]
            or self.R1 != self.R_levels[0]
        ):
            return False
        vertices = set(range(self.graph.n))
        for index, level in enumerate(self.levels):
            if level.graph.n != self.graph.n:
                return False
            level_vertices = set(range(level.graph.n))
            if (
                level.A & set(level.B)
                or level.A & set(level.U)
                or set(level.B) & set(level.U)
                or level.A | set(level.B) | set(level.U) != level_vertices
            ):
                return False
            if (
                level.A != set().union(*self.A_levels[: index + 1])
                or set(level.B) != self.N_levels[index]
            ):
                return False
            # Intermediate levels are intentionally not required to satisfy
            # the finest-level lower degree bound after refinement, but their
            # inherited adjacency indexes must still describe their own
            # graph exactly.
            if not level.check_lambda() or not level.check_L():
                return False
        system = self.levels[-1]
        z = system.z
        all_a = set().union(*self.A_levels)
        if (
            all_a & set(system.B)
            or all_a & set(system.U)
            or set(system.B) & set(system.U)
        ):
            return False
        if all_a | set(system.B) | set(system.U) != vertices:
            return False
        for index, region in enumerate(self.R_levels):
            below = (
                set().union(*self.A_levels[index + 1 :]) | set(system.B) | set(system.U)
            )
            if region != below - self.N_levels[index]:
                return False
            if not self.N_levels[index] <= below - set(system.U):
                return False
        degree = {vertex: 0 for vertex in vertices}
        for u, v in system.M:
            if self.k > 1 and u in system.U and v in system.U:
                return False
            degree[u] += 1
            degree[v] += 1
        if any(value > z for value in degree.values()):
            return False
        if any(degree[v] < z - self.k + 1 for v in all_a | system.B):
            return False
        if any(
            sum(1 for neighbor in self.graph.neighbors(u) if neighbor in system.U) > z
            for u in system.U
        ):
            return False
        if any(
            sum(1 for neighbor in self.graph.neighbors(u) if neighbor in system.B)
            > 2 * z
            for u in system.U
        ):
            return False
        for index, a_vertices in enumerate(self.A_levels):
            lower = set().union(*self.A_levels[: index + 1])
            for vertex in a_vertices:
                for edge in system.M:
                    if vertex not in edge:
                        continue
                    other = edge[1] if edge[0] == vertex else edge[0]
                    if other not in lower | self.N_levels[index]:
                        return False
                expected = sorted(
                    neighbor
                    for neighbor in self.graph.neighbors(vertex)
                    if neighbor in self.R_levels[index]
                )
                if self.L_levels[index].get(vertex, []) != expected:
                    return False
        if self.R_levels[-1] != set(system.U):
            return False
        if not self.N1 <= self.A2 | set(self.levels[0].B):
            return False
        for left, right in self.levels[-1].M:
            if left in self.A1 and right not in self.A1 | self.N1:
                return False
            if right in self.A1 and left not in self.A1 | self.N1:
                return False
        if any(
            not self.R_levels[index + 1] <= self.R_levels[index]
            for index in range(self.k - 1)
        ):
            return False
        for vertex in system.U:
            expected = sorted(
                neighbor
                for neighbor in self.graph.neighbors(vertex)
                if neighbor in system.B | system.U
            )
            if system.lambda_lists.get(vertex, []) != expected:
                return False
        return True

    def check_i3(self, matching: set[tuple[int, int]], r: int, z: int) -> bool:
        """Check multi-level invariant (I3).

        At most :math:`2\\tau` vertices of :math:`A_1` are matched by
        :math:`M^*` into :math:`R_1`, where :math:`\\tau = 32 r / z`
        (Section 6.2 of the paper).  In other words, the count of
        edges of the matching that connect a vertex of :math:`A_1`
        to a vertex of :math:`R_1` is at most :math:`2\\tau = 64 r / z`.

        Args:
            matching: The maintained maximal matching M*.
            r: The phase length (set by the :class:`axiom.rebuild.Rebuild`
                policy at construction).
            z: The :math:`z` parameter of the active level-1 system.

        Returns:
            ``True`` iff the invariant holds.  The constant is the
            paper's :math:`2\\tau`; we treat it as ``64 r / z``
            (``\\tau = 32 r / z``).

        Complexity:
            :math:`O(|M^*|)`.
        """
        if z <= 0:
            return True
        # The paper's threshold is 2*tau with tau = 32*r/z.  Since the
        # number of crossing matching edges is integral, floor the final
        # threshold rather than flooring tau before multiplying by two.
        bound = (64 * r) // z
        count = 0
        for u, v in matching:
            if (u in self.A1 and v in self.R1) or (v in self.A1 and u in self.R1):
                count += 1
                if count > bound:
                    return False
        return True

    def maintain_i3(
        self,
        matching: set[tuple[int, int]],
        r: int,
        z: int,
        partner_of: Callable[[Vertex], Vertex | None],
        rematch: Callable[[Vertex], None],
        drop_match: Callable[[Vertex, Vertex], None] | None = None,
    ) -> int:
        """Repair any violation of invariant (I3).

        Iterates over vertices of :math:`A_1` that are currently matched
        by :math:`M^*` into :math:`R_1`, breaks the offending edge, and
        calls ``rematch`` to find a new partner for the A_1 endpoint.

        Args:
            matching: The maintained maximal matching M* (mutated in place).
            r: The phase length.
            z: The :math:`z` parameter of the active level-1 system.
            partner_of: Callable returning the partner of a vertex in M*.
            rematch: Callable to re-match an unmatched A_1 vertex.
            drop_match: Optional atomic matching-removal callback.  When
                supplied, it must remove the edge from the matching and all
                synchronized partner indexes; the direct set mutation is
                retained only for standalone hierarchy callers.

        Returns:
            The number of A_1 -> R_1 edges broken and rematched.
        """
        if z <= 0:
            return 0
        # Keep the repair threshold identical to check_i3: floor(2*tau),
        # not 2*floor(tau), which is stricter for non-integral tau.
        bound = (64 * r) // z
        offenders: list[tuple[int, int]] = []
        for u, v in sorted(matching):
            if (u in self.A1 and v in self.R1) or (v in self.A1 and u in self.R1):
                offenders.append((min(u, v), max(u, v)))
        # Keep at most ``bound`` crossing edges.  Slicing to ``bound`` would
        # remove the wrong number when the violation is larger than the
        # allowed budget and could leave I3 false after repair.
        offenders = offenders[max(0, bound) :]
        for u, v in offenders:
            if drop_match is None:
                matching.discard((min(u, v), max(u, v)))
            else:
                drop_match(u, v)
            rematch(u)
            rematch(v)
        return len(offenders)


def build_hierarchy(
    graph: Graph, level_zs: list[int], colorer: Colorer | None = None
) -> Hierarchy:
    r"""Build a multi-level system by recursive refinement.

    The first level is constructed by :func:`axiom.system.build`; every
    subsequent level is derived from its predecessor by
    :func:`refine_hierarchy`, retaining inherited partitions and lists.

    Each finer level is derived from the preceding level by selecting the
    first ``z_prime`` color classes, inheriting the prior regions and lists,
    and running the promotion pass that repairs the new U-degree and
    B-neighborhood bounds.

    Args:
        graph: The host graph.
        level_zs: Strictly decreasing positive integers giving the
            :math:`z` value of each level (finest first).

    Returns:
        A :class:`Hierarchy` whose ``levels`` list contains one
        entry per :math:`z` value.

    Complexity:
        Linear in the number of levels times the cost of
        :func:`axiom.system.build`.
    """
    if not level_zs:
        raise ValueError("level_zs must contain at least one positive value")
    if any(z <= 0 for z in level_zs):
        raise ValueError("all level z values must be positive")
    if any(left <= right for left, right in pairwise(level_zs)):
        raise ValueError("level_zs must be strictly decreasing")

    active_colorer = colorer if colorer is not None else PaperFanColorer()
    first = build_z_system(graph, level_zs[0])
    hierarchy = _from_basic(first)
    for z in level_zs[1:]:
        hierarchy = refine_hierarchy(hierarchy, z, colorer=active_colorer)
    return hierarchy


def _from_basic(system: System) -> Hierarchy:
    """Represent a basic system as the first level of a hierarchy."""
    hierarchy = Hierarchy(graph=system.graph, k=1, levels=[system])
    hierarchy.A_levels = [set(system.A)]
    hierarchy.N_levels = [set(system.B)]
    hierarchy.R_levels = [set(system.U)]
    hierarchy.L_levels = [dict(system.L_lists)]
    hierarchy.A1 = set(system.A)
    hierarchy.A2 = set()
    hierarchy.N1 = set(system.B)
    hierarchy.R1 = set(system.U)
    return hierarchy


def refine_hierarchy(
    hierarchy: Hierarchy,
    z_prime: int,
    *,
    deleted: set[Edge] | None = None,
    inserted: set[Edge] | None = None,
    colorer: Colorer | None = None,
) -> Hierarchy:
    """Recursively refine a hierarchy using the paper's level construction.

    The input graph is treated as the current graph with no deferred edge
    set.  The refinement keeps the previous levels and derives the next
    level by selecting the first ``z_prime`` color classes of the previous
    system, then applying the promotion pass that repairs the U-degree and
    B-neighborhood bounds.
    """
    previous = hierarchy.levels[-1]
    z = previous.z
    h = hierarchy.k
    if not 0 < z_prime < z:
        raise ValueError("z_prime must be positive and smaller than the prior z")

    deleted = deleted or set()
    inserted = inserted or set()
    # The hierarchy graph is the phase-start snapshot.  ED is supplied as a
    # separate set, so remove it from the live side before selecting the
    # bounded deferred subset ED'.
    live_edges = (set(hierarchy.graph.edges()) - deleted) | inserted
    retained_deleted = deleted & previous.M
    subgraph = _edge_graph(hierarchy.graph, previous.M)
    active_colorer = colorer if colorer is not None else PaperFanColorer()
    coloring = active_colorer.color(subgraph, z)
    if set(coloring) != set(previous.M):
        raise RuntimeError(
            "recursive refinement received an incomplete edge coloring: "
            f"missing={sorted(set(previous.M) - set(coloring))}"
        )
    incident_colors: dict[Vertex, set[int]] = {
        vertex: set() for vertex in range(hierarchy.graph.n)
    }
    for edge, color in coloring.items():
        if not isinstance(color, int) or isinstance(color, bool) or not 0 <= color <= z:
            raise RuntimeError(
                "recursive refinement received an invalid color: "
                f"edge={edge}, color={color!r}, expected an integer in 0..{z}"
            )
        u, v = edge
        if color in incident_colors[u] or color in incident_colors[v]:
            raise RuntimeError(
                "recursive refinement received a non-proper edge coloring: "
                f"color {color} conflicts on edge {edge}"
            )
        incident_colors[u].add(color)
        incident_colors[v].add(color)
    # Keep empty color classes in the candidate order.  The paper reindexes
    # color classes by nondecreasing deleted-edge count, then selects the
    # first z' classes.  This makes the retained deleted subset satisfy the
    # required |E_D'| <= |E_D| z'/z bound without dropping a selected edge.
    # Empty classes still participate in the first ``z_prime`` selection.
    classes: dict[int, set[Edge]] = {color: set() for color in range(z + 1)}
    for edge, color in coloring.items():
        classes[color].add(edge)
    ordered_colors = sorted(
        classes,
        key=lambda color: (len(classes[color] & retained_deleted), color),
    )
    selected_colors = set(ordered_colors[:z_prime])
    deletion_budget = len(retained_deleted) * z_prime // z
    deferred_candidates = sorted(
        edge
        for color in selected_colors
        for edge in classes[color]
        if edge in retained_deleted
    )
    if len(deferred_candidates) > deletion_budget:
        raise RuntimeError(
            "recursive refinement selected too many deleted matching edges: "
            f"selected={len(deferred_candidates)}, budget={deletion_budget}"
        )
    deferred_deleted = set(deferred_candidates)
    chosen = {
        edge
        for color in selected_colors
        for edge in classes[color]
        if edge in live_edges or edge in deferred_deleted
    }
    working_edges = (live_edges | deferred_deleted) - (deleted - deferred_deleted)
    working_graph = _edge_graph(hierarchy.graph, working_edges)
    degree = {vertex: 0 for vertex in range(hierarchy.graph.n)}
    for u, v in chosen:
        degree[u] += 1
        degree[v] += 1

    old_a = set(previous.A)
    old_b = set(previous.B)
    old_u = set(previous.U)
    levels = [set(level) for level in hierarchy.A_levels]
    # A one-level base system may contain U-U edges.  The multilevel
    # definition forbids those edges from level 2 onward, so discard
    # inherited U-U matching edges before the promotion pass; U vertices
    # have no lower matching-degree requirement.
    for edge in tuple(chosen):
        if edge[0] in old_u and edge[1] in old_u:
            chosen.remove(edge)
            degree[edge[0]] -= 1
            degree[edge[1]] -= 1
    old_s = old_a | old_b
    new_a: set[Vertex] = set()
    new_b: set[Vertex] = set()
    new_u = set(old_u)
    settled = set(old_s)
    for vertex in sorted(old_b):
        # Step 1 of the paper's construction keeps S and U fixed and
        # partitions the previous B according to the selected matching:
        # vertices whose selected M-neighbours all remain in S become the
        # new A_{h+1}; the rest remain in B.
        if all(neighbor in settled for neighbor in _partners(vertex, chosen)):
            new_a.add(vertex)
        else:
            new_b.add(vertex)

    def promote(vertex: Vertex) -> None:
        if vertex not in new_u:
            return
        new_u.remove(vertex)
        settled.add(vertex)
        if degree[vertex] >= z_prime - h and all(
            neighbor in settled for neighbor in _partners(vertex, chosen)
        ):
            new_a.add(vertex)
        else:
            new_b.add(vertex)

    for vertex in sorted(tuple(new_u)):
        if degree[vertex] >= z_prime - h:
            promote(vertex)

    changed = True
    while changed:
        changed = False
        for vertex in sorted(tuple(new_u)):
            need = z_prime - degree[vertex]
            if need <= 0:
                promote(vertex)
                changed = True
                continue

            # ProcProcess, first branch: fill the remaining degree using
            # edges to U.  Every selected neighbour must still have room at
            # the z' cap; otherwise the next level would violate P1.
            u_neighbors = [
                neighbor
                for neighbor in working_graph.neighbors(vertex)
                if (
                    neighbor in new_u
                    and degree[neighbor] < z_prime
                    and canonical(vertex, neighbor) not in chosen
                )
            ]
            if len(u_neighbors) >= need:
                for neighbor in u_neighbors[:need]:
                    chosen.add(canonical(vertex, neighbor))
                    degree[vertex] += 1
                    degree[neighbor] += 1
                promote(vertex)
                for neighbor in u_neighbors[:need]:
                    if neighbor in new_u and degree[neighbor] >= z_prime - h:
                        promote(neighbor)
                changed = True
                continue

            # ProcProcess, second branch: use B vertices only when there
            # are z' available B neighbours.  Each swap removes an existing
            # B-U edge (the paper's Z(v) witness) before inserting (u,v).
            b_candidates: list[tuple[Vertex, Edge]] = []
            for neighbor in working_graph.neighbors(vertex):
                edge = canonical(vertex, neighbor)
                if neighbor not in new_b or edge in chosen:
                    continue
                witnesses = sorted(
                    old_edge
                    for old_edge in chosen
                    if neighbor in old_edge
                    and degree[neighbor] > z_prime - h
                    and (old_edge[0] in new_u or old_edge[1] in new_u)
                )
                if witnesses:
                    b_candidates.append((neighbor, witnesses[0]))
            if len(b_candidates) >= z_prime:
                for neighbor, removed in b_candidates[:need]:
                    chosen.remove(removed)
                    for endpoint in removed:
                        degree[endpoint] -= 1
                    chosen.add(canonical(vertex, neighbor))
                    degree[vertex] += 1
                    degree[neighbor] += 1
                promote(vertex)
                changed = True

        # ProcProcess must also restore the lower matching-degree bound for
        # vertices inherited from the previous B region.  Selecting only the
        # first z' color classes can leave such a vertex short of
        # z'-h incident edges even though the input h-level system was valid.
        # Fill the deficit from deterministic available neighbors, preferring
        # U so the defining B-to-U witness is preserved.  Every inserted edge
        # respects the z' cap; if the theorem's input guarantees are violated,
        # fail explicitly rather than installing an invalid hierarchy.
        target = z_prime - h
        for vertex in sorted(new_a | new_b):
            need = target - degree[vertex]
            if need <= 0:
                continue
            candidates: list[tuple[Vertex, Edge | None]] = []
            for neighbor in sorted(working_graph.neighbors(vertex)):
                edge = canonical(vertex, neighbor)
                if edge in chosen:
                    continue
                if vertex in new_a and neighbor in new_u:
                    continue
                if neighbor in new_u and degree[neighbor] >= z_prime:
                    witnesses = sorted(
                        old_edge
                        for old_edge in chosen
                        if neighbor in old_edge
                        and (old_edge[0] in new_b or old_edge[1] in new_b)
                        and (old_edge[0] != vertex and old_edge[1] != vertex)
                        and degree[
                            old_edge[1] if old_edge[0] == neighbor else old_edge[0]
                        ]
                        > target
                    )
                    if witnesses:
                        candidates.append((neighbor, witnesses[0]))
                elif neighbor in new_u | new_b | new_a and degree[neighbor] < z_prime:
                    candidates.append((neighbor, None))
            candidates.sort(key=lambda item: (item[0] not in new_u, item[0]))
            if len(candidates) < need:
                raise RuntimeError(
                    "recursive refinement could not restore the S degree bound: "
                    f"vertex={vertex}, need={need}, available={len(candidates)}"
                )
            for neighbor, witness in candidates[:need]:
                if witness is not None:
                    chosen.remove(witness)
                    for endpoint in witness:
                        degree[endpoint] -= 1
                chosen.add(canonical(vertex, neighbor))
                degree[vertex] += 1
                degree[neighbor] += 1
                if neighbor in new_u and degree[neighbor] >= target:
                    promote(neighbor)
            changed = True

    # ProcPromote keeps every B vertex attached to U through M.  A vertex
    # promoted to A may not subsequently acquire a U partner; normalize this
    # boundary explicitly before applying the B-to-A promotion.
    for vertex in tuple(new_a):
        if any(
            vertex in edge and (edge[0] in new_u or edge[1] in new_u) for edge in chosen
        ):
            new_a.remove(vertex)
            new_b.add(vertex)

    for vertex in tuple(new_b):
        if degree[vertex] >= z_prime - h and not any(
            vertex in edge and (edge[0] in new_u or edge[1] in new_u) for edge in chosen
        ):
            new_b.remove(vertex)
            new_a.add(vertex)

    # All retained levels describe the same refined phase graph.  Preserve
    # their level-specific M/partition state, but refresh the graph reference
    # and derived adjacency indexes so inherited state cannot point at an old
    # phase snapshot.
    for level in hierarchy.levels:
        level.graph = working_graph
        level.index()

    new_system = System(
        graph=working_graph,
        z=z_prime,
        A=set().union(*levels, new_a),
        B=new_b,
        U=new_u,
        M=chosen,
    )
    new_system.index()

    all_a_levels = [*levels, new_a]
    all_n_levels = [*hierarchy.N_levels, new_b]
    all_b = set(new_b)
    all_u = set(new_u)
    all_r_levels = [
        (set().union(*all_a_levels[index + 1 :]) | all_b | all_u) - all_n_levels[index]
        for index in range(len(all_a_levels))
    ]
    inherited_lists = [
        _level_lists(working_graph, vertices, all_r_levels[index])
        for index, vertices in enumerate(all_a_levels)
    ]
    next_hierarchy = Hierarchy(
        graph=working_graph,
        k=hierarchy.k + 1,
        levels=[*hierarchy.levels, new_system],
        A_levels=all_a_levels,
        N_levels=all_n_levels,
        R_levels=all_r_levels,
        L_levels=inherited_lists,
        deferred_deletions=deferred_deleted,
    )
    next_hierarchy.A1 = set(next_hierarchy.A_levels[0])
    next_hierarchy.A2 = set().union(*next_hierarchy.A_levels[1:])
    next_hierarchy.N1 = set(next_hierarchy.N_levels[0])
    next_hierarchy.R1 = set(next_hierarchy.R_levels[0])
    return next_hierarchy


def _edge_graph(graph: Graph, edges: set[Edge]) -> Graph:
    from axiom.graph import Adjacency

    result = Adjacency(graph.n)
    for u, v in sorted(edges):
        result.add_edge(u, v)
    return result


def _partners(vertex: Vertex, edges: set[Edge]) -> list[Vertex]:
    return [v if u == vertex else u for u, v in edges if vertex in (u, v)]


def _level_lists(
    graph: Graph, vertices: set[Vertex], region: set[Vertex]
) -> dict[Vertex, list[Vertex]]:
    return {
        vertex: sorted(
            neighbor for neighbor in graph.neighbors(vertex) if neighbor in region
        )
        for vertex in vertices
    }
