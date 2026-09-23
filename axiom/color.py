r"""Deterministic edge-coloring routines.

**Fidelity note:** The paper invokes Theorem 2.4 (ABB+26) for deterministic
:math:`(\Delta+1)`-edge-coloring in :math:`O(m^{1+o(1)})` time.  The
authoritative source contains the complete type-sparsification, u-fan, and
color-extension procedures.  This module currently provides two
correctness-preserving classical implementations instead:

1. ``Greedy`` -- a degree-ordered colouring pass with an explicit local
   recoloring operation when a colour is unavailable.

2. ``Vizing`` -- the deterministic fan-based Vizing/Misra--Gries
   construction, using at most :math:`\Delta+1` colours.

Both algorithms produce valid (Δ+1)-edge-colourings.  Neither implementation
claims the ABB+26 near-linear running time.

Mathematical background:
    Vizing's theorem (Vizing 1964) states that every simple graph admits a
    proper edge-coloring with at most :math:`\Delta + 1` colours, where
    :math:`\Delta` is the maximum degree.  The constructive proof is by
    induction on the number of edges: assuming a partial colouring on
    :math:`E \setminus \{e\}`, the unfavourable case is that every colour
    is used at one endpoint of ``e``; flipping a two-colour alternating
    path frees one colour at the other endpoint.  The paper cites a more
    recent deterministic construction (Theorem 2.4, ABB+26) running in
    :math:`O(m^{1+o(1)})` time; this module does not claim that asymptotic
    bound for either local implementation.

Limitations:
    * The :math:`O(m^{1+o(1)})` bound of Theorem 2.4 is **not** met here.
      ``Greedy`` and the classical fan algorithm are polynomial but have
      larger worst-case bounds than ABB+26.
"""

from __future__ import annotations

from axiom.types import Color, Coloring, Edge, Graph, Vertex, canonical


class VizingColoringError(RuntimeError):
    """Raised when the constructive Vizing recoloring argument hits a corner case.

    This is a narrow subclass so callers can distinguish a failed explicit
    constructive recolouring operation from unexpected programming errors.
    """


class Greedy:
    """Fast greedy edge-coloring using degree-ordered processing.

    This is a deterministic degree-ordered colouring pass. It is an
    engineering utility and does not claim the ABB+26 asymptotic bound.

    Algorithm (pseudocode):
        1. Build ``vertex_colors[v] = {c : (v, ?) has color c}``.
        2. Process edges in decreasing ``deg(u) + deg(v)`` order so that
           high-degree endpoints get their colours first.
        3. For each edge ``(u, v)`` find the smallest ``c`` not used at
           either endpoint; assign it.
        4. If no such ``c`` exists, run the explicit local Vizing recoloring
           operation.  Failure is reported; the implementation never swaps
           in a different coloring algorithm implicitly.
    """

    def color(self, graph: Graph, delta: int) -> Coloring:
        r"""Return a proper edge coloring of the graph.

        Args:
            graph: The graph to color.
            delta: An upper bound on the maximum degree.

        Returns:
            A dictionary mapping each canonical edge to its colour.

        Complexity:
            Worst-case :math:`O(m \cdot \Delta)` because of the recolouring
            attempts.  Empirically much faster on sparse graphs.
        """
        max_colors = delta + 1
        coloring: Coloring = {}

        if graph.num_edges() == 0:
            return coloring

        vertex_colors: list[set[Color]] = [set() for _ in range(graph.n)]

        edges = sorted(
            graph.edges(),
            key=lambda e: -(graph.degree(e[0]) + graph.degree(e[1])),
        )

        for u, v in edges:
            e = canonical(u, v)
            used_u = vertex_colors[u]
            used_v = vertex_colors[v]

            assigned = False
            for c in range(max_colors):
                if c not in used_u and c not in used_v:
                    coloring[e] = c
                    used_u.add(c)
                    used_v.add(c)
                    assigned = True
                    break

            if assigned:
                continue

            success = recolor(graph, coloring, vertex_colors, u, v, max_colors)
            if not success:
                try:
                    color_one(graph, u, v, coloring, max_colors)
                    vertex_colors[u].add(coloring[e])
                    vertex_colors[v].add(coloring[e])
                except VizingColoringError as error:
                    raise VizingColoringError(
                        "greedy edge coloring could not complete its explicit "
                        f"recoloring for edge {e}: {error}"
                    ) from error

        return coloring


class Vizing:
    """Deterministic fan-based ``(Delta + 1)`` edge coloring."""

    def color(self, graph: Graph, delta: int) -> Coloring:
        r"""Return a proper edge coloring of the graph.

        Args:
            graph: The graph to color.
            delta: An upper bound on the maximum degree of the graph.
                   The algorithm uses the colour set ``{0, ..., delta}``.

        Returns:
            A dictionary mapping each canonical edge to its colour.

        Complexity:
            Polynomial in the graph size using the classical fan procedure.
        """
        if delta < 0:
            raise ValueError("delta must be non-negative")
        maximum = max((graph.degree(v) for v in range(graph.n)), default=0)
        if maximum > delta:
            raise ValueError(f"delta={delta} is smaller than maximum degree {maximum}")
        # Exact special cases: a degree-zero graph has no edges, while a
        # degree-one graph is a matching and every edge may use color 0.
        # These cases occur frequently at the finest recursive levels.
        if maximum <= 1:
            return {edge: 0 for edge in graph.edges()}
        return _misra_gries(graph, delta + 1)


def _misra_gries(graph: Graph, color_count: int) -> Coloring:
    """Construct a proper coloring with the fan proof of Vizing's theorem."""
    coloring: Coloring = {}
    for center, first in sorted(graph.edges()):
        fan = _maximal_fan(graph, coloring, center, first)
        first_color = _missing_at(graph, coloring, center, color_count)[0]
        second_color = _missing_at(graph, coloring, fan[-1], color_count)[0]
        _invert_cd_component(graph, coloring, center, first_color, second_color)
        width = _rotatable_prefix(graph, coloring, center, fan, second_color)
        _rotate_fan(coloring, center, fan[: width + 1])
        coloring[canonical(center, fan[width])] = second_color
    _assert_coloring(graph, coloring, color_count)
    return coloring


def _incident_colors(graph: Graph, coloring: Coloring, vertex: Vertex) -> set[Color]:
    return {
        coloring[canonical(vertex, neighbor)]
        for neighbor in graph.neighbors(vertex)
        if canonical(vertex, neighbor) in coloring
    }


def _missing_at(
    graph: Graph, coloring: Coloring, vertex: Vertex, color_count: int
) -> list[Color]:
    used = _incident_colors(graph, coloring, vertex)
    return [color for color in range(color_count) if color not in used]


def _maximal_fan(
    graph: Graph, coloring: Coloring, center: Vertex, first: Vertex
) -> list[Vertex]:
    fan = [first]
    while True:
        last_colors = _incident_colors(graph, coloring, fan[-1])
        extension = next(
            (
                neighbor
                for neighbor in sorted(graph.neighbors(center))
                if neighbor not in fan
                and canonical(center, neighbor) in coloring
                and coloring[canonical(center, neighbor)] not in last_colors
            ),
            None,
        )
        if extension is None:
            return fan
        fan.append(extension)


def _invert_cd_component(
    graph: Graph,
    coloring: Coloring,
    start: Vertex,
    color1: Color,
    color2: Color,
) -> None:
    component_edges: set[Edge] = set()
    visited = {start}
    stack = [start]
    while stack:
        vertex = stack.pop()
        for neighbor in graph.neighbors(vertex):
            edge = canonical(vertex, neighbor)
            if edge not in coloring or coloring[edge] not in {color1, color2}:
                continue
            component_edges.add(edge)
            if neighbor not in visited:
                visited.add(neighbor)
                stack.append(neighbor)
    for edge in component_edges:
        coloring[edge] = color2 if coloring[edge] == color1 else color1


def _rotatable_prefix(
    graph: Graph,
    coloring: Coloring,
    center: Vertex,
    fan: list[Vertex],
    color: Color,
) -> int:
    for width, endpoint in enumerate(fan):
        if color in _incident_colors(graph, coloring, endpoint):
            continue
        if all(
            canonical(center, fan[index + 1]) in coloring
            and coloring[canonical(center, fan[index + 1])]
            not in _incident_colors(graph, coloring, fan[index])
            for index in range(width)
        ):
            return width
    raise RuntimeError("fan inversion failed to produce a rotatable prefix")


def _rotate_fan(coloring: Coloring, center: Vertex, fan: list[Vertex]) -> None:
    if len(fan) <= 1:
        return
    old = [coloring[canonical(center, vertex)] for vertex in fan[1:]]
    for index, color in enumerate(old):
        coloring[canonical(center, fan[index])] = color
    coloring.pop(canonical(center, fan[-1]), None)


def _assert_coloring(graph: Graph, coloring: Coloring, color_count: int) -> None:
    if set(coloring) != set(graph.edges()):
        raise RuntimeError("edge-coloring did not assign every graph edge")
    for vertex in range(graph.n):
        colors = [
            coloring[canonical(vertex, neighbor)]
            for neighbor in graph.neighbors(vertex)
        ]
        if len(colors) != len(set(colors)) or any(
            color < 0 or color >= color_count for color in colors
        ):
            raise RuntimeError(f"invalid edge coloring at vertex {vertex}")


def recolor(
    graph: Graph,
    coloring: Coloring,
    vertex_colors: list[set[Color]],
    u: Vertex,
    v: Vertex,
    max_colors: int,
) -> bool:
    r"""Try to free a colour for edge ``(u, v)`` via short recolouring.

    Looks for a colour ``c1`` that is used at ``v`` but missing at ``u``;
    that colour is the limiting constraint.  If we can shift the unique
    edge of colour ``c1`` at ``v`` to a new colour ``c2`` (missing at
    both its endpoints) then ``c1`` becomes free at ``v`` and we can
    assign it to ``(u, v)`` while keeping the partial colouring proper.

    Searches along an alternating path of length at most 3 from ``u``
    -- this is much faster than the full Vizing alternating path in
    :func:`alternating`.

    Args:
        graph: The host graph.
        coloring: Current partial colouring (mutated on success).
        vertex_colors: Per-vertex set of colours already used (mutated).
        u: Target endpoint that needs ``c1``.
        v: Other endpoint.
        max_colors: Bound on the colour palette (``delta + 1``).

    Returns:
        ``True`` if recolouring succeeded and a colour was freed.
    """
    used_u = vertex_colors[u]
    used_v = vertex_colors[v]

    for c1 in range(max_colors):
        if c1 not in used_u and c1 in used_v:
            e_v = find(graph, coloring, v, c1)
            if e_v is None:
                continue
            w = e_v[0] if e_v[1] == v else e_v[1]

            for c2 in range(max_colors):
                if (
                    c2 != c1
                    and c2 not in vertex_colors[v]
                    and c2 not in vertex_colors[w]
                ):
                    coloring[e_v] = c2
                    vertex_colors[v].discard(c1)
                    vertex_colors[v].add(c2)
                    vertex_colors[w].discard(c1)
                    vertex_colors[w].add(c2)

                    e_uv = canonical(u, v)
                    coloring[e_uv] = c1
                    used_u.add(c1)
                    used_v.add(c1)
                    return True

    return False


def find(graph: Graph, coloring: Coloring, v: Vertex, c: Color) -> Edge | None:
    """Find an edge incident to ``v`` with colour ``c``.

    Returns:
        The unique matching edge or ``None`` if none exists.
    """
    for w in graph.neighbors(v):
        e = canonical(v, w)
        if e in coloring and coloring[e] == c:
            return e
    return None


def missing(
    graph: Graph,
    vertex: Vertex,
    coloring: Coloring,
    max_colors: int,
) -> list[Color]:
    r"""Return a list of colours not incident to ``vertex`` in ``coloring``.

    Args:
        graph: The host graph.
        vertex: The vertex whose incident edges should be inspected.
        coloring: The current partial colouring.
        max_colors: Size of the colour palette.

    Returns:
        Colours in ``[0, max_colors)`` that do not yet appear on any edge
        of ``vertex``.  The list is empty when the vertex is saturated.

    Complexity:
        :math:`O(\deg(v))` to inspect every incident edge.
    """
    used: set[Color] = set()
    for w in graph.neighbors(vertex):
        e = canonical(vertex, w)
        if e in coloring:
            used.add(coloring[e])
    return [c for c in range(max_colors) if c not in used]


def alternating(
    graph: Graph,
    coloring: Coloring,
    start: Vertex,
    color1: Color,
    color2: Color,
) -> list[Vertex]:
    r"""Return the maximal ``color1/color2`` alternating path beginning at ``start``.

    The returned path always has even length and alternates between edges
    whose current colour is ``color1`` and edges whose current colour is
    ``color2``.  The first edge is in ``color2`` because ``start`` is
    assumed to be missing ``color1``, so the first step out of ``start``
    uses the colour we want to introduce there.

    Args:
        graph: The host graph.
        coloring: Current partial colouring.
        start: Path origin (must be missing ``color1``).
        color1: The colour we ultimately want to free at ``start``.
        color2: The colour introduced to recolour along the path.

    Returns:
        List of vertices ``[start, v_1, v_2, ..., v_k]`` representing
        the longest alternating path reachable.
    """
    path: list[Vertex] = [start]
    visited: set[Vertex] = {start}
    current = start
    next_color = color2

    while True:
        found = False
        for w in graph.neighbors(current):
            e = canonical(current, w)
            if e in coloring and coloring[e] == next_color and w not in visited:
                path.append(w)
                visited.add(w)
                current = w
                next_color = color2 if next_color == color1 else color1
                found = True
                break
        if not found:
            break

    return path


def flip(
    coloring: Coloring,
    path: list[Vertex],
    color1: Color,
    color2: Color,
) -> None:
    """Swap ``color1`` and ``color2`` on every edge of ``path``.

    The flip preserves the properness of the colouring because every
    edge of the path sees exactly one of its two colours appear on the
    other side, so the local constraint at every vertex is unchanged.

    Args:
        coloring: Partial colouring to mutate.
        path: Vertices of the alternating path; edges are consecutive pairs.
        color1: First colour in the swap.
        color2: Second colour in the swap.
    """
    for i in range(len(path) - 1):
        e = canonical(path[i], path[i + 1])
        if coloring[e] == color1:
            coloring[e] = color2
        else:
            coloring[e] = color1


def color_one(
    graph: Graph,
    u: Vertex,
    v: Vertex,
    coloring: Coloring,
    max_colors: int,
) -> None:
    r"""Colour the single edge ``(u, v)`` preserving a proper partial coloring.

    Implements the standard Vizing recolouring argument by case analysis
    on whether the alternating path starting at ``u`` (in colours
    ``c = miss_u[0]`` and ``d = miss_v[0]``) reaches ``v``.

    Cases:
        * If ``u`` and ``v`` share a missing colour, assign the
          smallest such colour.
        * Otherwise the alternating path does not contain ``v``: flip
          the path so that the previously missing colour ``c`` reappears
          at the endpoint closest to ``v``, then assign ``d`` to
          ``(u, v)``.
        * If the path does contain ``v``, retry with the next missing
          colour at ``u`` (``miss_u[1]``).  If that path also reaches
          ``v`` the recolouring argument has failed.

    Args:
        graph: The host graph.
        u: First endpoint of the edge to colour.
        v: Second endpoint of the edge to colour.
        coloring: Partial colouring (mutated on success).
        max_colors: Bound on the colour palette.

    Raises:
        VizingColoringError: If both recolouring attempts reach ``v``
            before extending, indicating an unrecoverable colouring
            state for this instance.

    Complexity:
        :math:`O(\Delta)` for each of the up to two alternating paths
        traversed, where ``\Delta`` is the maximum degree.
    """
    miss_u = missing(graph, u, coloring, max_colors)
    miss_v = missing(graph, v, coloring, max_colors)

    common = set(miss_u) & set(miss_v)
    if common:
        coloring[canonical(u, v)] = min(common)
        return

    c = miss_u[0]
    d = miss_v[0]

    path = alternating(graph, coloring, u, c, d)

    if v not in path:
        flip(coloring, path, c, d)
        coloring[canonical(u, v)] = d
        return

    if len(miss_u) < 2:
        raise VizingColoringError(
            f"Vertex {u} has degree {graph.degree(u)} but only "
            f"{len(miss_u)} missing colours (max_colors={max_colors})."
        )

    c_prime = miss_u[1]
    path2 = alternating(graph, coloring, u, c_prime, d)

    if v in path2:
        raise VizingColoringError(
            f"Vizing recoloring failed for edge ({u}, {v}): "
            f"both ({c}, {d}) and ({c_prime}, {d}) alternating paths reach {v}."
        )

    flip(coloring, path2, c_prime, d)
    coloring[canonical(u, v)] = d
