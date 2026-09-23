"""Stateful primitives used by the paper's deterministic coloring algorithm.

This module deliberately models the paper's partial-coloring interface rather
than exposing a second edge-coloring implementation.  The higher-level
``Extend`` recursion can therefore operate on explicit uncolored edges,
alternating paths, u-fans, and separable collections without treating a
classical complete coloring as an interchangeable substitute.
"""

from __future__ import annotations

from collections.abc import ItemsView, Iterator
from dataclasses import dataclass
from itertools import pairwise

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

    def __contains__(self, edge: object) -> bool:
        return edge in self._colors

    def __getitem__(self, edge: Edge) -> Color:
        return self._colors[canonical(*edge)]

    def items(self) -> ItemsView[Edge, Color]:
        return self._colors.items()

    def edges(self) -> set[Edge]:
        return set(self._colors)

    def missing(self, vertex: Vertex) -> list[Color]:
        used = {
            color
            for neighbor in self.graph.neighbors(vertex)
            if (color := self._colors.get(canonical(vertex, neighbor))) is not None
        }
        return [color for color in range(self.color_count) if color not in used]

    def assign(self, edge: Edge, color: Color) -> None:
        edge = canonical(*edge)
        if edge not in set(self.graph.edges()):
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

    def recolor(self, edge: Edge, color: Color) -> None:
        edge = canonical(*edge)
        if edge not in self._colors:
            raise ValueError(f"edge is not colored: {edge}")
        old = self._colors.pop(edge)
        try:
            self.assign(edge, color)
        except Exception:
            self._colors[edge] = old
            raise

    def alternating_path(
        self, start: Vertex, first_color: Color, second_color: Color
    ) -> list[Vertex]:
        """Return the maximal simple path starting with ``second_color``."""
        if first_color == second_color:
            raise ValueError("alternating path colors must differ")
        if first_color not in self.missing(start):
            raise ValueError("first color must be missing at the path start")
        path = [start]
        visited = {start}
        current = start
        wanted = second_color
        while True:
            next_vertex = next(
                (
                    neighbor
                    for neighbor in sorted(self.graph.neighbors(current))
                    if neighbor not in visited
                    and self._colors.get(canonical(current, neighbor)) == wanted
                ),
                None,
            )
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


class SeparableFans:
    """Deterministic collection enforcing the paper's separability invariant."""

    def __init__(self) -> None:
        self._fans: set[UFan] = set()
        self._edges: set[Edge] = set()
        self._colors: dict[tuple[Vertex, Color], UFan] = {}
        self._vertices: dict[Vertex, set[UFan]] = {}

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
        for vertex in fan.vertices:
            self._colors[(vertex, fan.color_at(vertex))] = fan
            self._vertices.setdefault(vertex, set()).add(fan)

    def discard(self, fan: UFan) -> None:
        if fan not in self._fans:
            return
        self._fans.remove(fan)
        self._edges.difference_update(fan.edges)
        for vertex in fan.vertices:
            self._colors.pop((vertex, fan.color_at(vertex)), None)
            members = self._vertices.get(vertex)
            if members is not None:
                members.discard(fan)
                if not members:
                    self._vertices.pop(vertex)

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

    def missing(self, coloring: PartialColoring, vertex: Vertex) -> Color:
        used = {fan.color_at(vertex) for fan in self if vertex in fan.vertices}
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
        rebuilt_vertices: dict[Vertex, set[UFan]] = {}
        for fan in self._fans:
            for vertex in fan.vertices:
                rebuilt_vertices.setdefault(vertex, set()).add(fan)
        if rebuilt_vertices != self._vertices:
            raise AssertionError("u-fan vertex index is stale")


def activate_fan(coloring: PartialColoring, fans: SeparableFans, fan: UFan) -> Edge:
    """Activate one u-fan, extending the coloring to one spoke."""
    if fan not in set(fans):
        raise ValueError("fan must belong to the collection")
    spokes = {
        canonical(fan.center, fan.first_leaf),
        canonical(fan.center, fan.second_leaf),
    }
    if not spokes <= set(coloring.graph.edges()):
        raise ValueError("u-fan spokes must belong to the graph")
    if spokes & coloring.edges():
        raise ValueError("u-fan spokes must both be uncolored")
    for vertex, color in (
        (fan.center, fan.center_color),
        (fan.first_leaf, fan.first_color),
        (fan.second_leaf, fan.second_color),
    ):
        if color not in coloring.missing(vertex):
            raise ValueError("u-fan colors must be missing at their vertices")
    paths = [
        (fan.first_leaf, fan.first_color),
        (fan.second_leaf, fan.second_color),
    ]
    for leaf, leaf_color in paths:
        path = coloring.alternating_path(leaf, leaf_color, fan.center_color)
        if fan.center not in path:
            fans.flip_path(coloring, path, leaf_color, fan.center_color)
            edge = canonical(fan.center, leaf)
            coloring.assign(edge, fan.center_color)
            fans.discard(fan)
            return edge
    raise RuntimeError("both u-fan alternating paths reach the center")


def small_extend(coloring: PartialColoring, fans: SeparableFans) -> int:
    """Run the paper's deterministic most-common-type ``Small`` step.

    The routine repeatedly selects the lexicographically first most-common
    u-fan type and activates all currently matching fans.  A fan that cannot
    be activated is removed explicitly as a damaged fan; no alternate
    coloring algorithm is substituted.
    """
    extended = 0
    while len(fans):
        counts: dict[frozenset[Color], int] = {}
        for fan in fans:
            counts[fan.type] = counts.get(fan.type, 0) + 1
        target = min(counts, key=lambda value: (-counts[value], tuple(sorted(value))))
        batch = [fan for fan in fans if fan.type == target]
        for fan in batch:
            if fan not in set(fans):
                continue
            try:
                activate_fan(coloring, fans, fan)
            except (RuntimeError, ValueError):
                fans.discard(fan)
            else:
                extended += 1
        fans.assert_valid()
    return extended


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

    fans = SeparableFans()
    for center in range(coloring.graph.n):
        leaves = incident[center]
        for index, first_leaf in enumerate(leaves):
            for second_leaf in leaves[index + 1 :]:
                center_colors = set(coloring.missing(center))
                first_colors = set(coloring.missing(first_leaf))
                second_colors = set(coloring.missing(second_leaf))
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
                    break
    fans.assert_valid()
    return fans


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


def amplify(
    coloring: PartialColoring, fans: SeparableFans, eta: int
) -> tuple[tuple[frozenset[Color], ...], SeparableFans]:
    """Run the deterministic socialization phase of paper ``Amplify``.

    The routine implements the paper's type partition, relevant-path flips,
    good-fan selection, and damaged-fan removal.  Fan-chain construction is a
    separate input-stage operation; callers must provide a separable fan
    collection.
    """
    blocks, pairs = color_blocks(coloring.color_count, eta)
    initial = len(fans)
    for fan in tuple(fans):
        try:
            for color in fan.type:
                _block_index(blocks, color)
        except ValueError:
            fans.discard(fan)

    target = initial // 100
    social = {fan for fan in fans if fan_is_social(fan, blocks)}
    while len(social) < target:
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
        good_by_type: dict[tuple[int, int], list[UFan]] = {}
        for fan in fans:
            if fan_is_social(fan, blocks):
                continue
            try:
                paths = relevant_paths(coloring, fan, blocks, pair_index)
            except ValueError:
                continue
            damages_social = any(
                endpoint in other.vertices
                and other.color_at(endpoint) in {source, target}
                for path_vertices, source, target in paths
                for endpoint in (path_vertices[0], path_vertices[-1])
                for other in social
                if other is not fan
            )
            if damages_social:
                continue
            center_block = _block_index(blocks, fan.center_color)
            leaf_block = _block_index(blocks, fan.first_color)
            key = (center_block, leaf_block)
            good_by_type.setdefault(key, []).append(fan)
        if not good_by_type:
            raise RuntimeError(
                "Amplify could not find a good fan for the selected color pair"
            )
        batch_key = max(
            good_by_type,
            key=lambda key: (len(good_by_type[key]), tuple(-value for value in key)),
        )
        batch = good_by_type[batch_key]
        paths_to_flip: list[tuple[tuple[Vertex, ...], Color, Color]] = []
        for fan in batch:
            paths_to_flip.extend(relevant_paths(coloring, fan, blocks, pair_index))
        unique_paths: list[tuple[tuple[Vertex, ...], Color, Color]] = []
        seen_edges: set[Edge] = set()
        for path, source, target_color in paths_to_flip:
            edges = {canonical(left, right) for left, right in pairwise(path)}
            if edges and edges <= seen_edges:
                continue
            if edges & seen_edges:
                raise RuntimeError("Amplify produced overlapping relevant paths")
            seen_edges.update(edges)
            unique_paths.append((path, source, target_color))
        for path, source, target_color in unique_paths:
            fans.flip_path(coloring, list(path), source, target_color)
        social = {fan for fan in fans if fan_is_social(fan, blocks)}
        if not social and target > 0:
            raise RuntimeError("Amplify made no progress")
    result = SeparableFans()
    for fan in social:
        result.add(fan)
    return pairs, result
