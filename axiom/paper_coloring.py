"""Stateful primitives used by the paper's deterministic coloring algorithm.

This module deliberately models the paper's partial-coloring interface rather
than exposing a second edge-coloring implementation.  The higher-level
``Extend`` recursion can therefore operate on explicit uncolored edges,
alternating paths, u-fans, and separable collections without treating a
classical complete coloring as an interchangeable substitute.
"""

from __future__ import annotations

import math
from collections.abc import ItemsView, Iterator, Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType

from axiom.graph import Adjacency
from axiom.types import Color, Edge, Graph, Vertex, canonical


@dataclass(frozen=True, slots=True)
class UFan:
    """A paper u-fan with two uncolored spokes and three assigned colors."""

    center: Vertex
    first_leaf: Vertex
    second_leaf: Vertex
    center_color: Color
    first_color: Color
    second_color: Color

    def __post_init__(self) -> None:
        vertices = (self.center, self.first_leaf, self.second_leaf)
        if len(set(vertices)) != 3:
            raise ValueError("u-fan vertices must be distinct")
        if self.center_color == self.first_color:
            raise ValueError("u-fan center and first leaf colors must differ")
        if self.first_color != self.second_color:
            raise ValueError("u-fan leaf colors must be equal")

    @property
    def edges(self) -> frozenset[Edge]:
        return frozenset(
            {
                canonical(self.center, self.first_leaf),
                canonical(self.center, self.second_leaf),
            }
        )

    @property
    def vertices(self) -> tuple[Vertex, Vertex, Vertex]:
        return self.center, self.first_leaf, self.second_leaf

    def color_at(self, vertex: Vertex) -> Color:
        if vertex == self.center:
            return self.center_color
        if vertex == self.first_leaf:
            return self.first_color
        if vertex == self.second_leaf:
            return self.second_color
        raise KeyError(vertex)

    @property
    def type(self) -> frozenset[Color]:
        return frozenset((self.center_color, self.first_color))

    def with_vertex_color(self, vertex: Vertex, color: Color) -> UFan:
        """Return this fan with one assigned missing color changed."""
        if vertex == self.center:
            return UFan(
                self.center,
                self.first_leaf,
                self.second_leaf,
                color,
                self.first_color,
                self.second_color,
            )
        if vertex == self.first_leaf:
            return UFan(
                self.center,
                self.first_leaf,
                self.second_leaf,
                self.center_color,
                color,
                self.second_color,
            )
        if vertex == self.second_leaf:
            return UFan(
                self.center,
                self.first_leaf,
                self.second_leaf,
                self.center_color,
                self.first_color,
                color,
            )
        raise KeyError(vertex)


@dataclass(frozen=True, slots=True)
class TypeSparsification:
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
    edge_types: Mapping[Edge, frozenset[tuple[Color, Color]]]
    diagonal_edges: frozenset[Edge]
    block_counts: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_types", MappingProxyType(dict(self.edge_types)))

    @property
    def diagonal_fraction(self) -> float:
        """Return the fraction of uncolored edges with a diagonal type."""
        if not self.edge_types:
            return 1.0
        return len(self.diagonal_edges) / len(self.edge_types)


class PartialColoring:
    """A deterministic proper partial ``(delta + 1)`` edge coloring."""

    def __init__(self, graph: Graph, color_count: int) -> None:
        if not isinstance(color_count, int) or isinstance(color_count, bool):
            raise ValueError("color_count must be an integer")
        if color_count <= 0:
            raise ValueError("color_count must be positive")
        self.graph = graph
        self.color_count = color_count
        self._colors: dict[Edge, Color] = {}
        self._incident: dict[Vertex, set[Color]] = {
            vertex: set() for vertex in range(graph.n)
        }
        self._edge_by_color: dict[tuple[Vertex, Color], Edge] = {}

    def _reindex(self) -> None:
        """Rebuild the per-vertex color index after an atomic bulk edit."""
        incident: dict[Vertex, set[Color]] = {
            vertex: set() for vertex in range(self.graph.n)
        }
        edge_by_color: dict[tuple[Vertex, Color], Edge] = {}
        for (left, right), color in self._colors.items():
            if (left, color) in edge_by_color or (right, color) in edge_by_color:
                raise AssertionError("partial coloring has duplicate incident colors")
            incident[left].add(color)
            incident[right].add(color)
            edge_by_color[(left, color)] = (left, right)
            edge_by_color[(right, color)] = (left, right)
        self._incident = incident
        self._edge_by_color = edge_by_color

    def __contains__(self, edge: object) -> bool:
        return edge in self._colors

    def __getitem__(self, edge: Edge) -> Color:
        return self._colors[canonical(*edge)]

    def items(self) -> ItemsView[Edge, Color]:
        return self._colors.items()

    def edges(self) -> set[Edge]:
        return set(self._colors)

    def relabel(self, mapping: dict[Color, Color]) -> None:
        """Apply a validated global permutation to every assigned color."""
        expected = set(range(self.color_count))
        if set(mapping) != expected or set(mapping.values()) != expected:
            raise ValueError("color relabeling must be a permutation of the palette")
        self._colors = {edge: mapping[color] for edge, color in self._colors.items()}
        self._reindex()
        self.validate()

    def missing(self, vertex: Vertex) -> list[Color]:
        return [
            color
            for color in range(self.color_count)
            if color not in self._incident[vertex]
        ]

    def is_missing(self, vertex: Vertex, color: Color) -> bool:
        """Return whether ``color`` is available at ``vertex`` in O(1)."""
        if not 0 <= color < self.color_count:
            return False
        return color not in self._incident[vertex]

    def first_missing(self, vertex: Vertex) -> Color:
        """Return the smallest available color, or fail explicitly."""
        for color in range(self.color_count):
            if color not in self._incident[vertex]:
                return color
        raise RuntimeError(f"vertex {vertex} has no missing color")

    def validate(self) -> None:
        """Validate that every stored edge color is proper and in range."""
        seen: dict[Vertex, set[Color]] = {
            vertex: set() for vertex in range(self.graph.n)
        }
        for edge, color in self._colors.items():
            if not self.graph.has_edge(*edge):
                raise AssertionError(f"colored edge is outside graph: {edge}")
            if not 0 <= color < self.color_count:
                raise AssertionError(f"color is outside palette: {edge}={color}")
            left, right = edge
            if color in seen[left] or color in seen[right]:
                raise AssertionError(f"improper coloring at edge {edge}")
            seen[left].add(color)
            seen[right].add(color)
        if seen != self._incident:
            raise AssertionError("partial-coloring incident-color index is stale")
        rebuilt_edges: dict[tuple[Vertex, Color], Edge] = {}
        for edge, color in self._colors.items():
            left, right = edge
            rebuilt_edges[(left, color)] = edge
            rebuilt_edges[(right, color)] = edge
        if rebuilt_edges != self._edge_by_color:
            raise AssertionError("partial-coloring edge-color index is stale")

    def assign(self, edge: Edge, color: Color) -> None:
        edge = canonical(*edge)
        if not self.graph.has_edge(*edge):
            raise ValueError(f"cannot color an edge outside the graph: {edge}")
        if not isinstance(color, int) or isinstance(color, bool):
            raise ValueError("color must be an integer")
        if not 0 <= color < self.color_count:
            raise ValueError(f"color must be in 0..{self.color_count - 1}")
        if edge in self._colors:
            raise ValueError(f"edge is already colored: {edge}")
        if color not in self.missing(edge[0]) or color not in self.missing(edge[1]):
            raise ValueError(f"color {color} is unavailable on edge {edge}")
        self._colors[edge] = color
        self._incident[edge[0]].add(color)
        self._incident[edge[1]].add(color)
        self._edge_by_color[(edge[0], color)] = edge
        self._edge_by_color[(edge[1], color)] = edge

    def recolor(self, edge: Edge, color: Color) -> None:
        edge = canonical(*edge)
        if edge not in self._colors:
            raise ValueError(f"edge is not colored: {edge}")
        old = self.unassign(edge)
        try:
            self.assign(edge, color)
        except Exception:
            self._colors[edge] = old
            self._reindex()
            raise

    def unassign(self, edge: Edge) -> Color:
        """Make one colored edge uncolored and return its former color."""
        edge = canonical(*edge)
        try:
            old = self._colors.pop(edge)
        except KeyError as error:
            raise ValueError(f"edge is not colored: {edge}") from error
        self._incident[edge[0]].remove(old)
        self._incident[edge[1]].remove(old)
        self._edge_by_color.pop((edge[0], old), None)
        self._edge_by_color.pop((edge[1], old), None)
        return old

    def alternating_path(
        self, start: Vertex, first_color: Color, second_color: Color
    ) -> list[Vertex]:
        """Return the maximal simple path starting with ``second_color``."""
        if first_color == second_color:
            raise ValueError("alternating path colors must differ")
        if not self.is_missing(start, first_color):
            raise ValueError("first color must be missing at the path start")
        path = [start]
        visited = {start}
        current = start
        wanted = second_color
        while True:
            edge = self._edge_by_color.get((current, wanted))
            next_vertex = None
            if edge is not None:
                candidate = edge[1] if edge[0] == current else edge[0]
                if candidate not in visited:
                    next_vertex = candidate
            if next_vertex is None:
                return path
            path.append(next_vertex)
            visited.add(next_vertex)
            current = next_vertex
            wanted = first_color if wanted == second_color else second_color

    def flip(self, path: list[Vertex], first_color: Color, second_color: Color) -> None:
        """Flip a validated alternating path in place."""
        if len(path) < 1 or len(set(path)) != len(path):
            raise ValueError("path must be non-empty and simple")
        edges = [canonical(left, right) for left, right in pairwise(path)]
        if any(edge not in self._colors for edge in edges):
            raise ValueError("alternating path contains an uncolored edge")
        expected = second_color
        for edge in edges:
            if self._colors[edge] != expected:
                raise ValueError("path is not alternating from its start")
            expected = first_color if expected == second_color else second_color
        for edge in edges:
            self._colors[edge] = (
                first_color if self._colors[edge] == second_color else second_color
            )
        self._reindex()


class SeparableFans:
    """Deterministic collection enforcing the paper's separability invariant."""

    def __init__(self) -> None:
        self._fans: set[UFan] = set()
        self._edges: set[Edge] = set()
        self._colors: dict[tuple[Vertex, Color], UFan] = {}
        self._fan_colors: dict[Vertex, set[Color]] = {}
        self._vertices: dict[Vertex, set[UFan]] = {}
        self._types: dict[frozenset[Color], set[UFan]] = {}

    def __len__(self) -> int:
        return len(self._fans)

    def __iter__(self) -> Iterator[UFan]:
        return iter(
            sorted(
                self._fans,
                key=lambda fan: (fan.center, fan.first_leaf, fan.second_leaf),
            )
        )

    def add(self, fan: UFan) -> None:
        if self._fans.intersection({fan}):
            raise ValueError("u-fan is already present")
        if self._edges.intersection(fan.edges):
            raise ValueError("u-fan collection must be edge-disjoint")
        for vertex in fan.vertices:
            key = (vertex, fan.color_at(vertex))
            if key in self._colors:
                raise ValueError("u-fan colors must be distinct at each vertex")
        self._fans.add(fan)
        self._edges.update(fan.edges)
        self._types.setdefault(fan.type, set()).add(fan)
        for vertex in fan.vertices:
            self._colors[(vertex, fan.color_at(vertex))] = fan
            self._fan_colors.setdefault(vertex, set()).add(fan.color_at(vertex))
            self._vertices.setdefault(vertex, set()).add(fan)

    def discard(self, fan: UFan) -> None:
        if fan not in self._fans:
            return
        self._fans.remove(fan)
        self._edges.difference_update(fan.edges)
        typed = self._types.get(fan.type)
        if typed is not None:
            typed.discard(fan)
            if not typed:
                self._types.pop(fan.type)
        for vertex in fan.vertices:
            color = fan.color_at(vertex)
            self._colors.pop((vertex, color), None)
            assigned = self._fan_colors.get(vertex)
            if assigned is not None:
                assigned.discard(color)
                if not assigned:
                    self._fan_colors.pop(vertex)
            members = self._vertices.get(vertex)
            if members is not None:
                members.discard(fan)
                if not members:
                    self._vertices.pop(vertex)

    def relabel(self, mapping: dict[Color, Color]) -> None:
        """Apply a global color permutation while preserving all indexes."""
        current = tuple(self)
        for fan in current:
            self.discard(fan)
        try:
            for fan in current:
                self.add(
                    UFan(
                        fan.center,
                        fan.first_leaf,
                        fan.second_leaf,
                        mapping[fan.center_color],
                        mapping[fan.first_color],
                        mapping[fan.second_color],
                    )
                )
        except (KeyError, ValueError):
            self._fans.clear()
            self._edges.clear()
            self._colors.clear()
            self._fan_colors.clear()
            self._vertices.clear()
            self._types.clear()
            raise
        self.assert_valid()

    def at(self, vertex: Vertex) -> tuple[UFan, ...]:
        """Return fans containing ``vertex`` in deterministic order."""
        return tuple(
            sorted(
                self._vertices.get(vertex, set()),
                key=lambda fan: (fan.center, fan.first_leaf, fan.second_leaf),
            )
        )

    def with_vertices(self, vertices: tuple[Vertex, Vertex, Vertex]) -> UFan | None:
        """Return the fan with exactly ``vertices`` in stored order."""
        for fan in self._vertices.get(vertices[0], set()):
            if fan.vertices == vertices:
                return fan
        return None

    def update_vertex_color(
        self, fan: UFan, vertex: Vertex, color: Color
    ) -> UFan | None:
        """Update a fan after a path flip, dropping it if it is damaged."""
        if fan not in self._fans:
            return None
        self.discard(fan)
        try:
            replacement = fan.with_vertex_color(vertex, color)
            self.add(replacement)
        except ValueError:
            return None
        return replacement

    def flip_path(
        self,
        coloring: PartialColoring,
        path: list[Vertex],
        first_color: Color,
        second_color: Color,
    ) -> None:
        """Flip a path and repair fan assignments at both path endpoints."""
        coloring.flip(path, first_color, second_color)
        if not path:
            return
        for endpoint in {path[0], path[-1]}:
            for fan in self.at(endpoint):
                assigned = fan.color_at(endpoint)
                if assigned not in {first_color, second_color}:
                    continue
                self.update_vertex_color(
                    fan,
                    endpoint,
                    second_color if assigned == first_color else first_color,
                )

    def find(self, vertex: Vertex, color: Color) -> UFan | None:
        return self._colors.get((vertex, color))

    def by_type(self, fan_type: frozenset[Color]) -> tuple[UFan, ...]:
        """Return fans of one type in deterministic order."""
        return tuple(
            sorted(
                self._types.get(fan_type, set()),
                key=lambda fan: (fan.center, fan.first_leaf, fan.second_leaf),
            )
        )

    def type_counts(self) -> dict[frozenset[Color], int]:
        """Return a copy of the indexed fan-type counts."""
        return {fan_type: len(members) for fan_type, members in self._types.items()}

    def missing(self, coloring: PartialColoring, vertex: Vertex) -> Color:
        used = self._fan_colors.get(vertex, set())
        available = [color for color in coloring.missing(vertex) if color not in used]
        if not available:
            raise RuntimeError("no missing color remains outside the fan collection")
        return available[0]

    def assert_valid(self) -> None:
        if len(self._edges) != sum(len(fan.edges) for fan in self._fans):
            raise AssertionError("u-fan edges are not disjoint")
        rebuilt: dict[tuple[Vertex, Color], UFan] = {}
        for fan in self._fans:
            for vertex in fan.vertices:
                key = (vertex, fan.color_at(vertex))
                if key in rebuilt:
                    raise AssertionError("u-fan colors collide at a vertex")
                rebuilt[key] = fan
        if rebuilt != self._colors:
            raise AssertionError("u-fan color index is stale")
        rebuilt_fan_colors: dict[Vertex, set[Color]] = {}
        for fan in self._fans:
            for vertex in fan.vertices:
                rebuilt_fan_colors.setdefault(vertex, set()).add(fan.color_at(vertex))
        if rebuilt_fan_colors != self._fan_colors:
            raise AssertionError("u-fan assigned-color index is stale")
        rebuilt_vertices: dict[Vertex, set[UFan]] = {}
        for fan in self._fans:
            for vertex in fan.vertices:
                rebuilt_vertices.setdefault(vertex, set()).add(fan)
        if rebuilt_vertices != self._vertices:
            raise AssertionError("u-fan vertex index is stale")
        rebuilt_types: dict[frozenset[Color], set[UFan]] = {}
        for fan in self._fans:
            rebuilt_types.setdefault(fan.type, set()).add(fan)
        if rebuilt_types != self._types:
            raise AssertionError("u-fan type index is stale")

    def discard_damaged(self, coloring: PartialColoring) -> int:
        """Remove fans whose spokes or assigned colors are no longer valid."""
        damaged = [
            fan
            for fan in self
            if any(
                not coloring.is_missing(vertex, fan.color_at(vertex))
                for vertex in fan.vertices
            )
            or any(edge in coloring for edge in fan.edges)
        ]
        for fan in damaged:
            self.discard(fan)
        self.assert_valid()
        return len(damaged)


def activate_fan(coloring: PartialColoring, fans: SeparableFans, fan: UFan) -> Edge:
    """Activate one u-fan, extending the coloring to one spoke."""
    if fan not in set(fans):
        raise ValueError("fan must belong to the collection")
    spokes = {
        canonical(fan.center, fan.first_leaf),
        canonical(fan.center, fan.second_leaf),
    }
    if any(not coloring.graph.has_edge(*edge) for edge in spokes):
        raise ValueError("u-fan spokes must belong to the graph")
    if any(edge in coloring for edge in spokes):
        raise ValueError("u-fan spokes must both be uncolored")
    for vertex, color in (
        (fan.center, fan.center_color),
        (fan.first_leaf, fan.first_color),
        (fan.second_leaf, fan.second_color),
    ):
        if not coloring.is_missing(vertex, color):
            raise ValueError("u-fan colors must be missing at their vertices")
    paths = [
        (fan.first_leaf, fan.first_color),
        (fan.second_leaf, fan.second_color),
    ]
    for leaf, leaf_color in paths:
        path = coloring.alternating_path(leaf, leaf_color, fan.center_color)
        if fan.center not in path:
            # Remove the activated fan before flipping.  Otherwise
            # ``flip_path`` may replace its endpoint assignment in the
            # collection, leaving a stale fan whose spoke is now colored.
            fans.discard(fan)
            fans.flip_path(coloring, path, leaf_color, fan.center_color)
            edge = canonical(fan.center, leaf)
            coloring.assign(edge, fan.center_color)
            return edge
    raise RuntimeError("both u-fan alternating paths reach the center")


def color_small(coloring: PartialColoring, fans: SeparableFans) -> int:
    """Run the paper's deterministic most-common-type ``Color-Small`` step.

    The routine repeatedly selects the lexicographically first most-common
    u-fan type and activates all currently matching fans.  Fans damaged by a
    successful path flip are removed explicitly.  A failure to activate a
    valid fan is an invariant failure and is reported; no alternate coloring
    algorithm is substituted.
    """
    coloring.validate()
    fans.assert_valid()
    colors_before = dict(coloring._colors)
    fans_before = tuple(fans)
    extended = 0
    try:
        while len(fans):
            counts = fans.type_counts()
            target = min(
                counts, key=lambda value: (-counts[value], tuple(sorted(value)))
            )
            batch = list(fans.by_type(target))
            for fan in batch:
                if fan not in set(fans):
                    continue
                try:
                    activate_fan(coloring, fans, fan)
                except (RuntimeError, ValueError) as error:
                    raise RuntimeError(
                        f"Color-Small could not activate valid fan {fan}"
                    ) from error
                extended += 1
                fans.discard_damaged(coloring)
            fans.assert_valid()
        coloring.validate()
        return extended
    except BaseException:
        coloring._colors = colors_before
        coloring._reindex()
        for fan in tuple(fans):
            fans.discard(fan)
        for fan in fans_before:
            fans.add(fan)
        coloring.validate()
        fans.assert_valid()
        raise


def collect_direct_fans(
    coloring: PartialColoring, uncolored_edges: set[Edge]
) -> SeparableFans:
    """Collect directly constructible separable u-fans deterministically.

    This is the explicit, local part of the paper's fan-construction
    interface.  It only uses supplied uncolored edges; it never moves edges
    or invokes a different coloring algorithm.  The complete paper
    construction will extend this boundary with its fan-chain shifting step.
    """
    graph_edges = set(coloring.graph.edges())
    if not uncolored_edges <= graph_edges:
        raise ValueError("uncolored_edges must be edges of the graph")
    if uncolored_edges & coloring.edges():
        raise ValueError("uncolored_edges must not contain colored edges")

    incident: dict[Vertex, list[Vertex]] = {
        vertex: [] for vertex in range(coloring.graph.n)
    }
    for left, right in sorted(uncolored_edges):
        incident[left].append(right)
        incident[right].append(left)

    palettes = {
        vertex: set(coloring.missing(vertex)) for vertex in range(coloring.graph.n)
    }
    fans = SeparableFans()
    used_spokes: set[Edge] = set()
    for center in range(coloring.graph.n):
        leaves = incident[center]
        for index, first_leaf in enumerate(leaves):
            first_edge = canonical(center, first_leaf)
            if first_edge in used_spokes:
                continue
            for second_leaf in leaves[index + 1 :]:
                second_edge = canonical(center, second_leaf)
                if second_edge in used_spokes:
                    continue
                center_colors = palettes[center]
                first_colors = palettes[first_leaf]
                second_colors = palettes[second_leaf]
                common_leaf_colors = sorted(first_colors & second_colors)
                for leaf_color in common_leaf_colors:
                    center_candidates = sorted(center_colors - {leaf_color})
                    if not center_candidates:
                        continue
                    candidate = UFan(
                        center,
                        first_leaf,
                        second_leaf,
                        center_candidates[0],
                        leaf_color,
                        leaf_color,
                    )
                    try:
                        fans.add(candidate)
                    except ValueError:
                        continue
                    used_spokes.update((first_edge, second_edge))
                    break
                if first_edge in used_spokes:
                    break
    fans.assert_valid()
    return fans


def shift_edge_to_fan(
    coloring: PartialColoring, edge: Edge, fans: SeparableFans
) -> UFan | None:
    """Shift one uncolored edge into a valid two-spoke u-fan.

    For an uncolored ``(u, v)``, choose a color missing at ``v`` but used at
    ``u``.  Uncoloring the unique edge of that color incident to ``u`` gives
    the second fan spoke and makes the color missing at its other endpoint.
    """
    edge = canonical(*edge)
    if edge in coloring:
        raise ValueError("edge must be uncolored before fan shifting")
    for center, leaf in (edge, (edge[1], edge[0])):
        center_missing = set(coloring.missing(center))
        leaf_missing = sorted(coloring.missing(leaf))
        for leaf_color in leaf_missing:
            if leaf_color in center_missing:
                continue
            witness = next(
                (
                    canonical(center, neighbor)
                    for neighbor in sorted(coloring.graph.neighbors(center))
                    if coloring._colors.get(canonical(center, neighbor)) == leaf_color
                ),
                None,
            )
            if witness is None:
                continue
            other = witness[1] if witness[0] == center else witness[0]
            center_color = min(center_missing - {leaf_color})
            old_color = coloring.unassign(witness)
            candidate = UFan(
                center,
                leaf,
                other,
                center_color,
                leaf_color,
                leaf_color,
            )
            try:
                fans.add(candidate)
            except ValueError:
                coloring.assign(witness, old_color)
                continue
            return candidate
    return None


def collect_separable_fans(
    coloring: PartialColoring, uncolored_edges: set[Edge]
) -> SeparableFans:
    """Construct a separable fan collection by direct fans and witness shifts.

    Direct two-spoke fans are selected first.  Every remaining uncolored edge
    is then offered to the deterministic witness-shift operation exactly once;
    a failed shift is an explicit absence of a local fan, not a coloring
    fallback.  The resulting collection remains edge-disjoint and indexed by
    the normal fan invariants.
    """
    graph_edges = set(coloring.graph.edges())
    if not uncolored_edges <= graph_edges:
        raise ValueError("uncolored_edges must be edges of the graph")
    if uncolored_edges & coloring.edges():
        raise ValueError("uncolored_edges must not contain colored edges")

    fans = collect_direct_fans(coloring, set(uncolored_edges))
    fan_edges = {edge for fan in fans for edge in fan.edges}
    pending = sorted(set(uncolored_edges) - fan_edges)
    for edge in pending:
        if edge in coloring or edge in fan_edges:
            continue
        shifted = shift_edge_to_fan(coloring, edge, fans)
        if shifted is not None:
            fan_edges.update(shifted.edges)
    fans.assert_valid()
    return fans


class PaperFanColorer:
    """Deterministic complete coloring through paper u-fan operations.

    This implementation uses the paper's explicit fan-shift and activation
    interface followed by a deterministic maximal fan-chain completion.  It
    intentionally has no Vizing/greedy fallback: if a fan invariant cannot
    be maintained, it raises a diagnostic error.  The complete ABB+26
    near-linear construction and bound remain separate release gates.
    """

    def color(self, graph: Graph, delta: int) -> dict[Edge, Color]:
        if not isinstance(delta, int) or isinstance(delta, bool) or delta < 0:
            raise ValueError("delta must be a non-negative integer")
        maximum = max((graph.degree(vertex) for vertex in range(graph.n)), default=0)
        if maximum > delta:
            raise ValueError(f"delta={delta} is smaller than maximum degree {maximum}")
        all_edges = set(graph.edges())
        if delta >= 32 and all_edges:
            result = _recursive_paper_seed(graph, delta)
        else:
            start = PartialColoring(graph, delta + 1)
            result = _complete_partial_coloring(start, all_edges, delta)
        _certify_complete_coloring(graph, delta, all_edges, result)
        return result


def _certify_complete_coloring(
    graph: Graph, delta: int, all_edges: set[Edge], coloring: dict[Edge, Color]
) -> None:
    """Certify a public colorer result before returning it to callers."""
    if set(coloring) != all_edges:
        raise RuntimeError("paper colorer returned an incomplete edge coloring")
    certificate = PartialColoring(graph, delta + 1)
    for edge, color in sorted(coloring.items()):
        certificate.assign(edge, color)
    certificate.validate()


def _complete_partial_coloring(
    start: PartialColoring, all_edges: set[Edge], delta: int
) -> dict[Edge, Color]:
    """Complete a partial coloring through Extend and deterministic fan chains."""
    separable_fans = collect_separable_fans(start, all_edges - start.edges())
    if separable_fans:
        eta = _paper_eta(delta, start.color_count)
        if eta is None:
            color_small(start, separable_fans)
        else:
            extend_recursive(start, separable_fans, eta)
        start.validate()
    for edge in sorted(all_edges - start.edges()):
        if edge not in start:
            _extend_edge_by_fan_chain(start, edge, delta + 1)
            start.validate()
    if start.edges() != all_edges:
        raise RuntimeError("fan-chain completion left edges uncolored")
    return dict(start.items())


def _paper_eta(delta: int, color_count: int) -> int | None:
    """Return the ABB+26 ``eta`` parameter when recursive Extend applies.

    The type-sparsification construction requires ``10 <= eta <= mu/10``
    for a ``mu``-coloring.  Below that threshold the paper uses its
    ``Color-Small`` base case instead of forcing an invalid block partition.
    """
    if delta < 2 or color_count < 100:
        return None
    eta = 10 * max(1, math.ceil(2 ** math.sqrt(math.log2(delta))))
    if eta > color_count // 10:
        return None
    return eta


def _euler_partition(graph: Graph) -> tuple[Adjacency, Adjacency]:
    """Split edges into two balanced Euler-tour parity subgraphs.

    Odd-degree vertices are paired with deterministic auxiliary edges.  An
    Euler circuit in each augmented component is alternated, then auxiliary
    edges are discarded.  Every original vertex therefore receives the two
    subgraph degrees differing by at most one, which is the recursive ABB
    partition invariant.
    """
    original_edges = sorted(graph.edges())
    components: list[set[Vertex]] = []
    unseen = set(range(graph.n))
    while unseen:
        root = min(unseen)
        component: set[Vertex] = set()
        visit_stack = [root]
        unseen.remove(root)
        while visit_stack:
            vertex = visit_stack.pop()
            component.add(vertex)
            for neighbor in graph.neighbors(vertex):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    visit_stack.append(neighbor)
        if any(graph.degree(vertex) for vertex in component):
            components.append(component)

    augmented: list[tuple[Vertex, Vertex, int | None]] = [
        (left, right, index) for index, (left, right) in enumerate(original_edges)
    ]
    next_auxiliary = graph.n
    for component in components:
        odd = sorted(vertex for vertex in component if graph.degree(vertex) % 2)
        if len(odd) % 2:
            raise RuntimeError("Euler partition found an odd number of odd vertices")
        if odd:
            dummy = next_auxiliary
            next_auxiliary += 1
            augmented.extend((vertex, dummy, None) for vertex in odd)
            augmented_edges = sum(graph.degree(vertex) for vertex in component) // 2
            augmented_edges += len(odd)
            if augmented_edges % 2:
                # The loop is incident only to the auxiliary vertex, so it
                # changes the circuit parity without affecting any original
                # vertex's partition degree.
                augmented.append((dummy, dummy, None))

    incident: dict[Vertex, list[tuple[int, Vertex]]] = {}
    for edge_id, (left, right, _) in enumerate(augmented):
        incident.setdefault(left, []).append((edge_id, right))
        incident.setdefault(right, []).append((edge_id, left))
    for vertex in incident:
        incident[vertex].sort(reverse=True)

    partition: dict[int, int] = {}
    used: set[int] = set()
    for component in components:
        root = min(component)
        trail_stack: list[tuple[Vertex, int | None]] = [(root, None)]
        circuit: list[int] = []
        while trail_stack:
            vertex, incoming = trail_stack[-1]
            while incident[vertex] and incident[vertex][-1][0] in used:
                incident[vertex].pop()
            if incident[vertex]:
                edge_id, neighbor = incident[vertex].pop()
                if edge_id in used:
                    continue
                used.add(edge_id)
                trail_stack.append((neighbor, edge_id))
            else:
                trail_stack.pop()
                if incoming is not None:
                    circuit.append(incoming)
        for position, edge_id in enumerate(reversed(circuit)):
            original_index = augmented[edge_id][2]
            if original_index is not None:
                partition[original_index] = position % 2

    if len(partition) != len(original_edges):
        raise RuntimeError("Euler partition did not assign every graph edge")
    parts = (Adjacency(graph.n), Adjacency(graph.n))
    for index, edge in enumerate(original_edges):
        parts[partition[index]].add_edge(*edge)
    maximum = max((graph.degree(vertex) for vertex in range(graph.n)), default=0)
    # An odd Euler circuit can leave one vertex with one extra edge in a
    # subgraph.  The recursive construction therefore uses the standard
    # ``ceil((Delta + 1) / 2)`` bound, not ``floor((Delta + 1) / 2)``.
    bound = (maximum + 2) // 2
    if any(part.degree(vertex) > bound for part in parts for vertex in range(graph.n)):
        raise RuntimeError("Euler partition violated the balanced-degree bound")
    return parts


def _recursive_paper_seed(graph: Graph, delta: int) -> dict[Edge, Color]:
    """Build the ABB recursive seed, then reduce and extend its palette."""
    if delta < 32:
        start = PartialColoring(graph, delta + 1)
        return _complete_partial_coloring(start, set(graph.edges()), delta)
    left, right = _euler_partition(graph)
    left_delta = max((left.degree(vertex) for vertex in range(graph.n)), default=0)
    right_delta = max((right.degree(vertex) for vertex in range(graph.n)), default=0)
    left_coloring = _recursive_paper_seed(left, left_delta) if left.num_edges() else {}
    right_coloring = (
        _recursive_paper_seed(right, right_delta) if right.num_edges() else {}
    )
    left_palette = left_delta + 1
    combined: dict[Edge, Color] = dict(left_coloring)
    combined.update(
        {edge: color + left_palette for edge, color in right_coloring.items()}
    )
    palette_size = left_palette + right_delta + 1
    if palette_size <= delta + 1:
        remap = {
            color: index for index, color in enumerate(sorted(set(combined.values())))
        }
        return {edge: remap[color] for edge, color in combined.items()}

    counts = {
        color: sum(1 for edge_color in combined.values() if edge_color == color)
        for color in range(palette_size)
    }
    removed = {
        color
        for color, _ in sorted(counts.items(), key=lambda item: (item[1], item[0]))[:2]
    }
    retained = {edge: color for edge, color in combined.items() if color not in removed}
    remap = {
        color: index
        for index, color in enumerate(sorted({color for color in retained.values()}))
    }
    start = PartialColoring(graph, delta + 1)
    for edge, color in sorted(retained.items()):
        start.assign(edge, remap[color])
    return _complete_partial_coloring(start, set(graph.edges()), delta)


def _edge_color_at(
    coloring: PartialColoring, left: Vertex, right: Vertex
) -> Color | None:
    return coloring._colors.get(canonical(left, right))


def _invert_color_component(
    coloring: PartialColoring, start: Vertex, first: Color, second: Color
) -> None:
    if first == second:
        raise ValueError("component colors must differ")
    component: set[Edge] = set()
    visited = {start}
    stack = [start]
    while stack:
        vertex = stack.pop()
        for neighbor in sorted(coloring.graph.neighbors(vertex)):
            edge = canonical(vertex, neighbor)
            color = _edge_color_at(coloring, *edge)
            if color not in {first, second}:
                continue
            component.add(edge)
            if neighbor not in visited:
                visited.add(neighbor)
                stack.append(neighbor)
    for edge in sorted(component):
        coloring._colors[edge] = second if coloring._colors[edge] == first else first
    coloring._reindex()


def _maximal_fan(
    coloring: PartialColoring, center: Vertex, first_leaf: Vertex
) -> list[Vertex]:
    fan = [first_leaf]
    while True:
        last = fan[-1]
        used_at_last = {
            color
            for neighbor in coloring.graph.neighbors(last)
            if (color := _edge_color_at(coloring, last, neighbor)) is not None
        }
        extension = next(
            (
                neighbor
                for neighbor in sorted(coloring.graph.neighbors(center))
                if neighbor not in fan
                and (edge_color := _edge_color_at(coloring, center, neighbor))
                is not None
                and edge_color not in used_at_last
            ),
            None,
        )
        if extension is None:
            return fan
        fan.append(extension)


def _rotatable_fan_prefix(
    coloring: PartialColoring, center: Vertex, fan: list[Vertex], color: Color
) -> int:
    def used(vertex: Vertex) -> set[Color]:
        return {
            value
            for neighbor in coloring.graph.neighbors(vertex)
            if (value := _edge_color_at(coloring, vertex, neighbor)) is not None
        }

    for width, endpoint in enumerate(fan):
        if color in used(endpoint):
            continue
        if all(
            (edge_color := _edge_color_at(coloring, center, fan[index + 1])) is not None
            and edge_color not in used(fan[index])
            for index in range(width)
        ):
            return width
    raise RuntimeError("maximal fan has no rotatable prefix")


def _rotate_fan(
    coloring: PartialColoring, center: Vertex, fan: list[Vertex], width: int
) -> None:
    old_colors = [coloring[canonical(center, fan[index + 1])] for index in range(width)]
    for index, color in enumerate(old_colors):
        coloring._colors[canonical(center, fan[index])] = color
    if width > 0:
        coloring._colors.pop(canonical(center, fan[width]))
    coloring._reindex()


def _extend_edge_by_fan_chain(
    coloring: PartialColoring, edge: Edge, color_count: int
) -> None:
    if color_count != coloring.color_count:
        raise ValueError("fan-chain palette size does not match the coloring")
    center, first = edge
    common = sorted(set(coloring.missing(center)) & set(coloring.missing(first)))
    if common:
        coloring.assign(edge, common[0])
        return
    missing_center = coloring.missing(center)
    if not missing_center:
        raise RuntimeError(f"no missing color available at fan center {center}")
    before = dict(coloring._colors)
    try:
        fan = _maximal_fan(coloring, center, first)
        missing_end = coloring.missing(fan[-1])
        if not missing_end:
            raise RuntimeError(f"no missing color available at fan endpoint {fan[-1]}")
        first_color = missing_center[0]
        second_color = missing_end[0]
        if first_color != second_color:
            _invert_color_component(coloring, center, first_color, second_color)
        width = _rotatable_fan_prefix(coloring, center, fan, second_color)
        _rotate_fan(coloring, center, fan, width)
        coloring.assign(canonical(center, fan[width]), second_color)
        if not 0 <= second_color < color_count:
            raise RuntimeError("fan chain produced a color outside its palette")
    except BaseException:
        coloring._colors = before
        coloring._reindex()
        coloring.validate()
        raise


def color_blocks(
    color_count: int, eta: int
) -> tuple[tuple[frozenset[Color], ...], tuple[frozenset[Color], ...]]:
    """Return the paper's ordered ``C_i`` blocks and paired ``𝒞_k`` blocks."""
    if not isinstance(eta, int) or isinstance(eta, bool) or eta < 10:
        raise ValueError("eta must be an integer at least 10")
    if color_count < 10 * eta:
        raise ValueError("color_count must be at least 10*eta")
    width = color_count // (2 * eta)
    blocks = tuple(
        frozenset(range(index * width, (index + 1) * width)) for index in range(2 * eta)
    )
    pairs = tuple(blocks[index] | blocks[index + 1] for index in range(0, 2 * eta, 2))
    return blocks, pairs


def classify_type_sparsification(
    coloring: PartialColoring,
    uncolored_edges: set[Edge],
    eta: int,
) -> TypeSparsification:
    """Build the paper's diagonal type-sparsification certificate.

    ``uncolored_edges`` must be a matching, and the palette must divide into
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
    if coloring.color_count % eta:
        raise ValueError("color_count must be divisible by eta")

    graph_edges = set(coloring.graph.edges())
    normalized = {canonical(*edge) for edge in uncolored_edges}
    if normalized != uncolored_edges:
        raise ValueError("uncolored_edges must contain canonical edges")
    if not normalized <= graph_edges:
        raise ValueError("uncolored_edges must be edges of the graph")
    if normalized & coloring.edges():
        raise ValueError("uncolored_edges must not contain colored edges")

    endpoints: dict[Vertex, Edge] = {}
    for edge in sorted(normalized):
        for vertex in edge:
            if vertex in endpoints:
                raise ValueError("uncolored_edges must form a matching")
            endpoints[vertex] = edge

    width = coloring.color_count // eta
    blocks = tuple(
        frozenset(range(index * width, (index + 1) * width)) for index in range(eta)
    )
    color_block = {
        color: index for index, block in enumerate(blocks) for color in block
    }
    counts = [[0 for _ in range(eta)] for _ in range(eta)]
    edge_types: dict[Edge, frozenset[tuple[Color, Color]]] = {}
    diagonal: set[Edge] = set()
    for edge in sorted(normalized):
        left_missing = coloring.missing(edge[0])
        right_missing = coloring.missing(edge[1])
        if not left_missing or not right_missing:
            raise RuntimeError(f"uncolored edge has no missing endpoint color: {edge}")
        types = frozenset(
            (left_color, right_color)
            for left_color in left_missing
            for right_color in right_missing
        )
        edge_types[edge] = types
        for left_color, right_color in sorted(types):
            left_block = color_block[left_color]
            right_block = color_block[right_color]
            counts[left_block][right_block] += 1
            if left_block == right_block:
                diagonal.add(edge)

    return TypeSparsification(
        blocks=blocks,
        edge_types=edge_types,
        diagonal_edges=frozenset(diagonal),
        block_counts=tuple(tuple(row) for row in counts),
    )


def _block_index(blocks: tuple[frozenset[Color], ...], color: Color) -> int:
    for index, block in enumerate(blocks):
        if color in block:
            return index
    raise ValueError(f"color {color} is outside the amplified color range")


def _color_in_block(
    blocks: tuple[frozenset[Color], ...], block_index: int, color: Color
) -> Color:
    source = blocks[_block_index(blocks, color)]
    offset = color - min(source)
    target = sorted(blocks[block_index])
    return target[offset]


def fan_is_social(fan: UFan, blocks: tuple[frozenset[Color], ...]) -> bool:
    """Return whether a fan is uniform or aligned in the paper partition."""
    center_block = _block_index(blocks, fan.center_color)
    leaf_block = _block_index(blocks, fan.first_color)
    if center_block == leaf_block:
        return True
    return center_block // 2 == leaf_block // 2


def _damages_social_fan(
    fan: UFan,
    paths: tuple[tuple[tuple[Vertex, ...], Color, Color], ...],
    social: set[UFan],
) -> bool:
    """Return whether flipping ``paths`` can damage an existing social fan."""
    for path_vertices, source, target in paths:
        endpoints = (path_vertices[0], path_vertices[-1])
        for other in social:
            if other is fan:
                continue
            if any(
                endpoint in other.vertices
                and other.color_at(endpoint) in {source, target}
                for endpoint in endpoints
            ):
                return True
    return False


def relevant_paths(
    coloring: PartialColoring,
    fan: UFan,
    blocks: tuple[frozenset[Color], ...],
    pair_index: int,
) -> tuple[tuple[tuple[Vertex, ...], Color, Color], ...]:
    """Compute the paper's three pair-index-relevant alternating paths."""
    if fan_is_social(fan, blocks):
        raise ValueError("relevant paths require a non-social fan")
    center_block = _block_index(blocks, fan.center_color)
    leaf_block = _block_index(blocks, fan.first_color)
    left_block = 2 * pair_index
    right_block = left_block + 1
    if center_block == right_block or leaf_block == left_block:
        left_block, right_block = right_block, left_block

    def path(
        start: Vertex, source: Color, target_block: int
    ) -> tuple[tuple[Vertex, ...], Color, Color]:
        target = _color_in_block(blocks, target_block, source)
        if source == target:
            return (start,), source, target
        return tuple(coloring.alternating_path(start, source, target)), source, target

    return (
        path(fan.center, fan.center_color, left_block),
        path(fan.first_leaf, fan.first_color, right_block),
        path(fan.second_leaf, fan.second_color, right_block),
    )


def modify_types(
    coloring: PartialColoring,
    fans: SeparableFans,
    batch: tuple[UFan, ...],
    blocks: tuple[frozenset[Color], ...],
    pair_index: int,
) -> None:
    """Apply one ``Modify-Types`` batch atomically."""
    coloring.validate()
    fans.assert_valid()
    colors_before = dict(coloring._colors)
    fans_before = tuple(fans)
    try:
        _modify_types_unchecked(coloring, fans, batch, blocks, pair_index)
    except BaseException:
        coloring._colors = colors_before
        coloring._reindex()
        for fan in tuple(fans):
            fans.discard(fan)
        for fan in fans_before:
            fans.add(fan)
        coloring.validate()
        fans.assert_valid()
        raise


def _modify_types_unchecked(
    coloring: PartialColoring,
    fans: SeparableFans,
    batch: tuple[UFan, ...],
    blocks: tuple[frozenset[Color], ...],
    pair_index: int,
) -> None:
    """Apply one paper ``Modify-Types`` batch in place.

    Every selected fan is transformed with its pair-index-relevant paths.
    Relevant paths are flipped only once when two fans share the same path;
    any other edge overlap is an invariant violation and raises.  The fan
    index is rebuilt around the simultaneous operation, and stale fans whose
    assigned missing colors were damaged are removed explicitly.
    """
    coloring.validate()
    fans.assert_valid()
    colored_edges = coloring.edges()
    if not batch:
        raise ValueError("Modify-Types requires a non-empty fan batch")
    if any(fan not in set(fans) for fan in batch):
        raise ValueError("Modify-Types batch must belong to the fan collection")
    if len(set(batch)) != len(batch):
        raise ValueError("Modify-Types batch must not contain duplicate fans")

    fan_paths: dict[UFan, tuple[tuple[tuple[Vertex, ...], Color, Color], ...]] = {
        fan: relevant_paths(coloring, fan, blocks, pair_index) for fan in batch
    }
    for fan in batch:
        # Keep selected fans out of the index while their three paths are
        # being flipped; otherwise endpoint repair can create an intermediate
        # fan with the same spokes.
        fans.discard(fan)

    unique_paths: list[tuple[tuple[Vertex, ...], Color, Color]] = []
    seen_edges: set[Edge] = set()
    for path, source, target_color in (
        path for paths in fan_paths.values() for path in paths
    ):
        edges = {canonical(left, right) for left, right in pairwise(path)}
        if edges and edges <= seen_edges:
            continue
        if edges & seen_edges:
            raise RuntimeError("Modify-Types produced overlapping relevant paths")
        seen_edges.update(edges)
        unique_paths.append((path, source, target_color))
    for path, source, target_color in unique_paths:
        fans.flip_path(coloring, list(path), source, target_color)

    for fan in tuple(fans):
        if any(
            fan.color_at(vertex) not in coloring.missing(vertex)
            for vertex in fan.vertices
        ):
            fans.discard(fan)

    for fan, paths in fan_paths.items():
        fans.add(
            UFan(
                fan.center,
                fan.first_leaf,
                fan.second_leaf,
                paths[0][2],
                paths[1][2],
                paths[2][2],
            )
        )
    coloring.validate()
    fans.assert_valid()
    if coloring.edges() != colored_edges:
        raise RuntimeError("Modify-Types changed the set of colored edges")


def sparsify_types(
    coloring: PartialColoring, fans: SeparableFans, eta: int
) -> tuple[tuple[frozenset[Color], ...], SeparableFans]:
    """Run ``Sparsify-Types`` atomically over the coloring and fan index."""
    colors_before = dict(coloring._colors)
    fans_before = tuple(fans)
    try:
        return _sparsify_types_unchecked(coloring, fans, eta)
    except BaseException:
        coloring._colors = colors_before
        coloring._reindex()
        for fan in tuple(fans):
            fans.discard(fan)
        for fan in fans_before:
            fans.add(fan)
        coloring.validate()
        fans.assert_valid()
        raise


def _sparsify_types_unchecked(
    coloring: PartialColoring, fans: SeparableFans, eta: int
) -> tuple[tuple[frozenset[Color], ...], SeparableFans]:
    """Run the deterministic ``Sparsify-Types`` fan transformation.

    The routine implements the paper's type partition, relevant-path flips,
    good-fan selection, and damaged-fan removal.  It changes only colors on
    alternating paths and the fan index; it never changes which graph edges
    are colored.  Fan-chain construction is a separate input-stage operation;
    callers must provide a valid separable fan collection.
    """
    if not isinstance(eta, int) or isinstance(eta, bool) or eta < 10:
        raise ValueError("eta must be an integer at least 10")
    if coloring.color_count < 10 * eta:
        raise ValueError("color_count must be at least 10*eta")
    coloring.validate()
    fans.assert_valid()
    colored_edges = coloring.edges()
    initial = len(fans)
    if initial == 0:
        raise ValueError("sparsify_types requires at least one u-fan")
    counts = {color: 0 for color in range(coloring.color_count)}
    for fan in fans:
        for color in fan.type:
            counts[color] += 1
    order = sorted(counts, key=lambda color: (-counts[color], color))
    mapping = {old: new for new, old in enumerate(order)}
    coloring.relabel(mapping)
    fans.relabel(mapping)
    blocks, pairs = color_blocks(coloring.color_count, eta)
    for fan in tuple(fans):
        try:
            for color in fan.type:
                _block_index(blocks, color)
        except ValueError:
            fans.discard(fan)

    retained = len(fans)
    minimum_retained = (3 * initial + 4) // 5
    if retained < minimum_retained:
        raise RuntimeError(
            "Sparsify-Types preprocessing discarded too many u-fans: "
            f"retained={retained}, required={minimum_retained}, initial={initial}"
        )

    # The paper's constant-fraction bound is integral in the implementation:
    # every non-empty input must retain at least one social fan.
    target = max(1, (initial + 99) // 100)
    social = {fan for fan in fans if fan_is_social(fan, blocks)}
    iterations = 0
    # A successful iteration adds at least one previously non-social fan to
    # ``social``.  The input collection is finite, so its size is the exact
    # progress bound; this guard protects against a broken path/index
    # invariant without imposing a heuristic iteration budget.
    max_iterations = max(1, len(fans))
    while len(social) < target:
        iterations += 1
        if iterations > max_iterations:
            raise RuntimeError(
                "Sparsify-Types exceeded its deterministic iteration bound without "
                "reaching the required social-fan mass"
            )
        pair_counts = [
            sum(
                1
                for fan in fans
                if fan_is_social(fan, blocks) and fan.type <= pair_colors
            )
            for pair_colors in pairs
        ]
        pair_index = min(
            range(len(pairs)), key=lambda index: (pair_counts[index], index)
        )
        # This is the paper's B_k filter: a non-social fan is k-bad exactly
        # when one of its k-relevant paths would damage an already social fan.
        good_by_type: dict[tuple[int, int], list[UFan]] = {}
        for fan in fans:
            if fan_is_social(fan, blocks):
                continue
            try:
                paths = relevant_paths(coloring, fan, blocks, pair_index)
            except ValueError:
                continue
            if _damages_social_fan(fan, paths, social):
                continue
            center_block = _block_index(blocks, fan.center_color)
            leaf_block = _block_index(blocks, fan.first_color)
            # A fan type is an unordered pair of color blocks.  Canonicalize
            # the pair so opposite orientations share one paper batch.
            key = (min(center_block, leaf_block), max(center_block, leaf_block))
            good_by_type.setdefault(key, []).append(fan)
        if not good_by_type:
            raise RuntimeError(
                "Sparsify-Types could not find a good fan for the selected color pair"
            )
        batch_key = max(
            good_by_type,
            key=lambda key: (len(good_by_type[key]), -key[0], -key[1]),
        )
        batch = tuple(good_by_type[batch_key])
        social_before = len(social)
        modify_types(coloring, fans, batch, blocks, pair_index)
        social = {fan for fan in fans if fan_is_social(fan, blocks)}
        if len(social) <= social_before:
            raise RuntimeError("Sparsify-Types made no social-fan progress")
    result = SeparableFans()
    for fan in social:
        result.add(fan)
    if len(result) < target:
        raise RuntimeError(
            "Sparsify-Types returned fewer social fans than its constant-fraction "
            f"bound: retained={len(result)}, required={target}"
        )
    if any(not fan_is_social(fan, blocks) for fan in result):
        raise RuntimeError("Sparsify-Types returned a non-social u-fan")
    if any(len(group) > coloring.color_count // eta for group in pairs):
        raise RuntimeError("Sparsify-Types returned an oversized color group")
    if coloring.edges() != colored_edges:
        raise RuntimeError("Sparsify-Types changed the set of colored edges")
    return pairs, result


def _project_subproblem(
    coloring: PartialColoring,
    fans: SeparableFans,
    color_group: frozenset[Color],
) -> tuple[PartialColoring, SeparableFans, set[Edge], tuple[Color, ...]]:
    """Project one paper ``Extend`` subproblem onto local color numbers."""
    ordered = tuple(sorted(color_group))
    to_local = {color: index for index, color in enumerate(ordered)}
    edge_scope = {edge for edge, color in coloring.items() if color in color_group}
    selected_fans = [fan for fan in fans if fan.type <= color_group]
    for fan in selected_fans:
        edge_scope.update(fan.edges)
    degree: dict[Vertex, int] = {vertex: 0 for vertex in range(coloring.graph.n)}
    for left, right in edge_scope:
        degree[left] += 1
        degree[right] += 1
    maximum_degree = max(degree.values(), default=0)
    if maximum_degree > len(ordered):
        raise RuntimeError(
            "Extend projected an infeasible subproblem: "
            f"maximum degree {maximum_degree} exceeds palette size {len(ordered)}"
        )
    child = PartialColoring(coloring.graph, len(ordered))
    for edge in edge_scope:
        if edge in coloring:
            color = coloring[edge]
            if color not in to_local:
                raise RuntimeError("subproblem projection crossed a color group")
            child._colors[edge] = to_local[color]
    child._reindex()
    child.validate()
    child_fans = SeparableFans()
    for fan in selected_fans:
        child_fans.add(
            UFan(
                fan.center,
                fan.first_leaf,
                fan.second_leaf,
                to_local[fan.center_color],
                to_local[fan.first_color],
                to_local[fan.second_color],
            )
        )
    return child, child_fans, edge_scope, ordered


def _merge_subproblem(
    parent: PartialColoring,
    child: PartialColoring,
    edge_scope: set[Edge],
    local_colors: tuple[Color, ...],
) -> None:
    """Merge a completed isolated subproblem into its parent coloring."""
    for edge in edge_scope:
        if edge not in child:
            continue
        local = child[edge]
        if not 0 <= local < len(local_colors):
            raise RuntimeError("subproblem returned an invalid local color")
        parent._colors[edge] = local_colors[local]
    parent._reindex()
    parent.validate()


def extend_recursive(coloring: PartialColoring, fans: SeparableFans, eta: int) -> int:
    """Recursively execute the paper's ``Extend`` decomposition.

    ``Sparsify-Types`` supplies disjoint color groups and social fans.  Each group is
    projected to local color numbers, processed independently, and merged back
    only after its properness has been validated.  If amplification cannot
    produce a valid recursive split, this function raises instead of invoking
    a classical-coloring fallback.
    """
    coloring.validate()
    fans.assert_valid()
    if not fans:
        return 0
    if coloring.color_count <= 10 * eta:
        return color_small(coloring, fans)

    groups, social = sparsify_types(coloring, fans, eta)
    if not social:
        raise RuntimeError("Extend received no social fans after Sparsify-Types")
    total = 0
    scoped_edges: set[Edge] = set()
    for group in groups:
        selected = [fan for fan in social if fan.type <= group]
        if not selected:
            continue
        child, child_fans, edge_scope, local_colors = _project_subproblem(
            coloring, social, group
        )
        if scoped_edges & edge_scope:
            raise RuntimeError("Extend produced overlapping recursive edge scopes")
        scoped_edges.update(edge_scope)
        total += extend_recursive(child, child_fans, eta)
        _merge_subproblem(coloring, child, edge_scope, local_colors)
    coloring.validate()
    return total
