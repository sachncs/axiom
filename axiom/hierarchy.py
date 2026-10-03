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

from array import array
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from heapq import merge
from itertools import chain, groupby, pairwise

from axiom.graph import Adjacency, empty
from axiom.hierarchies import Hierarchies
from axiom.paper_coloring import Paper
from axiom.storage import Packed
from axiom.system import System, degrees
from axiom.system import build as build_z_system
from axiom.types import Edge, Graph, Vertex, canonical
from axiom.vertices import Vertices


class SparseDegrees(dict[Vertex, int]):
    """Store only touched nonzero matching degrees for sparse refinement."""

    def __missing__(self, vertex: Vertex) -> int:
        """Treat an absent degree as zero without inserting a hash entry."""
        return 0


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
    A1: set[Vertex] | Vertices = field(default_factory=set)
    A2: set[Vertex] | Vertices = field(default_factory=set)
    N1: set[Vertex] | Vertices = field(default_factory=set)
    R1: set[Vertex] | Vertices = field(default_factory=set)
    A_levels: list[set[Vertex] | Vertices] = field(default_factory=list)
    N_levels: list[set[Vertex] | Vertices] = field(default_factory=list)
    R_levels: list[set[Vertex] | Vertices] = field(default_factory=list)
    L_levels: list[dict[Vertex, list[Vertex]]] = field(default_factory=list)
    deferred_deletions: set[Edge] = field(default_factory=set)
    journal: Hierarchies | None = field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Compact dense A-level rows while retaining sparse set storage."""
        if self.graph.n == 0:
            return
        for index, partition in enumerate(self.A_levels):
            if type(partition) is set and len(partition) * 4 >= self.graph.n:
                self.A_levels[index] = Vertices(
                    self.graph.n, partition, ordered=False
                )

    def counts(
        self, matching: set[Edge], ceiling: int
    ) -> dict[Vertex, int] | array[int] | None:
        """Count matching degrees sparsely or densely, failing at the cap."""
        if len(matching) * 36 < self.graph.n:
            result: dict[Vertex, int] = {}
            for left, right in matching:
                leftcount = result.get(left, 0) + 1
                rightcount = result.get(right, 0) + 1
                if leftcount > ceiling or rightcount > ceiling:
                    return None
                result[left] = leftcount
                result[right] = rightcount
            return result

        dense_result = degrees(self.graph.n)
        for left, right in matching:
            dense_result[left] += 1
            dense_result[right] += 1
            if dense_result[left] > ceiling or dense_result[right] > ceiling:
                return None
        return dense_result

    def __setattr__(self, name: str, value: object) -> None:
        """Keep an active hierarchy transaction handle bound to its owner."""
        if name == "journal" and getattr(self, "journal", None) is not None:
            raise RuntimeError("active hierarchy journal cannot be replaced")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        """Prevent deletion of the active hierarchy transaction handle."""
        if name == "journal" and getattr(self, "journal", None) is not None:
            raise RuntimeError("active hierarchy journal cannot be deleted")
        object.__delattr__(self, name)

    def defer(self, edge: Edge) -> None:
        """Retain an adversarial deletion in this phase graph."""
        if self.journal is None:
            self.deferred_deletions.add(edge)
        else:
            self.journal.change(edge, True)

    def undefer(self, edge: Edge) -> None:
        """Remove a restored or inserted edge from deferred phase deletions."""
        if self.journal is None:
            self.deferred_deletions.discard(edge)
        else:
            self.journal.change(edge, False)

    def clear(self) -> None:
        """Consume every deferred deletion at a parent-phase boundary."""
        if self.journal is None:
            self.deferred_deletions.clear()
        else:
            self.journal.clear()

    def sync_graph(
        self,
        graph: Graph,
        *,
        excluded_edges: set[Edge] | None = None,
        changed_edge: Edge | None = None,
    ) -> None:
        r"""Synchronize the phase graph and its adjacency indexes.

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
        excluded = excluded_edges or set()
        for label, edges in (("excluded_edges", excluded),):
            for edge in edges:
                if (
                    not isinstance(edge, tuple)
                    or len(edge) != 2
                    or not all(
                        isinstance(vertex, int) and not isinstance(vertex, bool)
                        for vertex in edge
                    )
                    or not 0 <= edge[0] < edge[1] < graph.n
                ):
                    raise ValueError(
                        f"{label} must contain canonical edges in [0, n): {edge!r}"
                    )
        if changed_edge is not None:
            left, right = changed_edge
            if (
                not isinstance(changed_edge, tuple)
                or len(changed_edge) != 2
                or not isinstance(left, int)
                or isinstance(left, bool)
                or not isinstance(right, int)
                or isinstance(right, bool)
                or not 0 <= left < right < graph.n
            ):
                raise ValueError(f"changed_edge must be canonical: {changed_edge}")
            if self.graph.n != graph.n:
                raise ValueError(
                    "cannot incrementally synchronize graphs of different sizes"
                )
            # The live graph has already applied the update.  A phase graph
            # keeps deferred adversarial deletions and omits current-phase
            # insertions, so only the changed edge's phase visibility can
            # differ.  Preserve the shared phase graph object and update its
            # indexes in O(log n) list work instead of rebuilding every level.
            should_exist = (
                graph.has_edge(left, right) or changed_edge in self.deferred_deletions
            ) and changed_edge not in excluded
            currently_exists = self.graph.has_edge(left, right)
            if should_exist != currently_exists:
                if should_exist:
                    self.graph.add_edge(left, right)
                else:
                    self.graph.remove_edge(left, right)
                edge = changed_edge
                added = should_exist
                left, right = edge
                for system in self.levels:
                    system.update(left, right, added)
                for index, vertices in enumerate(self.A_levels):
                    region = self.R_levels[index]
                    for source, target in ((left, right), (right, left)):
                        if source in vertices and target in region:
                            journal = self.levels[index].journal
                            if journal is None:
                                update(
                                    self.L_levels[index].setdefault(source, []),
                                    target,
                                    added,
                                )
                            else:
                                journal.edit(
                                    self.L_levels[index], source, target, added
                                )
            if self.graph.has_edge(left, right) != should_exist:
                raise RuntimeError("hierarchy phase edge delta was not applied")
            if not self.certify(left, right):
                reason = self.diagnose(left, right)
                raise RuntimeError(
                    f"hierarchy endpoint certificate failed: {reason}"
                )
            return

        phase_graph = empty(graph)
        if isinstance(graph, (Adjacency, Packed)):
            deferred_edges = iter(
                sorted(edge for edge in self.deferred_deletions if edge not in excluded)
            )
            live_edges = (edge for edge in graph.edges() if edge not in excluded)
            for edge, _ in groupby(merge(deferred_edges, live_edges)):
                phase_graph.add_edge(*edge)
        else:
            for left, right in self.deferred_deletions:
                if canonical(left, right) not in excluded:
                    phase_graph.add_edge(left, right)
            for left, right in graph.edges():
                if canonical(left, right) not in excluded and not phase_graph.has_edge(
                    left, right
                ):
                    phase_graph.add_edge(left, right)
        self.graph = phase_graph
        for system in self.levels:
            system.graph = phase_graph
            system.restrict(phase_graph)
            system.index()
        self.L_levels = [
            lists(phase_graph, vertices, self.R_levels[index])
            for index, vertices in enumerate(self.A_levels)
        ]

    def certify(self, left: Vertex, right: Vertex) -> bool:
        """Certify one synchronized edge delta across affected hierarchy rows.

        A phase update changes only the requested edge. Partition roots and
        matching sets stay fixed until rebuild; their full certificates run at
        construction/rebuild boundaries. This certificate checks every
        graph-dependent row and neighborhood bound for the two endpoints at
        every level, finest-level neighborhood caps, plus the matching-edge
        relation for the changed edge.
        """
        return self.diagnose(left, right) is None

    def diagnose(self, left: Vertex, right: Vertex) -> str | None:
        """Return the first failed endpoint-certificate condition, if any."""
        if (
            type(left) is not int
            or type(right) is not int
            or not 0 <= left < right < self.graph.n
        ):
            return "invalid edge endpoints"
        for index, level in enumerate(self.levels):
            if level.graph is not self.graph:
                return f"level {index} graph reference differs"
            for vertex in (left, right):
                neighbors = sorted(self.graph.neighbors(vertex))
                if vertex in level.U:
                    lambda_row = [
                        neighbor
                        for neighbor in neighbors
                        if neighbor in level.B or neighbor in level.U
                    ]
                    lambda_value = level.lambda_lists.get(vertex)
                    if lambda_row and lambda_value != lambda_row:
                        return f"level {index} Lambda row differs at {vertex}"
                    if not lambda_row and lambda_value is not None:
                        return f"level {index} has empty Lambda row at {vertex}"
                    if index == len(self.levels) - 1:
                        u_degree = sum(neighbor in level.U for neighbor in neighbors)
                        b_degree = sum(neighbor in level.B for neighbor in neighbors)
                        if u_degree > level.z:
                            return f"level {index} U-degree bound fails at {vertex}"
                        if b_degree > 2 * level.z:
                            return (
                                f"level {index} B-neighborhood bound fails at {vertex}"
                            )
                if vertex in level.A:
                    l_row = [neighbor for neighbor in neighbors if neighbor in level.U]
                    l_value = level.L_lists.get(vertex)
                    if l_row and l_value != l_row:
                        return f"level {index} L row differs at {vertex}"
                    if not l_row and l_value is not None:
                        return f"level {index} has empty L row at {vertex}"
                if canonical(left, right) in level.M and not self.graph.has_edge(
                    left, right
                ):
                    return f"level {index} matching contains absent edge"
                if vertex in self.A_levels[index]:
                    region_row = [
                        neighbor
                        for neighbor in neighbors
                        if neighbor in self.R_levels[index]
                    ]
                    if self.L_levels[index].get(vertex, []) != region_row:
                        return f"level {index} region row differs at {vertex}"
        return None

    def unionequals(
        self, target: Collection[Vertex], partitions: Sequence[Collection[Vertex]]
    ) -> bool:
        """Compare a set-like target to a partition union without a scratch set."""
        if self.graph.n and len(target) * 8 >= self.graph.n:
            members = bytearray(self.graph.n)
            population = 0
            for partition in partitions:
                for vertex in partition:
                    if type(vertex) is not int or not 0 <= vertex < self.graph.n:
                        return False
                    members[vertex] = 1
                    population += 1
            if population != len(target):
                return False
            return all(
                type(vertex) is int
                and 0 <= vertex < self.graph.n
                and members[vertex]
                for vertex in target
            )

        population = 0
        for partition in partitions:
            population += len(partition)
            if any(vertex not in target for vertex in partition):
                return False
        if population != len(target):
            return False
        return all(
            any(vertex in partition for partition in partitions)
            for vertex in target
        )

    def regionequals(
        self,
        region: Collection[Vertex],
        included: Sequence[Collection[Vertex]],
        excluded: Collection[Vertex],
    ) -> bool:
        """Check region = union(included) - excluded without materializing it."""
        if self.graph.n and len(region) * 8 >= self.graph.n:
            members = bytearray(self.graph.n)
            for partition in included:
                for vertex in partition:
                    if type(vertex) is not int or not 0 <= vertex < self.graph.n:
                        return False
                    members[vertex] = 1
            for vertex in excluded:
                if type(vertex) is not int or not 0 <= vertex < self.graph.n:
                    return False
                members[vertex] = 0
            if members.count(1) != len(region):
                return False
            return all(
                type(vertex) is int
                and 0 <= vertex < self.graph.n
                and members[vertex]
                for vertex in region
            )

        for vertex in region:
            if vertex in excluded or not any(
                vertex in partition for partition in included
            ):
                return False
        return all(
            vertex in excluded or vertex in region
            for partition in included
            for vertex in partition
        )

    def check(self) -> bool:
        """Validate the multi-level subgraph-system invariants."""
        if not self.levels or len(self.levels) != self.k:
            return False
        level_zs = [level.z for level in self.levels]
        if any(
            not isinstance(z, int) or isinstance(z, bool) or z <= 0 for z in level_zs
        ) or any(left <= right for left, right in pairwise(level_zs)):
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
            or not self.unionequals(self.A2, self.A_levels[1:])
            or self.N1 != self.N_levels[0]
            or self.R1 != self.R_levels[0]
        ):
            return False
        if any(
            not self.graph.has_edge(*edge) for edge in self.deferred_deletions
        ):
            return False
        for index, level in enumerate(self.levels):
            if level.graph is not self.graph or level.graph.n != self.graph.n:
                return False
            if (
                not self.unionequals(level.A, self.A_levels[: index + 1])
                or level.B != self.N_levels[index]
            ):
                return False
            # Refinement intentionally relaxes exact saturation for inherited
            # and active levels, so ``System.check()`` is too strong here.
            # Validate every structural/index invariant plus edge validity,
            # while the hierarchy-specific degree checks below
            # enforce the relaxed paper bounds.
            if (
                not level.check_edges()
                or not level.check_no_u_u_edges()
                or not level.check_partition()
                or not level.check_lambda()
                or not level.check_L()
            ):
                return False
            level_degree = self.counts(level.M, level.z)
            if level_degree is None:
                return False
            for left, right in level.M:
                if left in level.A and right not in level.A and right not in level.B:
                    return False
                if right in level.A and left not in level.A and left not in level.B:
                    return False
        system = self.levels[-1]
        z = system.z
        degree = level_degree
        if degree is None:
            return False
        all_a = system.A
        for index, region in enumerate(self.R_levels):
            below = [*self.A_levels[index + 1 :], system.B, system.U]
            if not self.regionequals(region, below, self.N_levels[index]):
                return False
            below_without_u = [*self.A_levels[index + 1 :], system.B]
            if any(
                vertex in system.U
                or not any(vertex in partition for partition in below_without_u)
                for vertex in self.N_levels[index]
            ):
                return False
        for u, v in system.M:
            if self.k > 1 and u in system.U and v in system.U:
                return False
        minimum = z - self.k + 1
        if isinstance(degree, dict):
            if any(degree.get(vertex, 0) < minimum for vertex in all_a) or any(
                degree.get(vertex, 0) < minimum for vertex in system.B
            ):
                return False
        elif any(degree[vertex] < minimum for vertex in all_a) or any(
            degree[vertex] < minimum for vertex in system.B
        ):
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
            lower = self.A_levels[: index + 1]
            for vertex in a_vertices:
                for other in self.graph.neighbors(vertex):
                    if canonical(vertex, other) not in system.M:
                        continue
                    if not any(other in partition for partition in lower) and (
                        other not in self.N_levels[index]
                    ):
                        return False
                expected = sorted(
                    neighbor
                    for neighbor in self.graph.neighbors(vertex)
                    if neighbor in self.R_levels[index]
                )
                if self.L_levels[index].get(vertex, []) != expected:
                    return False
        if self.R_levels[-1] != system.U:
            return False
        if any(
            vertex not in self.A2 and vertex not in self.levels[0].B
            for vertex in self.N1
        ):
            return False
        for left, right in self.levels[-1].M:
            if left in self.A1 and right not in self.A1 and right not in self.N1:
                return False
            if right in self.A1 and left not in self.A1 and left not in self.N1:
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
                if neighbor in system.B or neighbor in system.U
            )
            if system.lambda_lists.get(vertex, []) != expected:
                return False
        return True

    def check_i3(self, matching: set[tuple[int, int]], r: int, z: int) -> bool:
        r"""Check multi-level invariant (I3).

        At most :math:`2\tau` vertices of :math:`A_1` are matched by
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


def require(colorer: Paper | None) -> Paper:
    """Return the only colorer permitted for recursive hierarchy construction."""
    if colorer is None:
        return Paper()
    if not isinstance(colorer, Paper):
        raise ValueError(
            "recursive hierarchy construction requires Paper; "
            "alternate coloring implementations are not supported"
        )
    return colorer


def build_hierarchy(
    graph: Graph,
    level_zs: list[int],
    colorer: Paper | None = None,
    first: System | None = None,
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
            :math:`z` value of each level (coarsest first).
        colorer: Paper colorer used for recursive refinement, or ``None``
            to construct the default strategy.
        first: An already-built level-one System to refine. It must be idle,
            bound to ``graph``, and use ``level_zs[0]``. Supplying it avoids a
            duplicate full level-one construction when the caller must retain
            the original System separately. The builder may mutate this
            System during refinement; pass a detached copy to preserve it.

    Returns:
        A :class:`Hierarchy` whose ``levels`` list contains one
        entry per :math:`z` value.

    Complexity:
        Depends on the recursive edge-colouring and promotion work at each
        level.  The repository does not claim the paper's asymptotic bound
        until the complete ABB+26 construction and dynamic data structures
        are implemented and verified.
    """
    if not level_zs:
        raise ValueError("level_zs must contain at least one positive value")
    if any(z <= 0 for z in level_zs):
        raise ValueError("all level z values must be positive")
    if any(left <= right for left, right in pairwise(level_zs)):
        raise ValueError("level_zs must be strictly decreasing")

    active_colorer = require(colorer)
    system = build_z_system(graph, level_zs[0]) if first is None else first
    if (
        system.graph is not graph
        or system.z != level_zs[0]
        or system.journal is not None
    ):
        raise ValueError("first System must be idle and match the graph and z")
    hierarchy = Hierarchy(
        graph=system.graph,
        k=1,
        levels=[system],
        A_levels=[system.A],
        N_levels=[system.B],
        R_levels=[system.U],
        L_levels=[dict(system.L_lists)],
    )
    hierarchy.A1 = hierarchy.A_levels[0]
    hierarchy.A2 = set()
    hierarchy.N1 = hierarchy.N_levels[0]
    hierarchy.R1 = hierarchy.R_levels[0]
    for z in level_zs[1:]:
        hierarchy = refine_hierarchy(hierarchy, z, colorer=active_colorer)
    return hierarchy


def refine_hierarchy(
    hierarchy: Hierarchy,
    z_prime: int,
    *,
    deleted: set[Edge] | None = None,
    inserted: set[Edge] | None = None,
    colorer: Paper | None = None,
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
    vertices = range(hierarchy.graph.n)
    for label, edges in (("deleted", deleted), ("inserted", inserted)):
        for edge in edges:
            if not isinstance(edge, tuple) or len(edge) != 2:
                raise ValueError(f"{label} edges must be 2-tuples")
            left, right = edge
            if left not in vertices or right not in vertices or left >= right:
                raise ValueError(
                    f"{label} edges must be canonical endpoints in [0, n): {edge}"
                )
    missing = sorted(
        edge for edge in deleted if not hierarchy.graph.has_edge(*edge)
    )
    if missing:
        raise ValueError(
            "deleted edges must belong to the phase graph: " f"{missing}"
        )
    present = sorted(
        edge for edge in inserted if hierarchy.graph.has_edge(*edge)
    )
    if present:
        raise ValueError(
            "inserted edges must be absent from the phase graph: " f"{present}"
        )
    if deleted & inserted:
        raise ValueError("deleted and inserted edge sets must be disjoint")
    # The hierarchy graph is the phase-start snapshot.  ED is supplied as a
    # separate set, so remove it from the live side before selecting the
    # bounded deferred subset ED'.
    retained_deleted = deleted & previous.M
    subgraph = project(hierarchy.graph, previous.M)
    active_colorer = require(colorer)
    coloring = active_colorer.color(subgraph, z)
    if set(coloring) != set(previous.M):
        raise RuntimeError(
            "recursive refinement received an incomplete edge coloring: "
            f"missing={sorted(set(previous.M) - set(coloring))}"
        )
    incident_colors: dict[Vertex, set[int]] = {}
    for edge, color in coloring.items():
        if not isinstance(color, int) or isinstance(color, bool) or not 0 <= color <= z:
            raise RuntimeError(
                "recursive refinement received an invalid color: "
                f"edge={edge}, color={color!r}, expected an integer in 0..{z}"
            )
        u, v = edge
        u_colors = incident_colors.setdefault(u, set())
        v_colors = incident_colors.setdefault(v, set())
        if color in u_colors or color in v_colors:
            raise RuntimeError(
                "recursive refinement received a non-proper edge coloring: "
                f"color {color} conflicts on edge {edge}"
            )
        u_colors.add(color)
        v_colors.add(color)
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
        if edge in inserted
        or (edge not in deleted and hierarchy.graph.has_edge(*edge))
        or edge in deferred_deleted
    }
    if isinstance(hierarchy.graph, (Adjacency, Packed)):
        phase_edges = (
            edge
            for edge in hierarchy.graph.edges()
            if edge not in deleted or edge in deferred_deleted
        )
        working_graph = project(
            hierarchy.graph,
            merge(phase_edges, iter(sorted(inserted))),
            ordered=True,
        )
    else:
        working_edges = set(inserted)
        working_edges.update(
            edge
            for edge in hierarchy.graph.edges()
            if edge not in deleted or edge in deferred_deleted
        )
        working_graph = project(hierarchy.graph, working_edges)
    degree: SparseDegrees | array[int]
    if len(chosen) * 36 < hierarchy.graph.n:
        degree = SparseDegrees()
    else:
        degree = degrees(hierarchy.graph.n)
    for u, v in chosen:
        degree[u] += 1
        degree[v] += 1

    old_u = previous.U.copy()
    levels = list(hierarchy.A_levels)
    # The base construction already removes U-U matching edges.  Keep this
    # defensive normalization for explicitly supplied/custom hierarchies;
    # U vertices have no lower matching-degree requirement.
    for edge in tuple(chosen):
        if edge[0] in old_u and edge[1] in old_u:
            chosen.remove(edge)
            degree[edge[0]] -= 1
            degree[edge[1]] -= 1
    new_a: set[Vertex] = set()
    new_b: set[Vertex] = set()
    new_u = old_u
    # Avoid materializing A ∪ B: the first pass queries the immutable source
    # partitions directly. Once this pass finishes, new_a/new_b represent all
    # of old B plus each subsequently promoted U vertex.
    for vertex in sorted(previous.B):
        # Step 1 of the paper's construction keeps S and U fixed and
        # partitions the previous B according to the selected matching:
        # vertices whose selected M-neighbours all remain in S become the
        # new A_{h+1}; the rest remain in B.
        if all(
            neighbor in previous.A or neighbor in previous.B
            for neighbor in working_graph.neighbors(vertex)
            if canonical(vertex, neighbor) in chosen
        ):
            new_a.add(vertex)
        else:
            new_b.add(vertex)

    def normalize_b(vertex: Vertex) -> None:
        """Move a B vertex without an unsettled chosen partner into A."""
        if vertex in new_b and not any(
            partner in new_u and canonical(vertex, partner) in chosen
            for partner in working_graph.neighbors(vertex)
        ):
            new_b.remove(vertex)
            new_a.add(vertex)

    def normalize_b_neighbors(vertex: Vertex) -> None:
        """Normalize B vertices whose witness relation can change at this vertex."""
        for other in working_graph.neighbors(vertex):
            if canonical(vertex, other) in chosen:
                normalize_b(other)

    def promote(vertex: Vertex) -> None:
        """Move a U vertex into A or B and repair its neighbors' partitions."""
        if vertex not in new_u:
            return
        new_u.discard(vertex)
        # previous.A plus the already-built destination partitions is exactly
        # the settled region, without a universe-sized union snapshot.
        if degree[vertex] >= z_prime - h and all(
            neighbor in previous.A or neighbor in new_a or neighbor in new_b
            for neighbor in working_graph.neighbors(vertex)
            if canonical(vertex, neighbor) in chosen
        ):
            new_a.add(vertex)
        else:
            new_b.add(vertex)
        # Removing ``vertex`` from U can invalidate I1 for B-neighbours
        # that used it as their last M-witness.  Repair them immediately.
        normalize_b_neighbors(vertex)

    for vertex in sorted(new_u):
        if degree[vertex] >= z_prime - h:
            promote(vertex)

    changed = True
    previous_u_size = len(new_u)
    while changed:
        changed = False
        for vertex in sorted(new_u):
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
                for neighbor in sorted(working_graph.neighbors(vertex))
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

            # ProcProcess, second branch: the paper tests the number of B
            # neighbours, then performs exactly ``need`` swaps.  Every B
            # vertex must have a Z(v) witness edge into U by I1; if that
            # invariant is absent, fail instead of silently leaving the
            # vertex unprocessed.
            b_neighbors = [
                neighbor
                for neighbor in sorted(working_graph.neighbors(vertex))
                if neighbor in new_b
            ]
            if len(b_neighbors) >= z_prime:
                b_candidates: list[tuple[Vertex, Edge]] = []
                for neighbor in b_neighbors:
                    edge = canonical(vertex, neighbor)
                    if edge in chosen:
                        continue
                    witness = next(
                        (
                            canonical(neighbor, partner)
                            for partner in working_graph.neighbors(neighbor)
                            if partner in new_u
                            and canonical(neighbor, partner) in chosen
                        ),
                        None,
                    )
                    if witness is not None:
                        b_candidates.append((neighbor, witness))
                if len(b_candidates) < need:
                    raise RuntimeError(
                        "recursive refinement lost a B-to-U witness required "
                        f"for ProcProcess({vertex}); needed={need}, "
                        f"available={len(b_candidates)}"
                    )
                for neighbor, removed in b_candidates[:need]:
                    chosen.remove(removed)
                    for endpoint in removed:
                        degree[endpoint] -= 1
                    chosen.add(canonical(vertex, neighbor))
                    degree[vertex] += 1
                    degree[neighbor] += 1
                    normalize_b(neighbor)
                promote(vertex)
                changed = True

        # Every branch that continues the loop performs at least one promotion;
        # promotion removes a vertex from U and U is never repopulated. This
        # exact scalar potential replaces graph-sized cycle-key snapshots.
        if changed:
            current_u_size = len(new_u)
            if current_u_size >= previous_u_size:
                raise RuntimeError(
                    "recursive refinement continued without reducing U; "
                    "refusing a non-terminating hierarchy construction"
                )
            previous_u_size = current_u_size

    # ProcPromote keeps every B vertex attached to U through M.  A vertex
    # promoted to A may not subsequently acquire a U partner; normalize this
    # boundary explicitly before applying the B-to-A promotion.
    move_to_b = [
        vertex
        for vertex in new_a
        if any(
            neighbor in new_u and canonical(vertex, neighbor) in chosen
            for neighbor in working_graph.neighbors(vertex)
        )
    ]
    for vertex in move_to_b:
        new_a.remove(vertex)
        new_b.add(vertex)

    move_to_a = [
        vertex
        for vertex in new_b
        if not any(
            neighbor in new_u and canonical(vertex, neighbor) in chosen
            for neighbor in working_graph.neighbors(vertex)
        )
    ]
    for vertex in move_to_a:
        new_b.remove(vertex)
        new_a.add(vertex)

    # All retained levels describe the same refined phase graph.  Preserve
    # their level-specific M/partition state, but refresh the graph reference
    # and derived adjacency indexes so inherited state cannot point at an old
    # phase snapshot.
    for level in hierarchy.levels:
        level.graph = working_graph
        level.restrict(working_graph)
        level.index()

    stored_a: set[Vertex] | Vertices = new_a
    if hierarchy.graph.n and len(new_a) * 4 >= hierarchy.graph.n:
        stored_a = Vertices(hierarchy.graph.n, new_a, ordered=False)
    levelvalues = [*levels, stored_a]
    levelsize = sum(len(partition) for partition in levelvalues)
    combined_a: set[Vertex] | Vertices
    if hierarchy.graph.n and levelsize * 8 >= hierarchy.graph.n:
        combined_a = Vertices(
            hierarchy.graph.n,
            chain.from_iterable(levelvalues),
            ordered=False,
        )
    else:
        combined_a = set().union(*levelvalues)

    new_system = System(
        graph=working_graph,
        z=z_prime,
        A=combined_a,
        B=new_b,
        U=new_u,
        M=chosen,
    )
    new_system.index()

    all_a_levels = levelvalues
    all_n_levels = [*hierarchy.N_levels, new_system.B]
    all_b = new_system.B
    all_u = new_u
    all_r_levels: list[set[Vertex] | Vertices] = []
    for index in range(len(all_a_levels) - 1):
        excluded = all_n_levels[index]
        below: list[Collection[Vertex]] = [
            *all_a_levels[index + 1 :],
            all_b,
            all_u,
        ]
        region_size = sum(len(partition) for partition in below) - len(excluded)
        region = (
            vertex
            for partition in below
            for vertex in partition
            if vertex not in excluded
        )
        if hierarchy.graph.n and region_size * 8 >= hierarchy.graph.n:
            all_r_levels.append(
                Vertices(hierarchy.graph.n, region, ordered=False)
            )
        else:
            all_r_levels.append(set(region))
    all_r_levels.append(new_system.U)
    inherited_lists = [
        lists(working_graph, vertices, all_r_levels[index])
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
    next_hierarchy.A1 = next_hierarchy.A_levels[0]
    upper = (partition for partition in next_hierarchy.A_levels[1:] if partition)
    first = next(upper, None)
    second = next(upper, None)
    if first is None:
        next_hierarchy.A2 = set()
    elif second is None:
        next_hierarchy.A2 = first
    else:
        upperlevels = [first, second, *upper]
        upper_size = sum(len(partition) for partition in upperlevels)
        if hierarchy.graph.n and upper_size * 8 >= hierarchy.graph.n:
            next_hierarchy.A2 = Vertices(
                hierarchy.graph.n,
                chain.from_iterable(upperlevels),
                ordered=False,
            )
        else:
            combined = set(first)
            combined.update(second)
            for partition in upperlevels[2:]:
                combined.update(partition)
            next_hierarchy.A2 = combined
    next_hierarchy.N1 = next_hierarchy.N_levels[0]
    next_hierarchy.R1 = next_hierarchy.R_levels[0]
    if not next_hierarchy.check():
        raise RuntimeError(
            "recursive refinement produced an invalid inherited hierarchy"
        )
    return next_hierarchy


def project(
    graph: Graph, edges: Iterable[Edge], *, ordered: bool = False
) -> Graph:
    """Build an isolated graph from an edge set or a certified ordered stream."""
    if type(ordered) is not bool:
        raise TypeError("ordered selection must be a boolean")
    result = Packed(graph.n) if isinstance(graph, Adjacency) else empty(graph)
    candidates = edges if ordered else sorted(edges)
    previous: Edge | None = None
    for u, v in candidates:
        edge = u, v
        if ordered and previous is not None and edge <= previous:
            raise ValueError("ordered projection edges must be strictly increasing")
        result.add_edge(u, v)
        previous = edge
    return result


def lists(
    graph: Graph, vertices: Iterable[Vertex], region: Collection[Vertex]
) -> dict[Vertex, list[Vertex]]:
    """Index each supplied vertex's sorted neighbors in the requested region."""
    return {
        vertex: sorted(
            neighbor for neighbor in graph.neighbors(vertex) if neighbor in region
        )
        for vertex in vertices
    }


# Preserve the existing public helper while sharing the class-owned primitive.
update = System.change
