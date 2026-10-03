"""Stateful primitives used by the paper's deterministic coloring algorithm.

This module deliberately models the paper's partial-coloring interface rather
than exposing a second edge-coloring implementation.  The higher-level
``Extend`` recursion can therefore operate on explicit uncolored edges,
alternating paths, u-fans, and separable collections without treating a
classical complete coloring as an interchangeable substitute.
"""

from __future__ import annotations

import math
from collections.abc import ItemsView, Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType

from axiom.graph import Adjacency, empty
from axiom.storage import Packed
from axiom.types import Color, Edge, Graph, Vertex, canonical


@dataclass(frozen=True, slots=True)
class Fan:
    """A paper u-fan with two uncolored spokes and three assigned colors."""

    center: Vertex
    first: Vertex
    second: Vertex
    alpha: Color
    beta: Color
    gamma: Color

    def __post_init__(self) -> None:
        """Validate distinct vertices and the fan's two-color assignment."""
        vertices = (self.center, self.first, self.second)
        if len(set(vertices)) != 3:
            raise ValueError("u-fan vertices must be distinct")
        if self.alpha == self.beta:
            raise ValueError("u-fan center and first leaf colors must differ")
        if self.beta != self.gamma:
            raise ValueError("u-fan leaf colors must be equal")

    @property
    def edges(self) -> frozenset[Edge]:
        """Return the fan's two canonical, uncolored spokes."""
        return frozenset(
            {
                canonical(self.center, self.first),
                canonical(self.center, self.second),
            }
        )

    @property
    def vertices(self) -> tuple[Vertex, Vertex, Vertex]:
        """Return the center and leaves in their stored order."""
        return self.center, self.first, self.second

    def color(self, vertex: Vertex) -> Color:
        """Return the assigned missing color, raising KeyError outside the fan."""
        if vertex == self.center:
            return self.alpha
        if vertex == self.first:
            return self.beta
        if vertex == self.second:
            return self.gamma
        raise KeyError(vertex)

    @property
    def type(self) -> frozenset[Color]:
        """Return the two distinct colors defining this fan's type."""
        return frozenset((self.alpha, self.beta))

    def replace(self, vertex: Vertex, color: Color) -> Fan:
        """Return this fan with one assigned missing color changed."""
        if vertex == self.center:
            return Fan(
                self.center,
                self.first,
                self.second,
                color,
                self.beta,
                self.gamma,
            )
        if vertex == self.first:
            return Fan(
                self.center,
                self.first,
                self.second,
                self.alpha,
                color,
                self.gamma,
            )
        if vertex == self.second:
            return Fan(
                self.center,
                self.first,
                self.second,
                self.alpha,
                self.beta,
                color,
            )
        raise KeyError(vertex)


@dataclass(frozen=True, slots=True)
class Spoke:
    """An uncolored edge together with its paper u-edge center color.

    The ABB/ABBC construction does not treat an uncolored edge as an
    untyped pair.  The center endpoint carries a missing color (the
    ``alpha``-primed color) and that color determines which Vizing-fan pass
    processes the edge.  Keeping this state explicit prevents the fan-pruning
    phase from accidentally deriving a new color after a path operation.
    """

    edge: Edge
    alpha: Color

    @property
    def center(self) -> Vertex:
        """Return the oriented u-edge's center endpoint."""
        return self.edge[0]

    @property
    def leaf(self) -> Vertex:
        """Return the oriented u-edge's leaf endpoint."""
        return self.edge[1]


@dataclass(frozen=True, slots=True)
class Chain:
    """A materialized Vizing fan and its source-defined alternating chain."""

    spoke: Spoke
    leaves: tuple[Vertex, ...]
    path: tuple[Vertex, ...]
    colors: tuple[Color, ...] = ()

    @property
    def edges(self) -> tuple[Edge, ...]:
        """Return the chain's canonical path edges in traversal order."""
        return tuple(canonical(left, right) for left, right in pairwise(self.path))


@dataclass(frozen=True, slots=True)
class Event:
    """The first terminal path or prefix collision in a synchronized round."""

    terminal: Chain | None = None
    collision: tuple[Chain, Chain] | None = None


@dataclass(frozen=True, slots=True)
class Certificate:
    """Deterministic type accounting for a matching of uncolored edges.

    The ABB sparsification theorem is stated for an uncolored matching.  This
    value object keeps that boundary explicit: it records the equal palette
    blocks, every feasible type of each uncolored edge, and the edges whose
    feasible types intersect the diagonal block union.  It is deliberately a
    certificate, not a silent replacement for the theorem's alternating-path
    sparsifier; callers that need to change the coloring must perform that
    operation explicitly and revalidate the certificate.
    """

    blocks: tuple[frozenset[Color], ...]
    types: Mapping[Edge, frozenset[tuple[Color, Color]]]
    diagonal: frozenset[Edge]
    counts: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        """Freeze a copy of the feasible edge-type mapping."""
        object.__setattr__(self, "types", MappingProxyType(dict(self.types)))

    @property
    def fraction(self) -> float:
        """Return the fraction of uncolored edges with a diagonal type."""
        if not self.types:
            return 1.0
        return len(self.diagonal) / len(self.types)


class Partial:
    """A deterministic proper partial ``(delta + 1)`` edge coloring."""

    def __init__(self, graph: Graph, palette: int) -> None:
        """Initialize an empty coloring with a positive integer palette size."""
        if not isinstance(palette, int) or isinstance(palette, bool):
            raise ValueError("palette must be an integer")
        if palette <= 0:
            raise ValueError("palette must be positive")
        self.graph = graph
        self.palette = palette
        self.assignments: dict[Edge, Color] = {}
        self.incident: dict[Vertex, set[Color]] = {}
        self.index: dict[tuple[Vertex, Color], Edge] = {}

    def reindex(self) -> None:
        """Rebuild sparse per-vertex color rows after an atomic bulk edit."""
        incident: dict[Vertex, set[Color]] = {}
        edgebycolor: dict[tuple[Vertex, Color], Edge] = {}
        for (left, right), color in self.assignments.items():
            if (left, color) in edgebycolor or (right, color) in edgebycolor:
                raise AssertionError("partial coloring has duplicate incident colors")
            incident.setdefault(left, set()).add(color)
            incident.setdefault(right, set()).add(color)
            edgebycolor[(left, color)] = (left, right)
            edgebycolor[(right, color)] = (left, right)
        self.incident = incident
        self.index = edgebycolor

    def certify(self, edges: Iterable[Edge]) -> None:
        """Check the coloring and indexes only at vertices touched by edges."""
        vertices: set[Vertex] = set()
        for edge in edges:
            edge = canonical(*edge)
            vertices.update(edge)
            color = self.assignments.get(edge)
            if color is None:
                if edge in self.assignments:
                    raise AssertionError("partial coloring contains a null color")
                if any(
                    self.index.get((vertex, used)) == edge
                    for vertex in edge
                    for used in self.incident.get(vertex, ())
                ):
                    raise AssertionError("uncolored edge remains in the local index")
                continue
            if (
                not self.graph.has_edge(*edge)
                or not 0 <= color < self.palette
                or any(color not in self.incident.get(vertex, ()) for vertex in edge)
                or any(self.index.get((vertex, color)) != edge for vertex in edge)
            ):
                raise AssertionError(
                    f"partial coloring edge certificate failed: {edge}"
                )

        for vertex in vertices:
            expected: dict[Color, Edge] = {}
            for neighbor in self.graph.neighbors(vertex):
                edge = canonical(vertex, neighbor)
                color = self.assignments.get(edge)
                if color is None:
                    continue
                if color in expected:
                    raise AssertionError(f"improper coloring at vertex {vertex}")
                expected[color] = edge
            if set(expected) != self.incident.get(vertex, set()) or any(
                self.index.get((vertex, color)) != edge
                for color, edge in expected.items()
            ):
                raise AssertionError(
                    f"partial-coloring local index is stale at {vertex}"
                )

    def replace(self, changes: Mapping[Edge, Color | None]) -> None:
        """Atomically replace a bounded set of edge colors and local indexes."""
        normalized: dict[Edge, Color | None] = {}
        for edge, color in changes.items():
            edge = canonical(*edge)
            if edge in normalized:
                raise ValueError(f"duplicate edge in coloring replacement: {edge}")
            normalized[edge] = color
        if not normalized:
            return

        before = {edge: self.assignments.get(edge) for edge in normalized}
        affected = set(normalized)
        released: dict[Vertex, set[Color]] = {}
        proposed: dict[Vertex, set[Color]] = {}
        touched: set[tuple[Vertex, Color]] = set()
        for edge, old in before.items():
            if old is None:
                if edge in self.assignments:
                    raise AssertionError("partial coloring contains a null color")
                continue
            if (
                any(self.index.get((vertex, old)) != edge for vertex in edge)
                or any(old not in self.incident.get(vertex, ()) for vertex in edge)
            ):
                raise RuntimeError("partial-coloring old index is inconsistent")
            for vertex in edge:
                released.setdefault(vertex, set()).add(old)

        for edge, color in normalized.items():
            if color is None:
                continue
            if (
                not isinstance(color, int)
                or isinstance(color, bool)
                or not 0 <= color < self.palette
                or not self.graph.has_edge(*edge)
            ):
                raise ValueError(f"invalid replacement color for edge {edge}")
            for vertex in edge:
                colors = proposed.setdefault(vertex, set())
                if color in colors or (
                    color in self.incident.get(vertex, ())
                    and color not in released.get(vertex, set())
                ):
                    raise ValueError(f"replacement would conflict at vertex {vertex}")
                owner = self.index.get((vertex, color))
                if owner is not None and owner not in affected:
                    raise RuntimeError("replacement target contradicts the color index")
                colors.add(color)

        for edge, color in before.items():
            for vertex in edge:
                if color is not None:
                    touched.add((vertex, color))
                replacement = normalized[edge]
                if replacement is not None:
                    touched.add((vertex, replacement))

        try:
            for edge, old in before.items():
                if old is None:
                    continue
                self.assignments.pop(edge)
                for vertex in edge:
                    key = vertex, old
                    self.index.pop(key)
                    colors = self.incident[vertex]
                    colors.remove(old)
                    if not colors:
                        self.incident.pop(vertex)

            for edge, color in normalized.items():
                if color is None:
                    continue
                self.assignments[edge] = color
                for vertex in edge:
                    key = vertex, color
                    self.incident.setdefault(vertex, set()).add(color)
                    self.index[key] = edge
            self.certify(normalized)
        except BaseException:
            for edge in affected:
                self.assignments.pop(edge, None)
            for vertex, color in touched:
                owner = self.index.get((vertex, color))
                if owner in affected:
                    self.index.pop((vertex, color))
                if (vertex, color) not in self.index:
                    row = self.incident.get(vertex)
                    if row is not None:
                        row.discard(color)
                        if not row:
                            self.incident.pop(vertex)
            for edge, color in before.items():
                if color is None:
                    continue
                self.assignments[edge] = color
                for vertex in edge:
                    self.incident.setdefault(vertex, set()).add(color)
                    self.index[(vertex, color)] = edge
            raise

    def __contains__(self, edge: object) -> bool:
        """Return whether a canonical edge has an assigned color."""
        return edge in self.assignments

    def __getitem__(self, edge: Edge) -> Color:
        """Return an edge's assigned color, accepting either orientation."""
        return self.assignments[canonical(*edge)]

    def items(self) -> ItemsView[Edge, Color]:
        """Return a live view of the assigned edge colors."""
        return self.assignments.items()

    def edges(self) -> set[Edge]:
        """Return a copy of the set of colored edges."""
        return set(self.assignments)

    def relabel(self, mapping: dict[Color, Color]) -> None:
        """Apply a global permutation without duplicating edge assignments.

        Build and certify the replacement incidence indexes while assignment
        values are still untouched. Once staging succeeds, changing existing
        dictionary values cannot resize the assignment table, so the new rows
        can be published without retaining a second edge-to-color dictionary.
        """
        expected = set(range(self.palette))
        if set(mapping) != expected or set(mapping.values()) != expected:
            raise ValueError("color relabeling must be a permutation of the palette")
        incident: dict[Vertex, set[Color]] = {}
        edgebycolor: dict[tuple[Vertex, Color], Edge] = {}
        for edge, color in self.assignments.items():
            left, right = edge
            if not self.graph.has_edge(left, right):
                raise AssertionError(f"colored edge is outside graph: {edge}")
            replacement = mapping[color]
            if (left, replacement) in edgebycolor or (
                right,
                replacement,
            ) in edgebycolor:
                raise AssertionError(f"improper coloring at edge {edge}")
            edgebycolor[(left, replacement)] = edge
            edgebycolor[(right, replacement)] = edge
            incident.setdefault(left, set()).add(replacement)
            incident.setdefault(right, set()).add(replacement)

        for edge, color in self.assignments.items():
            self.assignments[edge] = mapping[color]
        self.incident = incident
        self.index = edgebycolor

    def missing(self, vertex: Vertex) -> list[Color]:
        """Return the vertex's missing palette colors in ascending order."""
        used = self.incident.get(vertex, ())
        return [
            color for color in range(self.palette) if color not in used
        ]

    def available(self, vertex: Vertex, color: Color) -> bool:
        """Return whether ``color`` is available at ``vertex`` in O(1)."""
        if (
            not isinstance(color, int)
            or isinstance(color, bool)
            or not 0 <= color < self.palette
        ):
            return False
        return color not in self.incident.get(vertex, ())

    def vacancy(self, vertex: Vertex) -> Color:
        """Return the smallest available color, or fail explicitly."""
        used = self.incident.get(vertex, ())
        for color in range(self.palette):
            if color not in used:
                return color
        raise RuntimeError(f"vertex {vertex} has no missing color")

    def validate(self) -> None:
        """Validate that every stored edge color is proper and in range."""
        seen: dict[Vertex, set[Color]] = {}
        for edge, color in self.assignments.items():
            if not self.graph.has_edge(*edge):
                raise AssertionError(f"colored edge is outside graph: {edge}")
            if not 0 <= color < self.palette:
                raise AssertionError(f"color is outside palette: {edge}={color}")
            left, right = edge
            leftcolors = seen.setdefault(left, set())
            rightcolors = seen.setdefault(right, set())
            if color in leftcolors or color in rightcolors:
                raise AssertionError(f"improper coloring at edge {edge}")
            leftcolors.add(color)
            rightcolors.add(color)
        if seen != self.incident:
            raise AssertionError("partial-coloring incident-color index is stale")
        rebuiltedges: dict[tuple[Vertex, Color], Edge] = {}
        for edge, color in self.assignments.items():
            left, right = edge
            rebuiltedges[(left, color)] = edge
            rebuiltedges[(right, color)] = edge
        if rebuiltedges != self.index:
            raise AssertionError("partial-coloring edge-color index is stale")

    def assign(self, edge: Edge, color: Color) -> None:
        """Color an uncolored graph edge and update its incidence indexes.

        Raises:
            ValueError: If the edge is absent or already colored, or the
                color is outside the palette or used at either endpoint.
        """
        edge = canonical(*edge)
        if not self.graph.has_edge(*edge):
            raise ValueError(f"cannot color an edge outside the graph: {edge}")
        if not isinstance(color, int) or isinstance(color, bool):
            raise ValueError("color must be an integer")
        if not 0 <= color < self.palette:
            raise ValueError(f"color must be in 0..{self.palette - 1}")
        if edge in self.assignments:
            raise ValueError(f"edge is already colored: {edge}")
        if color not in self.missing(edge[0]) or color not in self.missing(edge[1]):
            raise ValueError(f"color {color} is unavailable on edge {edge}")
        self.assignments[edge] = color
        self.incident.setdefault(edge[0], set()).add(color)
        self.incident.setdefault(edge[1], set()).add(color)
        self.index[(edge[0], color)] = edge
        self.index[(edge[1], color)] = edge

    def recolor(self, edge: Edge, color: Color) -> None:
        """Replace an edge color, restoring the original color on failure."""
        edge = canonical(*edge)
        if edge not in self.assignments:
            raise ValueError(f"edge is not colored: {edge}")
        old = self.unassign(edge)
        try:
            self.assign(edge, color)
        except Exception:
            self.assignments[edge] = old
            self.reindex()
            raise

    def unassign(self, edge: Edge) -> Color:
        """Make one colored edge uncolored and return its former color."""
        edge = canonical(*edge)
        try:
            old = self.assignments.pop(edge)
        except KeyError as error:
            raise ValueError(f"edge is not colored: {edge}") from error
        for vertex in edge:
            colors = self.incident[vertex]
            colors.remove(old)
            if not colors:
                self.incident.pop(vertex)
        self.index.pop((edge[0], old), None)
        self.index.pop((edge[1], old), None)
        return old

    def path(self, start: Vertex, beta: Color, gamma: Color) -> list[Vertex]:
        """Return the maximal simple path starting with ``second_color``."""
        if beta == gamma:
            raise ValueError("alternating path colors must differ")
        if not self.available(start, beta):
            raise ValueError("first color must be missing at the path start")
        path = [start]
        visited = {start}
        current = start
        wanted = gamma
        while True:
            edge = self.index.get((current, wanted))
            nextvertex = None
            if edge is not None:
                candidate = edge[1] if edge[0] == current else edge[0]
                if candidate not in visited:
                    nextvertex = candidate
            if nextvertex is None:
                return path
            path.append(nextvertex)
            visited.add(nextvertex)
            current = nextvertex
            wanted = beta if wanted == gamma else gamma

    def flip(self, path: list[Vertex], beta: Color, gamma: Color) -> None:
        """Flip an alternating path using only path-local index updates."""
        if len(path) < 1 or len(set(path)) != len(path):
            raise ValueError("path must be non-empty and simple")
        edges = [canonical(left, right) for left, right in pairwise(path)]
        if not edges:
            return
        if beta == gamma:
            raise ValueError("alternating path colors must differ")
        if any(edge not in self.assignments for edge in edges):
            raise ValueError("alternating path contains an uncolored edge")
        colors = [self.assignments[edge] for edge in edges]
        for index, color in enumerate(colors):
            if color != (gamma if index % 2 == 0 else beta):
                raise ValueError("path is not alternating from its start")
        if (
            type(self.assignments) is not dict
            or type(self.incident) is not dict
            or type(self.index) is not dict
            or any(type(self.incident[vertex]) is not set for vertex in path)
        ):
            raise TypeError("path flips require the owned plain coloring indexes")

        replacements: list[Color] = []
        targets: list[tuple[tuple[Vertex, Color], Edge]] = []
        for edge, color in zip(edges, colors, strict=True):
            replacement = beta if color == gamma else gamma
            replacements.append(replacement)
            for vertex in edge:
                oldkey = vertex, color
                if self.index.get(oldkey) != edge:
                    raise RuntimeError("path edge-color index is inconsistent")
                if color not in self.incident[vertex]:
                    raise RuntimeError("path incidence index is inconsistent")
                targets.append(((vertex, replacement), edge))

        endpoints = (
            (
                path[0],
                replacements[0],
                colors[0],
                edges[0],
                (path[0], replacements[0]),
                (path[0], colors[0]),
            ),
            (
                path[-1],
                replacements[-1],
                colors[-1],
                edges[-1],
                (path[-1], replacements[-1]),
                (path[-1], colors[-1]),
            ),
        )
        for vertex, replacement, _, _, newkey, _ in endpoints:
            if replacement in self.incident[vertex]:
                raise ValueError(
                    "path flip would use a color already present at an endpoint"
                )
            if newkey in self.index:
                raise RuntimeError("endpoint color index contradicts its incidence")

        # Endpoint entries are the only new dictionary/set cells. Reserve them
        # before changing any coloring value; an allocation failure removes the
        # partial reservation and leaves all live state untouched.
        first_color = first_key = second_color = second_key = False
        try:
            first = endpoints[0]
            second = endpoints[1]
            self.incident[first[0]].add(first[1])
            first_color = True
            self.index[first[4]] = first[3]
            first_key = True
            self.incident[second[0]].add(second[1])
            second_color = True
            self.index[second[4]] = second[3]
            second_key = True
        except BaseException:
            if second_key:
                self.index.pop(endpoints[1][4])
            if second_color:
                self.incident[endpoints[1][0]].discard(endpoints[1][1])
            if first_key:
                self.index.pop(endpoints[0][4])
            if first_color:
                self.incident[endpoints[0][0]].discard(endpoints[0][1])
            raise

        for edge, replacement in zip(edges, replacements, strict=True):
            self.assignments[edge] = replacement
        for key, edge in targets:
            self.index[key] = edge
        for vertex, _, oldcolor, _, _, oldkey in endpoints:
            self.index.pop(oldkey)
            self.incident[vertex].remove(oldcolor)


class ColorJournal:
    """Retain first-write before-images for a bounded Partial coloring region."""

    def __init__(
        self, coloring: Partial, parent: ColorJournal | None = None
    ) -> None:
        """Bind a local before-image to its owner and optional enclosing journal."""
        self.coloring = coloring
        self.parent = parent
        self.before: dict[Edge, Color | None] = {}

    def capture(self, edges: Iterable[Edge]) -> None:
        """Capture each edge's original color once, including uncolored edges."""
        for edge in edges:
            edge = canonical(*edge)
            if edge not in self.before:
                if self.parent is not None:
                    self.parent.capture((edge,))
                self.before[edge] = self.coloring.assignments.get(edge)

    def rollback(self) -> None:
        """Restore captured coloring cells through the local owner certificate."""
        self.coloring.replace(self.before)


class Fans:
    """Deterministic collection enforcing the paper's separability invariant."""

    def __init__(self) -> None:
        """Initialize an empty separable collection and all of its indexes."""
        self.members: set[Fan] = set()
        self.spokes: set[Edge] = set()
        self.assignments: dict[tuple[Vertex, Color], Fan] = {}
        self.assigned: dict[Vertex, set[Color]] = {}
        self.vertices: dict[Vertex, set[Fan]] = {}
        self.types: dict[frozenset[Color], set[Fan]] = {}

    def __len__(self) -> int:
        """Return the number of stored fans."""
        return len(self.members)

    def __iter__(self) -> Iterator[Fan]:
        """Iterate over fans in deterministic center-and-leaf order."""
        return iter(
            sorted(
                self.members,
                key=lambda fan: (fan.center, fan.first, fan.second),
            )
        )

    def add(self, fan: Fan) -> None:
        """Add a fan, rejecting shared spokes or shared vertex-color assignments."""
        if fan in self.members:
            raise ValueError("u-fan is already present")
        if self.spokes.intersection(fan.edges):
            raise ValueError("u-fan collection must be edge-disjoint")
        for vertex in fan.vertices:
            key = (vertex, fan.color(vertex))
            if key in self.assignments:
                raise ValueError("u-fan colors must be distinct at each vertex")
        self.members.add(fan)
        self.spokes.update(fan.edges)
        self.types.setdefault(fan.type, set()).add(fan)
        for vertex in fan.vertices:
            self.assignments[(vertex, fan.color(vertex))] = fan
            self.assigned.setdefault(vertex, set()).add(fan.color(vertex))
            self.vertices.setdefault(vertex, set()).add(fan)

    def discard(self, fan: Fan) -> None:
        """Remove a fan from every index, doing nothing if it is absent."""
        if fan not in self.members:
            return
        self.members.remove(fan)
        self.spokes.difference_update(fan.edges)
        typed = self.types.get(fan.type)
        if typed is not None:
            typed.discard(fan)
            if not typed:
                self.types.pop(fan.type)
        for vertex in fan.vertices:
            color = fan.color(vertex)
            self.assignments.pop((vertex, color), None)
            assigned = self.assigned.get(vertex)
            if assigned is not None:
                assigned.discard(color)
                if not assigned:
                    self.assigned.pop(vertex)
            members = self.vertices.get(vertex)
            if members is not None:
                members.discard(fan)
                if not members:
                    self.vertices.pop(vertex)

    def relabel(self, mapping: dict[Color, Color]) -> None:
        """Apply a global color permutation while preserving all indexes."""
        replacement = type(self)()
        for fan in self.members:
            replacement.add(
                Fan(
                    fan.center,
                    fan.first,
                    fan.second,
                    mapping[fan.alpha],
                    mapping[fan.beta],
                    mapping[fan.gamma],
                )
            )
        replacement.validate()
        self.members = replacement.members
        self.spokes = replacement.spokes
        self.assignments = replacement.assignments
        self.assigned = replacement.assigned
        self.vertices = replacement.vertices
        self.types = replacement.types

    def at(self, vertex: Vertex) -> tuple[Fan, ...]:
        """Return fans containing ``vertex`` in deterministic order."""
        return tuple(
            sorted(
                self.vertices.get(vertex, set()),
                key=lambda fan: (fan.center, fan.first, fan.second),
            )
        )

    def locate(self, vertices: tuple[Vertex, Vertex, Vertex]) -> Fan | None:
        """Return the fan with exactly ``vertices`` in stored order."""
        for fan in self.vertices.get(vertices[0], set()):
            if fan.vertices == vertices:
                return fan
        return None

    def update(self, fan: Fan, vertex: Vertex, color: Color) -> Fan | None:
        """Update one fan with preallocated local index deltas.

        A structurally invalid replacement or a separability collision removes
        the damaged fan, as required after a path flip. Unexpected failures
        during allocation leave every original index cell unchanged.
        """
        if fan not in self.members:
            return None
        try:
            replacement = fan.replace(vertex, color)
        except ValueError:
            self.discard(fan)
            return None

        if replacement == fan:
            return fan
        if replacement in self.members:
            self.discard(fan)
            return None

        oldtype = fan.type
        newtype = replacement.type
        oldassignments = tuple(
            (item, fan.color(item), (item, fan.color(item))) for item in fan.vertices
        )
        newassignments = tuple(
            (item, replacement.color(item), (item, replacement.color(item)))
            for item in replacement.vertices
        )
        assignedsets = tuple(self.assigned[item] for item in fan.vertices)
        vertexsets = tuple(self.vertices[item] for item in fan.vertices)
        typed = self.types[oldtype]
        if (
            not all(self.assignments[key] == fan for _, _, key in oldassignments)
            or not all(color in values for values, (_, color, _) in zip(
                assignedsets, oldassignments, strict=True
            ))
            or not all(fan in values for values in vertexsets)
            or fan not in typed
        ):
            raise RuntimeError("fan indexes are inconsistent before update")

        newtyped = self.types.get(newtype)
        if newtyped is not None and replacement in newtyped:
            self.discard(fan)
            return None
        for item, newcolor, newkey in newassignments:
            owner = self.assignments.get(newkey)
            if owner is not None and owner != fan:
                self.discard(fan)
                return None
            if newcolor != fan.color(item) and newcolor in self.assigned[item]:
                self.discard(fan)
                return None
            if replacement in self.vertices[item]:
                raise RuntimeError("fan vertex index contains a stale replacement")

        createdtype = newtyped is None
        if createdtype:
            newtyped = {replacement}
        if newtyped is None:
            raise RuntimeError("fan type reservation failed")
        stages = [False] * 11
        try:
            self.members.add(replacement)
            stages[0] = True
            if createdtype:
                self.types[newtype] = newtyped
                stages[1] = True
            else:
                newtyped.add(replacement)
                stages[1] = True
            for index, ((item, oldcolor, oldkey), (_, newcolor, newkey)) in enumerate(
                zip(oldassignments, newassignments, strict=True)
            ):
                if newkey != oldkey:
                    self.assignments[newkey] = replacement
                    stages[2 + index] = True
                if newcolor != oldcolor:
                    self.assigned[item].add(newcolor)
                    stages[5 + index] = True
                self.vertices[item].add(replacement)
                stages[8 + index] = True
        except BaseException:
            for index, ((item, _, _), (_, _, newkey)) in enumerate(
                zip(oldassignments, newassignments, strict=True)
            ):
                if stages[2 + index]:
                    self.assignments.pop(newkey, None)
                if stages[5 + index]:
                    self.assigned[item].discard(newassignments[index][1])
                if stages[8 + index]:
                    self.vertices[item].discard(replacement)
            if stages[1]:
                if not createdtype:
                    newtyped.discard(replacement)
                else:
                    self.types.pop(newtype, None)
            if stages[0]:
                self.members.discard(replacement)
            raise

        for (item, oldcolor, oldkey), (_, newcolor, newkey) in zip(
            oldassignments, newassignments, strict=True
        ):
            if oldkey == newkey:
                self.assignments[newkey] = replacement
            else:
                self.assignments.pop(oldkey)
            if oldcolor != newcolor:
                self.assigned[item].remove(oldcolor)
            self.vertices[item].remove(fan)
        typed.remove(fan)
        if not typed:
            self.types.pop(oldtype)
        self.members.remove(fan)
        return replacement

    def flip(
        self,
        coloring: Partial,
        path: list[Vertex],
        beta: Color,
        gamma: Color,
    ) -> None:
        """Flip coloring and endpoint fans as one local rollback unit."""
        if not path:
            coloring.flip(path, beta, gamma)
            return
        endpoints = (path[0],) if path[0] == path[-1] else (path[0], path[-1])
        affected = sum(len(self.at(endpoint)) for endpoint in endpoints)
        oldfans: list[Fan | None] = [None] * affected
        newfans: list[Fan | None] = [None] * affected
        vertices = [0] * affected
        oldcolors = [0] * affected
        position = 0
        colorchanged = False
        inversepath = list(reversed(path)) if len(path) > 1 else []
        if inversepath:
            lastedge = canonical(path[-2], path[-1])
            oldlast = coloring.assignments.get(lastedge)
            if oldlast not in {beta, gamma}:
                raise RuntimeError("path endpoint color is inconsistent")
            inversebeta = oldlast
            inversegamma = beta if oldlast == gamma else gamma
        else:
            inversebeta = beta
            inversegamma = gamma

        try:
            coloring.flip(path, beta, gamma)
            colorchanged = bool(inversepath)
            for endpoint in endpoints:
                for fan in self.at(endpoint):
                    assigned = fan.color(endpoint)
                    if assigned not in {beta, gamma}:
                        continue
                    replacementcolor = gamma if assigned == beta else beta
                    replacement = self.update(fan, endpoint, replacementcolor)
                    if replacement is None:
                        if fan not in self.members:
                            oldfans[position] = fan
                            vertices[position] = endpoint
                            oldcolors[position] = assigned
                            position += 1
                    elif replacement != fan:
                        oldfans[position] = fan
                        newfans[position] = replacement
                        vertices[position] = endpoint
                        oldcolors[position] = assigned
                        position += 1
        except BaseException:
            try:
                for index in range(position - 1, -1, -1):
                    original = oldfans[index]
                    replacement = newfans[index]
                    if original is None:
                        raise RuntimeError("fan rollback record is missing")
                    if replacement is None:
                        self.add(original)
                    else:
                        restored = self.update(
                            replacement, vertices[index], oldcolors[index]
                        )
                        if restored != original:
                            raise RuntimeError("fan rollback did not restore its value")
                if colorchanged:
                    coloring.flip(inversepath, inversebeta, inversegamma)
            except BaseException as failure:
                raise RuntimeError(
                    "fan/color flip rollback failed; discard paper state"
                ) from failure
            raise

    def find(self, vertex: Vertex, color: Color) -> Fan | None:
        """Return the fan assigning this color at the vertex, or None."""
        return self.assignments.get((vertex, color))

    def select(self, fantype: frozenset[Color]) -> tuple[Fan, ...]:
        """Return fans of one type in deterministic order."""
        return tuple(
            sorted(
                self.types.get(fantype, set()),
                key=lambda fan: (fan.center, fan.first, fan.second),
            )
        )

    def counts(self) -> dict[frozenset[Color], int]:
        """Return a copy of the indexed fan-type counts."""
        return {fantype: len(members) for fantype, members in self.types.items()}

    def missing(self, coloring: Partial, vertex: Vertex) -> Color:
        """Return ``Missing-Color_U(vertex)`` from the bounded palette prefix."""
        used = self.assigned.get(vertex, set())
        limit = min(coloring.palette, coloring.graph.degree(vertex) + 1)
        for color in range(limit):
            if color not in used and coloring.available(vertex, color):
                return color
        raise RuntimeError(
            "no bounded missing color remains outside the fan collection; "
            f"vertex={vertex}, degree={coloring.graph.degree(vertex)}"
        )

    def validate(self) -> None:
        """Check separability and all fan indexes, raising AssertionError on damage."""
        if len(self.spokes) != sum(len(fan.edges) for fan in self.members):
            raise AssertionError("u-fan edges are not disjoint")
        rebuilt: dict[tuple[Vertex, Color], Fan] = {}
        for fan in self.members:
            for vertex in fan.vertices:
                key = (vertex, fan.color(vertex))
                if key in rebuilt:
                    raise AssertionError("u-fan colors collide at a vertex")
                rebuilt[key] = fan
        if rebuilt != self.assignments:
            raise AssertionError("u-fan color index is stale")
        rebuiltfancolors: dict[Vertex, set[Color]] = {}
        for fan in self.members:
            for vertex in fan.vertices:
                rebuiltfancolors.setdefault(vertex, set()).add(fan.color(vertex))
        if rebuiltfancolors != self.assigned:
            raise AssertionError("u-fan assigned-color index is stale")
        rebuiltvertices: dict[Vertex, set[Fan]] = {}
        for fan in self.members:
            for vertex in fan.vertices:
                rebuiltvertices.setdefault(vertex, set()).add(fan)
        if rebuiltvertices != self.vertices:
            raise AssertionError("u-fan vertex index is stale")
        rebuilttypes: dict[frozenset[Color], set[Fan]] = {}
        for fan in self.members:
            rebuilttypes.setdefault(fan.type, set()).add(fan)
        if rebuilttypes != self.types:
            raise AssertionError("u-fan type index is stale")

    def certify(self, vertices: Iterable[Vertex]) -> None:
        """Audit fan indexes at vertices in a proven mutation region."""
        for vertex in set(vertices):
            members = self.vertices.get(vertex, set())
            colors = self.assigned.get(vertex, set())
            if len(members) != len(colors):
                raise AssertionError(f"u-fan vertex index is stale at {vertex}")
            seen: set[Color] = set()
            for fan in members:
                color = fan.color(vertex)
                if (
                    fan not in self.members
                    or fan not in self.types.get(fan.type, ())
                    or color in seen
                    or color not in colors
                    or self.assignments.get((vertex, color)) != fan
                    or any(edge not in self.spokes for edge in fan.edges)
                ):
                    raise AssertionError(f"u-fan index certificate failed at {vertex}")
                seen.add(color)
            if seen != colors:
                raise AssertionError(f"u-fan color row is stale at {vertex}")
            for color in colors:
                owner = self.assignments.get((vertex, color))
                if owner not in members or owner.color(vertex) != color:
                    raise AssertionError(f"u-fan assignment is stale at {vertex}")

    def compatible(
        self, coloring: Partial, vertices: Iterable[Vertex] | None = None
    ) -> None:
        """Validate fan spokes and assigned colors against ``coloring``.

        ``validate`` checks only the collection's own indexes.  The ABB
        operations also require every spoke to be an uncolored graph edge and
        every fan color to be missing at its assigned endpoint.  Keeping this
        check explicit prevents a stale or hand-built fan collection from
        entering an atomic path-modification operation.
        """
        candidates: Iterable[Fan]
        if vertices is None:
            candidates = self
        else:
            affectedfans = {
                fan
                for vertex in vertices
                for fan in self.vertices.get(vertex, ())
            }
            candidates = sorted(
                affectedfans,
                key=lambda fan: (fan.center, fan.first, fan.second),
            )
        for fan in candidates:
            if any(not coloring.graph.has_edge(*edge) for edge in fan.edges):
                raise AssertionError(f"u-fan spoke is outside the graph: {fan}")
            if any(edge in coloring for edge in fan.edges):
                raise AssertionError(f"u-fan spoke is already colored: {fan}")
            for vertex in fan.vertices:
                if not coloring.available(vertex, fan.color(vertex)):
                    raise AssertionError(
                        "u-fan assigned color is not missing at its vertex: "
                        f"fan={fan}, vertex={vertex}"
                    )

    def repair(
        self, coloring: Partial, vertices: Iterable[Vertex] | None = None
    ) -> int:
        """Remove invalid fans globally or only at explicitly changed vertices."""
        candidates: Iterable[Fan]
        if vertices is None:
            candidates = self.members
        else:
            localcandidates: set[Fan] = set()
            for vertex in vertices:
                localcandidates.update(self.vertices.get(vertex, ()))
            candidates = localcandidates
        damaged = [
            fan
            for fan in candidates
            if any(
                not coloring.available(vertex, fan.color(vertex))
                for vertex in fan.vertices
            )
            or any(edge in coloring for edge in fan.edges)
        ]
        for fan in damaged:
            self.discard(fan)
        return len(damaged)


class BlockedColors(Mapping[Vertex, set[Color]]):
    """Read fan and active-u-edge blocked colors without a whole-fan copy."""

    def __init__(self, fans: Fans, centers: Mapping[Vertex, set[Color]]) -> None:
        """Retain the fan color index and the active-center delta map."""
        self.fans = fans
        self.centers = centers

    def __getitem__(self, vertex: Vertex) -> set[Color]:
        """Return blocked colors at one vertex, or raise when none are indexed."""
        fancolors = self.fans.assigned.get(vertex)
        centercolors = self.centers.get(vertex)
        if fancolors is None and centercolors is None:
            raise KeyError(vertex)
        return set(fancolors or ()) | set(centercolors or ())

    def __iter__(self) -> Iterator[Vertex]:
        """Iterate the union of fan-index and active-center vertices."""
        yield from self.fans.assigned
        yield from (
            vertex for vertex in self.centers if vertex not in self.fans.assigned
        )

    def __len__(self) -> int:
        """Return the number of distinct vertices with blocked colors."""
        return len(self.fans.assigned) + sum(
            vertex not in self.fans.assigned for vertex in self.centers
        )


class Vizing:
    """Deterministic paper vizing strategy."""

    @classmethod
    def fan(
        cls,
        coloring: Partial,
        center: Vertex,
        first: Vertex,
        blocked: Mapping[Vertex, set[Color]] | None = None,
        fans: Fans | None = None,
    ) -> tuple[list[Vertex], list[Color]]:
        """Construct the paper's deterministic ``VizingF`` sequence."""
        leaves = [first]

        def chooseleafcolor(vertex: Vertex) -> Color:
            """Return the first missing color outside the blocked fan assignments."""
            unavailable = set() if blocked is None else blocked.get(vertex, set())
            for color in coloring.missing(vertex):
                if color not in unavailable and (
                    fans is None or color not in fans.assigned.get(vertex, ())
                ):
                    return color
            raise RuntimeError(
                f"U-avoiding Vizing fan has no available leaf color: vertex={vertex}"
            )

        colors = [chooseleafcolor(first)]
        while True:
            terminal = colors[-1]
            if coloring.available(center, terminal) or terminal in colors[:-1]:
                return leaves, colors
            extension = next(
                (
                    neighbor
                    for neighbor in sorted(coloring.graph.neighbors(center))
                    if neighbor not in leaves
                    and coloring.assignments.get(canonical(center, neighbor))
                    == terminal
                ),
                None,
            )
            if extension is None:
                raise RuntimeError(
                    "Vizing fan construction could not find the terminal-color edge"
                )
            leaves.append(extension)
            colors.append(chooseleafcolor(extension))

    @classmethod
    def build(
        cls,
        coloring: Partial,
        spoke: Spoke,
        blocked: Mapping[Vertex, set[Color]] | None = None,
        fans: Fans | None = None,
    ) -> Chain:
        """Build the paper's Vizing fan and its maximal chain for one u-edge."""
        leaves, colors = cls.fan(
            coloring, spoke.center, spoke.leaf, blocked, fans
        )
        leavestuple = tuple(leaves)
        colorstuple = tuple(colors)
        terminal = colorstuple[-1]
        if coloring.available(spoke.center, terminal):
            return Chain(spoke, leavestuple, (), colorstuple)
        path = tuple(coloring.path(spoke.center, spoke.alpha, terminal))
        if path and path[0] != spoke.center:
            raise RuntimeError("Vizing chain does not start at its fan center")
        return Chain(spoke, leavestuple, path, colorstuple)

    @classmethod
    def explore(
        cls,
        chains: tuple[Chain, ...],
    ) -> Event:
        """Explore chain prefixes in synchronized rounds.

        Every round advances each still-live chain by one edge.  The owner index
        is keyed by canonical edges, so meeting in either orientation is detected
        as the same paper path collision.  The function does not mutate coloring;
        callers must resolve the returned event atomically.
        """
        if not chains:
            raise ValueError("chain exploration requires at least one chain")
        owners: dict[Edge, Chain] = {}
        maximum = max((len(chain.edges) for chain in chains), default=0)
        for depth in range(maximum + 1):
            for chain in chains:
                edges = chain.edges
                if depth >= len(edges):
                    if depth == 0:
                        return Event(terminal=chain)
                    continue
                edge = edges[depth]
                owner = owners.get(edge)
                if owner is not None and owner is not chain:
                    return Event(collision=(owner, chain))
                owners[edge] = chain
            for chain in chains:
                if len(chain.edges) == depth + 1:
                    return Event(terminal=chain)
        raise RuntimeError("Vizing chain exploration terminated without an event")

    @classmethod
    def opposite(cls, edge: Edge, vertex: Vertex) -> Vertex:
        """Return the endpoint of ``edge`` different from ``vertex``."""
        if edge[0] == vertex:
            return edge[1]
        if edge[1] == vertex:
            return edge[0]
        raise ValueError(f"vertex {vertex} is not an endpoint of edge {edge}")

    @classmethod
    def restore(
        cls,
        fans: Fans,
        snapshot: Iterable[Fan],
        vertices: Iterable[Vertex] | None = None,
    ) -> None:
        """Restore a fan collection globally or within a proven local region."""
        current: set[Fan]
        if vertices is None:
            current = set(fans.members)
        else:
            current = set()
            for vertex in vertices:
                current.update(fans.vertices.get(vertex, ()))
        for fan in current:
            fans.discard(fan)
        for fan in snapshot:
            fans.add(fan)

    @classmethod
    def activate(cls, coloring: Partial, chain: Chain) -> Edge:
        """Run the paper's ``Vizing(F)`` operation for one materialized fan."""
        center = chain.spoke.center
        leaves = list(chain.leaves)
        if not leaves:
            raise RuntimeError("Vizing activation requires a non-empty fan")
        edge = chain.spoke.edge
        if edge in coloring:
            raise ValueError(f"u-edge is already colored: {edge}")
        colors = list(chain.colors)
        if len(colors) != len(leaves):
            raise RuntimeError("Vizing chain is missing its fan leaf-color sequence")
        terminal = colors[-1]
        alpha = chain.spoke.alpha
        pathedges = [
            canonical(left, right) for left, right in pairwise(chain.path)
        ]
        spokeedges = [canonical(center, leaf) for leaf in leaves]
        affected = dict.fromkeys((*pathedges, *spokeedges))
        before = {
            candidate: coloring.assignments.get(candidate) for candidate in affected
        }
        try:
            if coloring.available(center, terminal):
                # Trivial fan: rotate every assigned spoke and color the final
                # spoke with the terminal missing color.
                coloring.replace(
                    {
                        canonical(center, leaf): color
                        for leaf, color in zip(leaves, colors, strict=True)
                    }
                )
                return edge

            repeated = next(
                (index for index, color in enumerate(colors[:-1]) if color == terminal),
                None,
            )
            if repeated is None:
                raise RuntimeError(
                    "non-trivial Vizing fan has no repeated terminal color"
                )
            if not chain.path or chain.path[0] != center:
                raise RuntimeError("non-trivial Vizing fan has no source-defined path")
            pathendsatrepeatedleaf = chain.path[-1] == leaves[repeated]
            coloring.flip(list(chain.path), alpha, terminal)
            if pathendsatrepeatedleaf:
                rotationleaves = leaves
                rotationcolors = [
                    coloring[canonical(center, leaf)] for leaf in leaves[1:]
                ] + [terminal]
            else:
                rotationleaves = leaves[: repeated + 1]
                rotationcolors = colors[: repeated + 1]
            changes = {
                canonical(center, leaf): color
                for leaf, color in zip(
                    rotationleaves, rotationcolors, strict=True
                )
            }
            coloring.replace(changes)
            if edge not in coloring:
                raise RuntimeError("Vizing rotation did not color the source u-edge")
            return edge
        except Exception:
            coloring.replace(before)
            coloring.validate()
            raise

    @classmethod
    def color(cls, coloring: Partial, edge: Edge, batch: bool = False) -> Edge:
        """Activate one uncolored edge through the paper Vizing primitive."""
        if type(batch) is not bool:
            raise TypeError("batch selection must be a boolean")
        edge = canonical(*edge)
        if edge in coloring:
            raise ValueError(f"edge is already colored: {edge}")
        alpha = coloring.vacancy(edge[0])
        chain = cls.build(coloring, Spoke(edge, alpha))
        candidates = chain.edges + tuple(
            canonical(chain.spoke.center, leaf) for leaf in chain.leaves
        )
        before = {
            candidate: coloring.assignments.get(candidate) for candidate in candidates
        }
        try:
            result = cls.activate(coloring, chain)
            if not batch:
                coloring.validate()
            return result
        except Exception:
            coloring.replace(before)
            coloring.validate()
            raise

    @classmethod
    def resolve(
        cls,
        coloring: Partial,
        fans: Fans,
        collision: tuple[Chain, Chain],
    ) -> tuple[bool, int]:
        """Apply one paper same/opposite-direction chain collision if valid.

        The operation is deliberately transactional.  The local fan builder is a
        deterministic implementation boundary, so a collision is accepted only
        when the resulting spokes and missing colors satisfy the full u-fan
        certificate. A rejected collision restores both snapshots and returns
        a failure result; reduction then reports the unsupported transformation.
        """
        first, second = collision
        if first.spoke.alpha != second.spoke.alpha:
            raise ValueError("chain collisions must be within one alpha group")
        firstedges = first.edges
        secondedges = second.edges
        firstpositions = {edge: index for index, edge in enumerate(firstedges)}
        secondpositions = {edge: index for index, edge in enumerate(secondedges)}
        common = firstpositions.keys() & secondpositions.keys()
        if not common:
            raise RuntimeError("chain collision has no shared canonical edge")
        # Match explore's round order: at each depth, the first chain is
        # checked before the second. The first-chain hit at the current depth
        # can therefore precede a second-chain hit even when its other index
        # is smaller. Selecting an arbitrary shared edge can retain overlap in
        # the prefixes that the resolver is about to activate.
        shared = min(
            common,
            key=lambda edge: (
                max(firstpositions[edge], secondpositions[edge]),
                0 if firstpositions[edge] > secondpositions[edge] else 1,
                firstpositions[edge],
                secondpositions[edge],
            ),
        )
        firstindex = firstpositions[shared]
        secondindex = secondpositions[shared]
        affectededges = set(firstedges) | set(secondedges)
        for chain in collision:
            affectededges.update(
                canonical(chain.spoke.center, leaf) for leaf in chain.leaves
            )
        affectedvertices = {vertex for edge in affectededges for vertex in edge}
        colorjournal = ColorJournal(coloring)
        colorjournal.capture(affectededges)
        fansbefore = {
            fan
            for vertex in affectedvertices
            for fan in fans.vertices.get(vertex, ())
        }
        alpha = first.spoke.alpha
        try:
            samedirection = (
                first.path[firstindex] == second.path[secondindex]
                and first.path[firstindex + 1] == second.path[secondindex + 1]
            )
            if samedirection:
                if firstindex == 0 or secondindex == 0:
                    return False, 0
                firstpredecessor = firstedges[firstindex - 1]
                secondpredecessor = secondedges[secondindex - 1]
                if firstpredecessor == secondpredecessor:
                    return False, 0
                beta = coloring[firstpredecessor]
                coloring.unassign(firstpredecessor)
                coloring.unassign(secondpredecessor)
                firstprefix = Chain(
                    first.spoke, first.leaves, first.path[:firstindex], first.colors
                )
                secondprefix = Chain(
                    second.spoke,
                    second.leaves,
                    second.path[:secondindex],
                    second.colors,
                )
                cls.activate(coloring, firstprefix)
                cls.activate(coloring, secondprefix)
                center = first.path[firstindex]
                left = cls.opposite(firstpredecessor, center)
                right = cls.opposite(secondpredecessor, center)
                created = Fan(center, left, right, beta, alpha, alpha)
                if firstpredecessor in coloring or secondpredecessor in coloring:
                    raise RuntimeError("same-direction shift recolored a predecessor")
                fans.add(created)
                fans.compatible(coloring, affectedvertices)
                return True, 2

            coloring.unassign(shared)
            firstprefix = Chain(
                first.spoke,
                first.leaves,
                first.path[: firstindex + 1],
                first.colors,
            )
            secondprefix = Chain(
                second.spoke,
                second.leaves,
                second.path[: secondindex + 1],
                second.colors,
            )
            cls.activate(coloring, firstprefix)
            cls.activate(coloring, secondprefix)
            if shared in coloring:
                raise RuntimeError("opposite-direction shift recolored the shared edge")
            return True, 2
        except (RuntimeError, ValueError, KeyError, AssertionError):
            colorjournal.rollback()
            cls.restore(fans, fansbefore, affectedvertices)
            return False, 0

    @classmethod
    def rotate(
        cls, coloring: Partial, center: Vertex, fan: list[Vertex], width: int
    ) -> None:
        """Shift a fan prefix's spoke colors to expose its last edge."""
        oldcolors = [
            coloring[canonical(center, fan[index + 1])] for index in range(width)
        ]
        changes: dict[Edge, Color | None] = {
            canonical(center, fan[index]): color
            for index, color in enumerate(oldcolors)
        }
        if width > 0:
            changes[canonical(center, fan[width])] = None
        coloring.replace(changes)


class Pruning:
    """Deterministic paper pruning strategy."""

    vizing: type[Vizing] = Vizing

    @classmethod
    def seed(cls, coloring: Partial, uncolorededges: set[Edge]) -> tuple[Spoke, ...]:
        """Construct the paper's initial separable collection of u-edges.

        ``ConUFans`` starts from a matching of uncolored edges.  A matching is a
        meaningful precondition here: it lets every edge choose a distinct center
        color without first solving another coloring problem.  The canonical
        endpoint is used as the center so the result is deterministic.
        """
        graphedges = set(coloring.graph.edges())
        if not uncolorededges <= graphedges:
            raise ValueError("uncolorededges must be edges of the graph")
        if uncolorededges & coloring.edges():
            raise ValueError("uncolorededges must not contain colored edges")
        usedvertices: set[Vertex] = set()
        seeded: list[Spoke] = []
        for edge in sorted(uncolorededges):
            if edge[0] in usedvertices or edge[1] in usedvertices:
                raise ValueError("ConUFans requires a matching of uncolored edges")
            missing = coloring.missing(edge[0])
            if not missing:
                raise RuntimeError(f"u-edge center has no missing color: {edge}")
            seeded.append(Spoke(edge, missing[0]))
            usedvertices.update(edge)
        return tuple(seeded)

    @classmethod
    def refresh(cls, coloring: Partial, item: Spoke) -> Spoke | None:
        """Revalidate one active u-edge after a path mutation.

        A Vizing activation can change which colors are missing at another active
        center.  Such an edge must not continue with a stale alpha certificate;
        retain it only when uncolored and deterministically reseed alpha when the
        old color is no longer missing.
        """
        if item.edge in coloring:
            return None
        if coloring.available(item.center, item.alpha):
            return item
        missing = coloring.missing(item.center)
        if not missing:
            raise RuntimeError(
                f"active u-edge center has no missing color: {item.edge}"
            )
        return Spoke(item.edge, missing[0])

    @classmethod
    def renew(
        cls, coloring: Partial, items: tuple[Spoke, ...] | list[Spoke]
    ) -> list[Spoke]:
        """Refresh a deterministic active-u-edge sequence after mutations."""
        refreshed: list[Spoke] = []
        for item in items:
            current = cls.refresh(coloring, item)
            if current is not None:
                refreshed.append(current)
        return refreshed

    @classmethod
    def expose(
        cls,
        coloring: Partial,
        center: Vertex,
        leaves: list[Vertex],
        target: Vertex,
    ) -> None:
        """Rotate a Vizing fan until ``(center, target)`` is uncolored."""
        try:
            index = leaves.index(target)
        except ValueError as error:
            raise RuntimeError(
                "Vizing fan does not contain the requested leaf"
            ) from error
        if index:
            cls.vizing.rotate(coloring, center, leaves, index)
        edge = canonical(center, target)
        if edge in coloring:
            raise RuntimeError("Vizing fan rotation did not expose an uncolored edge")

    @classmethod
    def choose(
        cls, coloring: Partial, fans: Fans, vertex: Vertex, blocked: set[Color]
    ) -> Color:
        """Choose the deterministic color used at a newly created u-fan center."""
        for color in coloring.missing(vertex):
            if color not in blocked and fans.find(vertex, color) is None:
                return color
        raise RuntimeError(
            "no missing center color remains for a newly created u-fan: "
            f"vertex={vertex}"
        )

    @classmethod
    def blocked(
        cls, fans: Fans, uedges: tuple[Spoke, ...]
    ) -> BlockedColors:
        """Read fan colors lazily and index only active u-edge centers."""
        blocked: dict[Vertex, set[Color]] = {}
        for item in uedges:
            blocked.setdefault(item.center, set()).add(item.alpha)
        return BlockedColors(fans, blocked)

    @classmethod
    def prune(
        cls,
        coloring: Partial,
        fans: Fans,
        uedges: tuple[Spoke, ...],
        *,
        journal: ColorJournal | None = None,
    ) -> tuple[Spoke, ...]:
        """Run pruning atomically, including the caller-owned fan collection."""
        colorjournal = ColorJournal(coloring, journal)
        createdfans: list[Fan] = []
        try:
            if not uedges:
                return ()
            alpha = uedges[0].alpha
            if any(item.alpha != alpha for item in uedges):
                raise ValueError(
                    "PruneVFans processes one alpha-primed group at a time"
                )

            active: list[tuple[Spoke, list[Vertex]]] = []
            pending = list(uedges)
            deferred: list[Spoke] = []
            while pending:
                original = pending.pop(0)
                item = cls.refresh(coloring, original)
                if item is None:
                    continue
                if item.alpha != alpha:
                    deferred.append(item)
                    continue
                blocked = cls.blocked(
                    fans,
                    tuple(entry[0] for entry in active) + (item,),
                )
                leaves, ignored = cls.vizing.fan(
                    coloring, item.center, item.leaf, blocked
                )
                collision = None
                for vertex in (item.center, *leaves):
                    if any(
                        vertex in (other.center, *otherleaves)
                        for other, otherleaves in active
                    ):
                        collision = vertex
                        break
                if collision is None:
                    active.append((item, leaves))
                    continue

                existingindex = next(
                    index
                    for index, (ignored, otherleaves) in enumerate(active)
                    if collision in (active[index][0].center, *otherleaves)
                )
                existing, existingleaves = active[existingindex]
                currentisexistingleaf = item.center in existingleaves
                existingiscurrentleaf = existing.center in leaves

                if currentisexistingleaf:
                    colorjournal.capture(
                        canonical(existing.center, leaf) for leaf in existingleaves
                    )
                    cls.expose(coloring, existing.center, existingleaves, item.center)
                    exposed = canonical(existing.center, item.center)
                    if not coloring.available(
                        existing.center, alpha
                    ) or not coloring.available(item.center, alpha):
                        raise RuntimeError(
                            "PruneVFans exposed an unavailable alpha edge"
                        )
                    coloring.assign(exposed, alpha)
                    active.pop(existingindex)
                    pending = [entry[0] for entry in active] + pending
                    active = []
                    continue

                if existingiscurrentleaf:
                    colorjournal.capture(
                        canonical(item.center, leaf) for leaf in leaves
                    )
                    cls.expose(coloring, item.center, leaves, existing.center)
                    exposed = canonical(item.center, existing.center)
                    if not coloring.available(
                        item.center, alpha
                    ) or not coloring.available(existing.center, alpha):
                        raise RuntimeError(
                            "PruneVFans exposed an unavailable alpha edge"
                        )
                    coloring.assign(exposed, alpha)
                    active.pop(existingindex)
                    pending = [entry[0] for entry in active] + pending
                    active = []
                    continue

                # The first shared vertex is a leaf of both fans.  Rotating both fans
                # exposes the two spokes used by the paper's new u-fan.
                shared = collision
                colorjournal.capture(
                    canonical(item.center, leaf) for leaf in leaves
                )
                colorjournal.capture(
                    canonical(existing.center, leaf) for leaf in existingleaves
                )
                cls.expose(coloring, item.center, leaves, shared)
                cls.expose(coloring, existing.center, existingleaves, shared)
                if not coloring.available(item.center, alpha) or not coloring.available(
                    existing.center, alpha
                ):
                    raise RuntimeError("PruneVFans lost alpha at a u-fan leaf")
                beta = cls.choose(coloring, fans, shared, {alpha})
                created = Fan(shared, item.center, existing.center, beta, alpha, alpha)
                createdfans.append(created)
                fans.add(created)
                active.pop(existingindex)
                pending = [entry[0] for entry in active] + pending
                active = []

            refreshed = cls.renew(
                coloring, [item for item, ignored in active] + deferred
            )
            fans.validate()
            fans.compatible(coloring)
            return tuple(refreshed)
        except Exception:
            colorjournal.rollback()
            for fan in reversed(createdfans):
                fans.discard(fan)
            coloring.validate()
            fans.validate()
            raise

    @classmethod
    def reduce(
        cls,
        coloring: Partial,
        fans: Fans,
        uedges: tuple[Spoke, ...],
        *,
        journal: ColorJournal | None = None,
    ) -> int:
        """Reduce the surviving pruned u-edges through deterministic Vizing chains.

        ``ReduceUEdges`` removes a surviving u-edge either by extending the
        coloring or by preserving a newly formed u-fan.  Chain prefixes are now
        explored in synchronized rounds, with canonical-edge collision detection.
        Collision resolution is transactional and never substitutes a different
        coloring algorithm when its paper preconditions are not met.
        """
        coloring.validate()
        fans.validate()
        fans.compatible(coloring)
        extended = 0
        active = cls.renew(coloring, uedges)
        while active:
            active = cls.renew(coloring, active)
            if not active:
                break
            # Chain collisions are defined within one alpha group.  A preceding
            # activation can reseed an active u-edge to a different missing color,
            # so the list that was originally grouped by alpha is no longer a
            # valid batch.  Repartition after every mutation and process the
            # smallest alpha group first to keep the reduction deterministic.
            alpha = min(item.alpha for item in active)
            group = tuple(item for item in active if item.alpha == alpha)
            blocked = cls.blocked(fans, group)
            chains = tuple(
                cls.vizing.build(coloring, item, blocked) for item in group
            )
            event = cls.vizing.explore(chains)
            if event.terminal is not None:
                selectedchains: tuple[Chain, ...] = (event.terminal,)
            elif event.collision is not None:
                collisionchains = event.collision
                if journal is not None:
                    for chain in collisionchains:
                        journal.capture(chain.edges)
                        journal.capture(
                            canonical(chain.spoke.center, leaf)
                            for leaf in chain.leaves
                        )
                resolved, added = cls.vizing.resolve(
                    coloring, fans, collisionchains
                )
                if resolved:
                    active = [
                        item
                        for item in active
                        if item not in {chain.spoke for chain in event.collision}
                    ]
                    extended += added
                    collisionedges = {
                        edge
                        for chain in collisionchains
                        for edge in chain.edges
                    }
                    for chain in collisionchains:
                        collisionedges.update(
                            canonical(chain.spoke.center, leaf)
                            for leaf in chain.leaves
                        )
                    changedvertices = {
                        vertex for edge in collisionedges for vertex in edge
                    }
                    fans.repair(coloring, changedvertices)
                    coloring.certify(collisionedges)
                    fans.certify(changedvertices)
                    fans.compatible(coloring, changedvertices)
                    continue
                raise RuntimeError(
                    "ReduceUEdges could not apply the paper chain-collision "
                    "transformation for the current fan state"
                )
            else:
                raise RuntimeError("chain exploration returned an empty event")
            changededges: set[Edge] = set()
            for chain in selectedchains:
                item = chain.spoke
                if item not in active or item.edge in coloring:
                    continue
                if journal is not None:
                    journal.capture(chain.edges)
                    journal.capture(
                        canonical(chain.spoke.center, leaf) for leaf in chain.leaves
                    )
                cls.vizing.activate(coloring, chain)
                changededges.update(chain.edges)
                changededges.update(
                    canonical(chain.spoke.center, leaf) for leaf in chain.leaves
                )
                active.remove(item)
                extended += 1
            changedvertices = {
                vertex for edge in changededges for vertex in edge
            }
            fans.repair(coloring, changedvertices)
            coloring.certify(changededges)
            fans.certify(changedvertices)
            fans.compatible(coloring, changedvertices)
        coloring.validate()
        fans.validate()
        fans.compatible(coloring)
        return extended

    @classmethod
    def construct(
        cls,
        coloring: Partial,
        uncolorededges: set[Edge],
        *,
        journal: ColorJournal | None = None,
    ) -> Fans:
        """Construct paper u-fans from a matching of uncolored edges.

        This executes the explicit ``create u-edges``, ``PruneVFans``, and the
        validated deterministic reduction phase of ``ConUFans``.  The returned
        collection contains only u-fans that survived reduction; every seeded
        u-edge is either colored or represented by that collection.
        """
        coloring.validate()
        if not uncolorededges:
            return Fans()
        colorjournal = ColorJournal(coloring, journal)
        try:
            seeded = cls.seed(coloring, uncolorededges)
            result = Fans()
            bycolor: dict[Color, list[Spoke]] = {}
            for item in seeded:
                bycolor.setdefault(item.alpha, []).append(item)
            for color in sorted(bycolor):
                remaining = cls.prune(
                    coloring,
                    result,
                    tuple(bycolor[color]),
                    journal=colorjournal,
                )
                cls.reduce(coloring, result, remaining, journal=colorjournal)
            coloring.validate()
            result.validate()
            result.compatible(coloring)
            colored = sum(edge in coloring for edge in uncolorededges)
            required = max(1, (len(uncolorededges) + 17) // 18)
            if colored + len(result) < required:
                raise RuntimeError(
                    "ConUFans failed its constant-fraction progress certificate: "
                    f"colored={colored}, fans={len(result)}, required={required}"
                )
            return result
        except Exception:
            colorjournal.rollback()
            coloring.validate()
            raise


class Construction:
    """Deterministic paper construction strategy."""

    vizing: type[Vizing] = Vizing
    pruning: type[Pruning] = Pruning

    @classmethod
    def activate(
        cls,
        coloring: Partial,
        fans: Fans,
        fan: Fan,
        journal: ColorJournal | None = None,
    ) -> Edge:
        """Activate one u-fan, extending the coloring to one spoke."""
        if fan not in fans.members:
            raise ValueError("fan must belong to the collection")
        spokes = {
            canonical(fan.center, fan.first),
            canonical(fan.center, fan.second),
        }
        if any(not coloring.graph.has_edge(*edge) for edge in spokes):
            raise ValueError("u-fan spokes must belong to the graph")
        if any(edge in coloring for edge in spokes):
            raise ValueError("u-fan spokes must both be uncolored")
        for vertex, color in (
            (fan.center, fan.alpha),
            (fan.first, fan.beta),
            (fan.second, fan.gamma),
        ):
            if not coloring.available(vertex, color):
                raise ValueError("u-fan colors must be missing at their vertices")
        paths = [
            (fan.first, fan.beta),
            (fan.second, fan.gamma),
        ]
        for leaf, leafcolor in paths:
            path = coloring.path(leaf, leafcolor, fan.alpha)
            if fan.center not in path:
                if journal is not None:
                    journal.capture(
                        (
                            *(
                                canonical(left, right)
                                for left, right in pairwise(path)
                            ),
                            canonical(fan.center, leaf),
                        )
                    )
                affectedvertices = set(fan.vertices)
                affectedvertices.update(path)
                affectedfans = {
                    member
                    for vertex in affectedvertices
                    for member in fans.vertices.get(vertex, ())
                }
                typesbefore = {
                    member.vertices: member.type for member in affectedfans
                }
                # Remove the activated fan before flipping.  Otherwise
                # ``flip_path`` may replace its endpoint assignment in the
                # collection, leaving a stale fan whose spoke is now colored.
                fans.discard(fan)
                fans.flip(coloring, path, leafcolor, fan.alpha)
                edge = canonical(fan.center, leaf)
                coloring.assign(edge, fan.alpha)
                currentfans = {
                    member
                    for vertex in affectedvertices
                    for member in fans.vertices.get(vertex, ())
                }
                for member in currentfans:
                    previous = typesbefore.get(member.vertices)
                    if previous is not None and member.type != previous:
                        fans.discard(member)
                fans.repair(coloring, affectedvertices)
                return edge
        raise RuntimeError("both u-fan alternating paths reach the center")

    @classmethod
    def small(cls, coloring: Partial, fans: Fans) -> int:
        """Run the paper's deterministic most-common-type ``Color-Small`` step.

        The routine repeatedly selects the lexicographically first most-common
        u-fan type and activates all currently matching fans.  Fans damaged by a
        successful path flip are removed explicitly.  A failure to activate a
        valid fan is an invariant failure and is reported; no alternate coloring
        algorithm is substituted.
        """
        coloring.validate()
        fans.validate()
        fans.compatible(coloring)
        journal = ColorJournal(coloring)
        fansbefore = tuple(fans)
        extended = 0
        rounds = 0
        maxrounds = max(1, coloring.palette**2)
        try:
            while len(fans):
                rounds += 1
                if rounds > maxrounds:
                    raise RuntimeError(
                        "Color-Small exceeded its deterministic mu^2 iteration "
                        "bound without exhausting the fan collection"
                    )
                counts = fans.counts()
                target = min(
                    counts, key=lambda value: (-counts[value], tuple(sorted(value)))
                )
                batch = list(fans.select(target))
                for fan in batch:
                    if fan not in fans.members:
                        continue
                    try:
                        cls.activate(coloring, fans, fan, journal)
                    except (RuntimeError, ValueError) as error:
                        raise RuntimeError(
                            f"Color-Small could not activate valid fan {fan}"
                        ) from error
                    extended += 1
            fans.validate()
            fans.compatible(coloring)
            coloring.validate()
            return extended
        except Exception:
            journal.rollback()
            for fan in tuple(fans):
                fans.discard(fan)
            for fan in fansbefore:
                fans.add(fan)
            coloring.validate()
            fans.validate()
            raise

    @classmethod
    def direct(cls, coloring: Partial, uncolorededges: set[Edge]) -> Fans:
        """Collect directly constructible separable u-fans deterministically.

        This is the explicit, local part of the paper's fan-construction
        interface.  It only uses supplied uncolored edges; it never moves edges
        or invokes a different coloring algorithm.  The complete paper
        construction will extend this boundary with its fan-chain shifting step.
        """
        graphedges = set(coloring.graph.edges())
        if not uncolorededges <= graphedges:
            raise ValueError("uncolorededges must be edges of the graph")
        if uncolorededges & coloring.edges():
            raise ValueError("uncolorededges must not contain colored edges")

        incident: dict[Vertex, list[Vertex]] = {
            vertex: [] for vertex in range(coloring.graph.n)
        }
        for left, right in sorted(uncolorededges):
            incident[left].append(right)
            incident[right].append(left)

        palettes = {
            vertex: set(coloring.missing(vertex)) for vertex in range(coloring.graph.n)
        }
        fans = Fans()
        usedspokes: set[Edge] = set()
        for center in range(coloring.graph.n):
            leaves = incident[center]
            for index, first in enumerate(leaves):
                firstedge = canonical(center, first)
                if firstedge in usedspokes:
                    continue
                for second in leaves[index + 1 :]:
                    secondedge = canonical(center, second)
                    if secondedge in usedspokes:
                        continue
                    centercolors = palettes[center]
                    firstcolors = palettes[first]
                    secondcolors = palettes[second]
                    commonleafcolors = sorted(firstcolors & secondcolors)
                    for leafcolor in commonleafcolors:
                        centercandidates = sorted(centercolors - {leafcolor})
                        if not centercandidates:
                            continue
                        candidate = Fan(
                            center,
                            first,
                            second,
                            centercandidates[0],
                            leafcolor,
                            leafcolor,
                        )
                        try:
                            fans.add(candidate)
                        except ValueError:
                            continue
                        usedspokes.update((firstedge, secondedge))
                        break
                    if firstedge in usedspokes:
                        break
        fans.validate()
        return fans

    @classmethod
    def shift(cls, coloring: Partial, edge: Edge, fans: Fans) -> Fan | None:
        """Shift one uncolored edge into a valid two-spoke u-fan.

        For an uncolored ``(u, v)``, choose a color missing at ``v`` but used at
        ``u``.  Uncoloring the unique edge of that color incident to ``u`` gives
        the second fan spoke and makes the color missing at its other endpoint.
        """
        edge = canonical(*edge)
        if edge in coloring:
            raise ValueError("edge must be uncolored before fan shifting")
        for center, leaf in (edge, (edge[1], edge[0])):
            centermissing = set(coloring.missing(center))
            leafmissing = sorted(coloring.missing(leaf))
            for leafcolor in leafmissing:
                if leafcolor in centermissing:
                    continue
                witness = next(
                    (
                        canonical(center, neighbor)
                        for neighbor in sorted(coloring.graph.neighbors(center))
                        if coloring.assignments.get(canonical(center, neighbor))
                        == leafcolor
                    ),
                    None,
                )
                if witness is None:
                    continue
                other = witness[1] if witness[0] == center else witness[0]
                alpha = min(centermissing - {leafcolor})
                oldcolor = coloring.unassign(witness)
                candidate = Fan(
                    center,
                    leaf,
                    other,
                    alpha,
                    leafcolor,
                    leafcolor,
                )
                try:
                    fans.add(candidate)
                except ValueError:
                    coloring.assign(witness, oldcolor)
                    continue
                return candidate
        return None

    @classmethod
    def collect(cls, coloring: Partial, uncolorededges: set[Edge]) -> Fans:
        """Construct a separable fan collection by direct fans and witness shifts.

        Direct two-spoke fans are selected first.  Every remaining uncolored edge
        is then offered to the deterministic witness-shift operation exactly once.
        If a shift is unavailable, the paper's alternative progress case is
        performed explicitly by extending that edge through the deterministic
        fan-chain operation.  The routine therefore never silently drops an edge:
        it either builds a fan or certifiably extends a constant fraction of the
        supplied uncolored set.
        """
        graphedges = set(coloring.graph.edges())
        if not uncolorededges <= graphedges:
            raise ValueError("uncolorededges must be edges of the graph")
        if uncolorededges & coloring.edges():
            raise ValueError("uncolorededges must not contain colored edges")

        if not uncolorededges:
            return Fans()
        minimumprogress = max(1, (len(uncolorededges) + 99) // 100)
        extendededges = 0
        fans = cls.direct(coloring, set(uncolorededges))
        fanedges = {edge for fan in fans for edge in fan.edges}
        pending = sorted(set(uncolorededges) - fanedges)
        # ConUFans starts from a matching of uncolored edges.  Use its explicit
        # u-edge/Vizing-fan pruning phase whenever that precondition is available;
        # the general non-matching case remains in the separate local path below.
        endpoints = {endpoint for edge in pending for endpoint in edge}
        ismatching = len(endpoints) == 2 * len(pending)
        if len(pending) >= 2 and ismatching:
            constructed = cls.pruning.construct(coloring, set(pending))
            extendededges += sum(edge in coloring for edge in pending)
            # ConUFans may rotate colors while reducing its matching.  Any direct
            # fan selected before that operation must be revalidated before the
            # two collections are merged; otherwise a stale color assignment can
            # collide with a newly constructed fan or enter Extend invalidly.
            fans.repair(coloring)
            for fan in constructed:
                fans.add(fan)
                fanedges.update(fan.edges)
            pending = [edge for edge in pending if edge not in coloring]
        if len(fans) >= minimumprogress:
            fans.compatible(coloring)
            return fans
        for edge in pending:
            if edge in coloring or edge in fanedges:
                continue
            shifted = cls.shift(coloring, edge, fans)
            if shifted is not None:
                fanedges.update(shifted.edges)
            else:
                cls.vizing.color(coloring, edge)
                extendededges += 1
                # Fan-chain flips can change a missing color assigned to an
                # existing fan.  Remove those fans before exposing the
                # collection to Color-Small or Amplify.
                fans.repair(coloring)
            if len(fans) + extendededges >= minimumprogress:
                break
        fans.validate()
        progress = len(fans) + extendededges
        if progress < minimumprogress:
            raise RuntimeError(
                "fan collection made insufficient deterministic progress: "
                f"progress={progress}, required={minimumprogress}"
            )
        fans.compatible(coloring)
        return fans


class Spectrum:
    """Deterministic paper spectrum strategy."""

    @classmethod
    def blocks(
        cls, palette: int, eta: int
    ) -> tuple[tuple[frozenset[Color], ...], tuple[frozenset[Color], ...]]:
        """Return the paper's ordered ``C_i`` blocks and paired ``𝒞_k`` blocks."""
        if not isinstance(palette, int) or isinstance(palette, bool):
            raise ValueError("palette must be an integer")
        if palette <= 0:
            raise ValueError("palette must be positive")
        if not isinstance(eta, int) or isinstance(eta, bool) or eta < 10:
            raise ValueError("eta must be an integer at least 10")
        if palette < 10 * eta:
            raise ValueError("palette must be at least 10*eta")
        width = palette // (2 * eta)
        blocks = tuple(
            frozenset(range(index * width, (index + 1) * width))
            for index in range(2 * eta)
        )
        pairs = tuple(
            blocks[index] | blocks[index + 1] for index in range(0, 2 * eta, 2)
        )
        return blocks, pairs

    @classmethod
    def classify(
        cls,
        coloring: Partial,
        uncolorededges: set[Edge],
        eta: int,
    ) -> Certificate:
        """Build the paper's diagonal type-sparsification certificate.

        ``uncolorededges`` must be a matching, and the palette must divide into
        ``eta`` equal blocks.  No edge is recolored by this function.  That
        separation is intentional: the paper's ``Sparsify-Types`` procedure is a
        sequence of certified alternating-path operations, so a caller must not
        treat classification as if it had achieved the theorem's progress.

        The returned matrix counts an edge once for every feasible ordered pair of
        missing endpoint colors.  Its diagonal survivor set is therefore exactly
        the set of uncolored edges whose type belongs to
        ``union_k (C_k x C_k)``.  All iteration and tie handling is deterministic.
        """
        if not isinstance(eta, int) or isinstance(eta, bool) or eta <= 0:
            raise ValueError("eta must be a positive integer")
        if coloring.palette % eta:
            raise ValueError("palette must be divisible by eta")

        graphedges = set(coloring.graph.edges())
        normalized = {canonical(*edge) for edge in uncolorededges}
        if normalized != uncolorededges:
            raise ValueError("uncolorededges must contain canonical edges")
        if not normalized <= graphedges:
            raise ValueError("uncolorededges must be edges of the graph")
        if normalized & coloring.edges():
            raise ValueError("uncolorededges must not contain colored edges")

        endpoints: dict[Vertex, Edge] = {}
        for edge in sorted(normalized):
            for vertex in edge:
                if vertex in endpoints:
                    raise ValueError("uncolorededges must form a matching")
                endpoints[vertex] = edge

        width = coloring.palette // eta
        blocks = tuple(
            frozenset(range(index * width, (index + 1) * width)) for index in range(eta)
        )
        colorblock = {
            color: index for index, block in enumerate(blocks) for color in block
        }
        counts = [[0 for ignored in range(eta)] for ignored in range(eta)]
        types: dict[Edge, frozenset[tuple[Color, Color]]] = {}
        diagonal: set[Edge] = set()
        for edge in sorted(normalized):
            leftmissing = coloring.missing(edge[0])
            rightmissing = coloring.missing(edge[1])
            if not leftmissing or not rightmissing:
                raise RuntimeError(
                    f"uncolored edge has no missing endpoint color: {edge}"
                )
            feasible = frozenset(
                (leftcolor, rightcolor)
                for leftcolor in leftmissing
                for rightcolor in rightmissing
            )
            types[edge] = feasible
            for leftcolor, rightcolor in sorted(feasible):
                leftblock = colorblock[leftcolor]
                rightblock = colorblock[rightcolor]
                counts[leftblock][rightblock] += 1
                if leftblock == rightblock:
                    diagonal.add(edge)

        return Certificate(
            blocks=blocks,
            types=types,
            diagonal=frozenset(diagonal),
            counts=tuple(tuple(row) for row in counts),
        )

    @classmethod
    def index(cls, blocks: tuple[frozenset[Color], ...], color: Color) -> int:
        """Return the block containing a color, raising ValueError if none does."""
        for index, block in enumerate(blocks):
            if color in block:
                return index
        raise ValueError(f"color {color} is outside the amplified color range")

    @classmethod
    def order(cls, fan: Fan) -> tuple[int, int, int, int, int, int]:
        """Return the canonical order used for deterministic fan batches."""
        return (
            fan.center,
            fan.first,
            fan.second,
            fan.alpha,
            fan.beta,
            fan.gamma,
        )

    @classmethod
    def kind(cls, fan: Fan, blocks: tuple[frozenset[Color], ...]) -> tuple[int, int]:
        """Return the canonical pair of partition blocks containing a fan type."""
        centerblock = cls.index(blocks, fan.alpha)
        leafblock = cls.index(blocks, fan.beta)
        return min(centerblock, leafblock), max(centerblock, leafblock)

    @classmethod
    def offset(
        cls, blocks: tuple[frozenset[Color], ...], blockindex: int, color: Color
    ) -> Color:
        """Return the color at the same offset in the requested target block."""
        source = blocks[cls.index(blocks, color)]
        offset = color - min(source)
        target = sorted(blocks[blockindex])
        return target[offset]

    @classmethod
    def social(cls, fan: Fan, blocks: tuple[frozenset[Color], ...]) -> bool:
        """Return whether a fan is uniform or aligned in the paper partition."""
        centerblock = cls.index(blocks, fan.alpha)
        leafblock = cls.index(blocks, fan.beta)
        if centerblock == leafblock:
            return True
        return centerblock // 2 == leafblock // 2

    @classmethod
    def damages(
        cls,
        fan: Fan,
        paths: tuple[tuple[tuple[Vertex, ...], Color, Color], ...],
        social: set[Fan],
    ) -> bool:
        """Return whether flipping ``paths`` can damage an existing social fan."""
        for pathvertices, source, target in paths:
            edges = {canonical(left, right) for left, right in pairwise(pathvertices)}
            endpoints = (pathvertices[0], pathvertices[-1])
            for other in social:
                if other is fan:
                    continue
                # ModifyB flips every colored edge on each relevant path.  A
                # protected fan is damaged if one of its spokes is on that path,
                # even when neither path endpoint is a fan vertex.  Endpoint-only
                # checks are insufficient because alternating paths may cross a
                # fan edge in their interior.
                if edges & other.edges:
                    return True
                if any(
                    endpoint in other.vertices
                    and other.color(endpoint) in {source, target}
                    for endpoint in endpoints
                ):
                    return True
        return False

    @classmethod
    def paths(
        cls,
        coloring: Partial,
        fan: Fan,
        blocks: tuple[frozenset[Color], ...],
        pairindex: int,
    ) -> tuple[tuple[tuple[Vertex, ...], Color, Color], ...]:
        """Compute the paper's three pair-index-relevant alternating paths."""
        if cls.social(fan, blocks):
            raise ValueError("relevant paths require a non-social fan")
        centerblock = cls.index(blocks, fan.alpha)
        leafblock = cls.index(blocks, fan.beta)
        leftblock = 2 * pairindex
        rightblock = leftblock + 1
        if centerblock == rightblock or leafblock == leftblock:
            leftblock, rightblock = rightblock, leftblock

        def path(
            start: Vertex, source: Color, targetblock: int
        ) -> tuple[tuple[Vertex, ...], Color, Color]:
            """Materialize the alternating path to the target block's offset color."""
            target = cls.offset(blocks, targetblock, source)
            if source == target:
                return (start,), source, target
            return tuple(coloring.path(start, source, target)), source, target

        return (
            path(fan.center, fan.alpha, leftblock),
            path(fan.first, fan.beta, rightblock),
            path(fan.second, fan.gamma, rightblock),
        )

    @classmethod
    def modify(
        cls,
        coloring: Partial,
        fans: Fans,
        batch: tuple[Fan, ...],
        blocks: tuple[frozenset[Color], ...],
        pairindex: int,
        parentjournal: ColorJournal | None = None,
    ) -> None:
        """Apply one ``Modify-Types`` batch atomically."""
        coloring.validate()
        fans.validate()
        fans.compatible(coloring)
        colorjournal = ColorJournal(coloring, parentjournal)
        fansbefore: set[Fan] | None = None
        affectedvertices: set[Vertex] = set()
        try:
            coloring.validate()
            fans.validate()
            fans.compatible(coloring)
            if not batch:
                raise ValueError("Modify-Types requires a non-empty fan batch")
            if any(fan not in fans.members for fan in batch):
                raise ValueError("Modify-Types batch must belong to the fan collection")
            if len(set(batch)) != len(batch):
                raise ValueError("Modify-Types batch must not contain duplicate fans")
            batchblocktypes = {
                tuple(
                    sorted(
                        {
                            cls.index(blocks, fan.alpha),
                            cls.index(blocks, fan.beta),
                        }
                    )
                )
                for fan in batch
            }
            if len(batchblocktypes) != 1:
                raise ValueError("Modify-Types batch must contain one fan block type")

            fanpaths: dict[Fan, tuple[tuple[tuple[Vertex, ...], Color, Color], ...]] = {
                fan: cls.paths(coloring, fan, blocks, pairindex) for fan in batch
            }
            for fan in batch:
                affectedvertices.update(fan.vertices)
            changededges: set[Edge] = set()
            for paths in fanpaths.values():
                for path, _, _ in paths:
                    changededges.update(
                        canonical(left, right) for left, right in pairwise(path)
                    )
                    if path:
                        affectedvertices.add(path[0])
                        affectedvertices.add(path[-1])
            colorjournal.capture(changededges)
            fansbefore = {
                member
                for vertex in affectedvertices
                for member in fans.vertices.get(vertex, ())
            }
            coloredcount = len(coloring.assignments)
            for fan in batch:
                # Keep selected fans out of the index while their three paths are
                # being flipped; otherwise endpoint repair can create an intermediate
                # fan with the same spokes.
                fans.discard(fan)

            uniquepaths: list[tuple[tuple[Vertex, ...], Color, Color]] = []
            seenedges: set[Edge] = set()
            for path, source, targetcolor in (
                path for paths in fanpaths.values() for path in paths
            ):
                edges = {canonical(left, right) for left, right in pairwise(path)}
                if edges and edges <= seenedges:
                    continue
                if edges & seenedges:
                    raise RuntimeError(
                        "Modify-Types produced overlapping relevant paths"
                    )
                seenedges.update(edges)
                uniquepaths.append((path, source, targetcolor))
            for path, source, targetcolor in uniquepaths:
                fans.flip(coloring, list(path), source, targetcolor)

            for fan in tuple(fans):
                if any(
                    fan.color(vertex) not in coloring.missing(vertex)
                    for vertex in fan.vertices
                ):
                    fans.discard(fan)

            for fan, paths in fanpaths.items():
                fans.add(
                    Fan(
                        fan.center,
                        fan.first,
                        fan.second,
                        paths[0][2],
                        paths[1][2],
                        paths[2][2],
                    )
                )
            coloring.validate()
            fans.validate()
            fans.compatible(coloring)
            if len(coloring.assignments) != coloredcount:
                raise RuntimeError("Modify-Types changed the set of colored edges")
        except Exception:
            colorjournal.rollback()
            if fansbefore is not None:
                Vizing.restore(fans, fansbefore, affectedvertices)
            coloring.validate()
            fans.validate()
            fans.compatible(coloring)
            raise

    @classmethod
    def sparsify(
        cls, coloring: Partial, fans: Fans, eta: int
    ) -> tuple[tuple[frozenset[Color], ...], Fans]:
        """Run ``Sparsify-Types`` atomically over the coloring and fan index."""
        fanroots = (
            fans.members,
            fans.spokes,
            fans.assignments,
            fans.assigned,
            fans.vertices,
            fans.types,
        )
        coloringroots = coloring.incident, coloring.index
        colorjournal = ColorJournal(coloring)
        relabeled = False
        fansrelabeled = False
        inverse: dict[Color, Color] = {}
        try:
            if not isinstance(eta, int) or isinstance(eta, bool) or eta < 10:
                raise ValueError("eta must be an integer at least 10")
            if coloring.palette < 10 * eta:
                raise ValueError("palette must be at least 10*eta")
            coloring.validate()
            fans.validate()
            fans.compatible(coloring)
            coloredcount = len(coloring.assignments)
            initial = len(fans)
            if initial == 0:
                raise ValueError("sparsify_types requires at least one u-fan")
            counts = {color: 0 for color in range(coloring.palette)}
            for fan in fans:
                for color in fan.type:
                    counts[color] += 1
            order = sorted(counts, key=lambda color: (-counts[color], color))
            mapping = {old: new for new, old in enumerate(order)}
            inverse = {new: old for old, new in mapping.items()}
            coloring.relabel(mapping)
            relabeled = True
            fans.relabel(mapping)
            fansrelabeled = True
            blocks, pairs = cls.blocks(coloring.palette, eta)
            for fan in tuple(fans):
                try:
                    for color in fan.type:
                        cls.index(blocks, color)
                except ValueError:
                    fans.discard(fan)

            retained = len(fans)
            minimumretained = (3 * initial + 4) // 5
            if retained < minimumretained:
                raise RuntimeError(
                    "Sparsify-Types preprocessing discarded too many u-fans: "
                    f"retained={retained}, required={minimumretained}, "
                    f"initial={initial}"
                )

            # The paper's constant-fraction bound is integral in the implementation:
            # every non-empty input must retain at least one social fan.
            target = max(1, (initial + 99) // 100)
            social = {fan for fan in fans if cls.social(fan, blocks)}
            iterations = 0
            # The ABB+26 analysis bounds Algorithm 4 by O(eta^2) iterations.  Keep
            # that proof-derived bound explicit so a malformed path/index transition
            # cannot turn the implementation into an unbounded fan-count scan.
            maxiterations = max(1, eta**2)
            while len(social) < target:
                iterations += 1
                if iterations > maxiterations:
                    raise RuntimeError(
                        "Sparsify-Types exceeded its deterministic iteration bound "
                        "without "
                        "reaching the required social-fan mass"
                    )
                # ModifyB replaces each transformed fan with a new fan whose type can
                # move to a different block pair.  Rebuild U_{i,i'} from the current
                # collection on every iteration; retaining the previous index would
                # select batches using stale fan objects after the first transformation.
                byblocktype: dict[tuple[int, int], set[Fan]] = {}
                for fan in fans:
                    byblocktype.setdefault(cls.kind(fan, blocks), set()).add(fan)
                pairindex = min(
                    range(len(pairs)),
                    key=lambda index: (
                        len(
                            byblocktype.get((2 * index, 2 * index + 1), set())
                            | byblocktype.get((2 * index, 2 * index), set())
                            | byblocktype.get((2 * index + 1, 2 * index + 1), set())
                        ),
                        index,
                    ),
                )
                # This is the paper's B_k filter: a non-social fan is k-bad exactly
                # when one of its k-relevant paths would damage an already social fan.
                bad: set[Fan] = set()
                for fan in fans:
                    if cls.social(fan, blocks):
                        continue
                    try:
                        paths = cls.paths(coloring, fan, blocks, pairindex)
                    except ValueError as error:
                        raise RuntimeError(
                            "Sparsify-Types could not construct relevant paths for a "
                            f"non-social u-fan: {fan}"
                        ) from error
                    if cls.damages(fan, paths, social):
                        bad.add(fan)
                        continue
                goodbytype = {
                    key: group - bad
                    for key, group in byblocktype.items()
                    if key[0] < key[1] and group - bad
                }
                if not goodbytype:
                    raise RuntimeError(
                        "Sparsify-Types could not find a good fan for the "
                        "selected color pair"
                    )
                batchkey = max(
                    goodbytype,
                    key=lambda key: (len(goodbytype[key]), -key[0], -key[1]),
                )
                batch = tuple(sorted(goodbytype[batchkey], key=cls.order))
                socialbefore = len(social)
                cls.modify(coloring, fans, batch, blocks, pairindex, colorjournal)
                social = {fan for fan in fans if cls.social(fan, blocks)}
                if len(social) <= socialbefore:
                    raise RuntimeError("Sparsify-Types made no social-fan progress")
            result = Fans()
            for fan in social:
                result.add(fan)
            if len(result) < target:
                raise RuntimeError(
                    "Sparsify-Types returned fewer social fans than its "
                    "constant-fraction "
                    f"bound: retained={len(result)}, required={target}"
                )
            if any(not cls.social(fan, blocks) for fan in result):
                raise RuntimeError("Sparsify-Types returned a non-social u-fan")
            if any(len(group) > coloring.palette // eta for group in pairs):
                raise RuntimeError("Sparsify-Types returned an oversized color group")
            if len(coloring.assignments) != coloredcount:
                raise RuntimeError("Sparsify-Types changed the colored edge count")
            # Amplify terminates with U := U_hat.  Keep the caller's working
            # collection synchronized with the returned social collection so a
            # subsequent recursive step cannot accidentally process stale
            # non-social fans.
            for fan in tuple(fans):
                fans.discard(fan)
            for fan in result:
                fans.add(fan)
            fans.compatible(coloring)
            return pairs, result
        except Exception:
            colorjournal.rollback()
            if relabeled:
                coloring.relabel(inverse)
                coloring.incident, coloring.index = coloringroots
            if fansrelabeled:
                (
                    fans.members,
                    fans.spokes,
                    fans.assignments,
                    fans.assigned,
                    fans.vertices,
                    fans.types,
                ) = fanroots
            coloring.validate()
            fans.validate()
            fans.compatible(coloring)
            raise


class Extension:
    """Deterministic paper extension strategy."""

    construction: type[Construction] = Construction
    spectrum: type[Spectrum] = Spectrum

    @classmethod
    def project(
        cls,
        coloring: Partial,
        fans: Fans,
        colorgroup: frozenset[Color],
    ) -> tuple[Partial, Fans, set[Edge], tuple[Color, ...]]:
        """Project one paper ``Extend`` subproblem onto local color numbers.

        The edge scope is exactly the colored edges in ``colorgroup`` plus the
        spokes of fans whose complete type belongs to that group. Combined
        with disjoint groups and a compatible, edge-disjoint fan collection,
        this contract makes sibling recursive edge scopes disjoint.
        """
        ordered = tuple(sorted(colorgroup))
        tolocal = {color: index for index, color in enumerate(ordered)}
        edgescope = {edge for edge, color in coloring.items() if color in colorgroup}
        selectedfans = [fan for fan in fans if fan.type <= colorgroup]
        for fan in selectedfans:
            edgescope.update(fan.edges)
        degree: dict[Vertex, int] = {}
        for left, right in edgescope:
            degree[left] = degree.get(left, 0) + 1
            degree[right] = degree.get(right, 0) + 1
        maximumdegree = max(degree.values(), default=0)
        if maximumdegree > len(ordered):
            raise RuntimeError(
                "Extend projected an infeasible subproblem: "
                f"maximum degree {maximumdegree} exceeds palette size {len(ordered)}"
            )
        # E_k is an actual edge-disjoint subproblem in ABB's Extend.  Give the
        # child its own graph snapshot so later path operations cannot
        # accidentally observe or mutate edges outside this color group.
        childgraph = (
            Packed(coloring.graph.n)
            if isinstance(coloring.graph, Adjacency)
            else empty(coloring.graph)
        )
        for edge in sorted(edgescope):
            childgraph.add_edge(*edge)
        child = Partial(childgraph, len(ordered))
        for edge in edgescope:
            if edge in coloring:
                color = coloring[edge]
                if color not in tolocal:
                    raise RuntimeError("subproblem projection crossed a color group")
                child.assignments[edge] = tolocal[color]
        child.reindex()
        child.validate()
        childfans = Fans()
        for fan in selectedfans:
            childfans.add(
                Fan(
                    fan.center,
                    fan.first,
                    fan.second,
                    tolocal[fan.alpha],
                    tolocal[fan.beta],
                    tolocal[fan.gamma],
                )
            )
        return child, childfans, edgescope, ordered

    @classmethod
    def merge(
        cls,
        parent: Partial,
        child: Partial,
        edgescope: set[Edge],
        localcolors: tuple[Color, ...],
    ) -> None:
        """Merge a completed isolated subproblem into its parent coloring."""
        for edge in edgescope:
            if edge not in child:
                continue
            local = child[edge]
            if not 0 <= local < len(localcolors):
                raise RuntimeError("subproblem returned an invalid local color")
            parent.assignments[edge] = localcolors[local]
        parent.reindex()
        parent.validate()

    @classmethod
    def extend(cls, coloring: Partial, fans: Fans, eta: int) -> int:
        """Recursively execute the paper's ``Extend`` decomposition.

        ``Sparsify-Types`` supplies disjoint color groups and social fans.
        Each group is
        projected to local color numbers, processed independently, and merged back
        only after its properness has been validated.  If amplification cannot
        produce a valid recursive split, this function raises an explicit
        diagnostic error.
        """
        coloring.validate()
        fans.validate()
        fans.compatible(coloring)
        if not fans:
            return 0
        coloredbefore = len(coloring.assignments)
        if coloring.palette <= 10 * eta:
            return cls.construction.small(coloring, fans)

        groups, social = cls.spectrum.sparsify(coloring, fans, eta)
        if not social:
            raise RuntimeError("Extend received no social fans after Sparsify-Types")
        total = 0
        assignedcolors: set[Color] = set()
        for group in groups:
            if any(color in assignedcolors for color in group):
                raise RuntimeError("Extend received overlapping color groups")
            assignedcolors.update(group)
        for group in groups:
            selected = [fan for fan in social if fan.type <= group]
            if not selected:
                continue
            child, childfans, edgescope, localcolors = cls.project(
                coloring, social, group
            )
            # The color groups are disjoint, so a colored edge can enter only
            # its one color group. Every fan type has two distinct colors and
            # can belong to at most one group; Fans.compatible guarantees its
            # uncolored spokes are pairwise disjoint and not colored. Therefore
            # these edge scopes are disjoint without retaining every prior
            # child edge in a second O(m) set.
            total += cls.extend(child, childfans, eta)
            cls.merge(coloring, child, edgescope, localcolors)
            # The child owns the authoritative fan state for this edge-disjoint
            # subproblem.  Propagate surviving fans back to the parent palette;
            # child activation may have removed a fan or changed its assigned
            # missing colors, and retaining the pre-recursion parent object would
            # make the caller's separable collection stale.
            for fan in selected:
                social.discard(fan)
            for fan in childfans:
                social.add(
                    Fan(
                        fan.center,
                        fan.first,
                        fan.second,
                        localcolors[fan.alpha],
                        localcolors[fan.beta],
                        localcolors[fan.gamma],
                    )
                )
        coloring.validate()
        # Keep both the returned collection and the caller-owned collection
        # synchronized after all recursive child merges.  A child may have
        # colored a spoke or invalidated a missing-color assignment in a sibling
        # fan, so validate the complete parent state before exposing it.
        for fan in tuple(fans):
            fans.discard(fan)
        for fan in social:
            fans.add(fan)
        fans.repair(coloring)
        fans.compatible(coloring)
        coloredafter = len(coloring.assignments)
        if total <= 0 or coloredafter <= coloredbefore:
            raise RuntimeError(
                "Extend made no coloring progress for a non-empty fan collection"
            )
        return total


class Paper:
    """Deterministic complete coloring through paper u-fan operations.

    This implementation uses the paper's explicit fan-shift and activation
    interface followed by deterministic Vizing fan reduction.  It
    intentionally has no Vizing/greedy fallback: if a fan invariant cannot
    be maintained, it raises a diagnostic error.  The complete ABB+26
    near-linear construction and bound remain separate release gates.
    """

    construction: type[Construction] = Construction
    vizing: type[Vizing] = Vizing
    extension: type[Extension] = Extension

    @classmethod
    def color(cls, graph: Graph, delta: int) -> dict[Edge, Color]:
        """Return a certified complete coloring with at most delta + 1 colors.

        Args:
            graph: The simple graph to color.
            delta: A non-negative integer bounding the maximum degree.

        Returns:
            A mapping from canonical graph edges to colors in 0..delta.

        Raises:
            ValueError: If delta is invalid or smaller than the maximum degree.
            RuntimeError: If a paper operation cannot maintain its invariants.
        """
        if not isinstance(delta, int) or isinstance(delta, bool) or delta < 0:
            raise ValueError("delta must be a non-negative integer")
        maximum = max((graph.degree(vertex) for vertex in range(graph.n)), default=0)
        if maximum > delta:
            raise ValueError(f"delta={delta} is smaller than maximum degree {maximum}")
        alledges = set(graph.edges())
        if delta >= 32 and alledges:
            result = cls.seed(graph, delta)
        else:
            start = Partial(graph, delta + 1)
            result = cls.complete(start, alledges, delta)
        cls.certify(graph, delta, alledges, result)
        return result

    @classmethod
    def certify(
        cls, graph: Graph, delta: int, alledges: set[Edge], coloring: dict[Edge, Color]
    ) -> None:
        """Certify a public colorer result before returning it to callers."""
        if set(coloring) != alledges:
            raise RuntimeError("paper colorer returned an incomplete edge coloring")
        certificate = Partial(graph, delta + 1)
        for edge, color in sorted(coloring.items()):
            certificate.assign(edge, color)
        certificate.validate()

    @classmethod
    def complete(
        cls, start: Partial, alledges: set[Edge], delta: int
    ) -> dict[Edge, Color]:
        """Complete a partial coloring through Extend and deterministic fan chains."""
        separablefans = cls.construction.collect(start, alledges - start.edges())
        if separablefans:
            eta = cls.regime(delta, start.palette)
            if eta is None:
                cls.construction.small(start, separablefans)
            else:
                cls.extension.extend(start, separablefans, eta)
            start.validate()
        pending = sorted(alledges - start.edges())
        for edge in pending:
            if edge not in start:
                cls.vizing.color(start, edge, batch=True)
        if start.assignments.keys() != alledges:
            raise RuntimeError("Vizing activation/reduction left edges uncolored")
        start.validate()
        return dict(start.items())

    @classmethod
    def regime(cls, delta: int, palette: int) -> int | None:
        """Return the ABB+26 ``eta`` parameter when recursive Extend applies.

        The type-sparsification construction requires ``10 <= eta <= mu/10``
        for a ``mu``-coloring.  Below that threshold the paper uses its
        ``Color-Small`` base case instead of forcing an invalid block partition.
        """
        if delta < 2 or palette < 100:
            return None
        eta = 10 * max(1, math.ceil(2 ** math.sqrt(math.log2(delta))))
        if eta > palette // 10:
            return None
        return eta

    @classmethod
    def partition(cls, graph: Graph) -> tuple[Graph, Graph]:
        """Split edges into two balanced Euler-tour parity subgraphs.

        Odd-degree vertices are paired with deterministic auxiliary edges.  An
        Euler circuit in each augmented component is alternated, then auxiliary
        edges are discarded.  Every original vertex therefore receives the two
        subgraph degrees differing by at most one, which is the recursive ABB
        partition invariant.
        """
        originaledges = sorted(graph.edges())
        components: list[set[Vertex]] = []
        unseen = set(range(graph.n))
        while unseen:
            root = min(unseen)
            component: set[Vertex] = set()
            visitstack = [root]
            unseen.remove(root)
            while visitstack:
                vertex = visitstack.pop()
                component.add(vertex)
                for neighbor in graph.neighbors(vertex):
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        visitstack.append(neighbor)
            if any(graph.degree(vertex) for vertex in component):
                components.append(component)

        augmented: list[tuple[Vertex, Vertex, int | None]] = [
            (left, right, index) for index, (left, right) in enumerate(originaledges)
        ]
        nextauxiliary = graph.n
        for component in components:
            odd = sorted(vertex for vertex in component if graph.degree(vertex) % 2)
            if len(odd) % 2:
                raise RuntimeError(
                    "Euler partition found an odd number of odd vertices"
                )
            if odd:
                dummy = nextauxiliary
                nextauxiliary += 1
                augmented.extend((vertex, dummy, None) for vertex in odd)
                augmentededges = sum(graph.degree(vertex) for vertex in component) // 2
                augmentededges += len(odd)
                if augmentededges % 2:
                    # The loop is incident only to the auxiliary vertex, so it
                    # changes the circuit parity without affecting any original
                    # vertex's partition degree.
                    augmented.append((dummy, dummy, None))

        incident: dict[Vertex, list[tuple[int, Vertex]]] = {}
        for edgeid, endpoints in enumerate(augmented):
            left, right = endpoints[:2]
            incident.setdefault(left, []).append((edgeid, right))
            incident.setdefault(right, []).append((edgeid, left))
        for vertex in incident:
            incident[vertex].sort(reverse=True)

        partition: dict[int, int] = {}
        used: set[int] = set()
        for component in components:
            root = min(component)
            trailstack: list[tuple[Vertex, int | None]] = [(root, None)]
            circuit: list[int] = []
            while trailstack:
                vertex, incoming = trailstack[-1]
                while incident[vertex] and incident[vertex][-1][0] in used:
                    incident[vertex].pop()
                if incident[vertex]:
                    edgeid, neighbor = incident[vertex].pop()
                    if edgeid in used:
                        continue
                    used.add(edgeid)
                    trailstack.append((neighbor, edgeid))
                else:
                    trailstack.pop()
                    if incoming is not None:
                        circuit.append(incoming)
            for position, edgeid in enumerate(reversed(circuit)):
                originalindex = augmented[edgeid][2]
                if originalindex is not None:
                    partition[originalindex] = position % 2

        if len(partition) != len(originaledges):
            raise RuntimeError("Euler partition did not assign every graph edge")
        parts = (empty(graph), empty(graph))
        for index, edge in enumerate(originaledges):
            parts[partition[index]].add_edge(*edge)
        maximum = max((graph.degree(vertex) for vertex in range(graph.n)), default=0)
        # An odd Euler circuit can leave one vertex with one extra edge in a
        # subgraph.  The recursive construction therefore uses the standard
        # ``ceil((Delta + 1) / 2)`` bound, not ``floor((Delta + 1) / 2)``.
        bound = (maximum + 2) // 2
        if any(
            part.degree(vertex) > bound for part in parts for vertex in range(graph.n)
        ):
            raise RuntimeError("Euler partition violated the balanced-degree bound")
        return parts

    @classmethod
    def seed(cls, graph: Graph, delta: int) -> dict[Edge, Color]:
        """Build the ABB recursive seed, then reduce and extend its palette."""
        if delta < 32:
            start = Partial(graph, delta + 1)
            return cls.complete(start, set(graph.edges()), delta)
        left, right = cls.partition(graph)
        leftdelta = max((left.degree(vertex) for vertex in range(graph.n)), default=0)
        rightdelta = max((right.degree(vertex) for vertex in range(graph.n)), default=0)
        leftcoloring = cls.seed(left, leftdelta) if left.num_edges() else {}
        rightcoloring = cls.seed(right, rightdelta) if right.num_edges() else {}
        leftpalette = leftdelta + 1
        combined: dict[Edge, Color] = dict(leftcoloring)
        combined.update(
            {edge: color + leftpalette for edge, color in rightcoloring.items()}
        )
        palettesize = leftpalette + rightdelta + 1
        if palettesize <= delta + 1:
            remap = {
                color: index
                for index, color in enumerate(sorted(set(combined.values())))
            }
            return {edge: remap[color] for edge, color in combined.items()}

        counts = {
            color: sum(1 for edgecolor in combined.values() if edgecolor == color)
            for color in range(palettesize)
        }
        removed = {
            color
            for color, ignored in sorted(
                counts.items(), key=lambda item: (item[1], item[0])
            )[:2]
        }
        retained = {
            edge: color for edge, color in combined.items() if color not in removed
        }
        remap = {
            color: index
            for index, color in enumerate(
                sorted({color for color in retained.values()})
            )
        }
        start = Partial(graph, delta + 1)
        for edge, color in sorted(retained.items()):
            start.assign(edge, remap[color])
        return cls.complete(start, set(graph.edges()), delta)
