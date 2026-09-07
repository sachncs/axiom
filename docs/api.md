# API Reference

This is the complete public surface of Axiom. All names below are
exported from `axiom.__init__`. There is no semi-private naming: every
helper that exists in the package is either in this list or in a
sub-module's public surface (which can be imported by qualified name).

## Core

```python
class Matcher:
    def __init__(
        n: int,
        mode: str = "basic",
        graph: Graph | None = None,
        colorer: Colorer | None = None,
        policy: Rebuild | None = None,
    ) -> None: ...

    # Update pipeline
    def insert(self, u: Vertex, v: Vertex) -> None: ...
    def delete(self, u: Vertex, v: Vertex) -> None: ...

    # Query
    def matching(self) -> Matching: ...       # copy of M*
    def maximal(self) -> bool: ...            # is M* maximal in graph?
    def size(self) -> int: ...                # |M*|
    def partner(self, v: Vertex) -> Vertex | None: ...  # O(1) via partner dict
    def partners(self) -> dict[Vertex, Vertex]: ...      # full partner map
    def stats(self) -> dict[str, int]: ...    # empirical counters

    # Augmenting-path API (public, promoted from private in v0.5.0)
    def augment(self) -> int: ...             # subphase-boundary augmentation; returns count
    def try_augment(self, start: Vertex, matched: set[Vertex]) -> bool: ...
    def flip(self, path: list[Vertex]) -> None: ...

    # Maintenance
    def partition(self) -> None: ...          # partition M into z+1 colour classes
    def refresh(self) -> None: ...            # rebuild M* from seed (or greedy fallback)
    def maintain_i3(self) -> int: ...         # tiered mode only; returns # of A1->R1 breaks

    # Internal state (read-only by convention)
    n: int
    mode: str
    graph: Adjacency
    colorer: Colorer
    matched_edges: Matching
    matched_vertices: set[Vertex]
    partners: dict[Vertex, Vertex]
    z: int
    phase_length: int
    subphase_length: int
    update_count: int
    subphase_count: int
    system: System | None
    matchings: list[Matching]
    seed_matching: Matching
    multi: Hierarchy | None
    level_zs: list[int]
    k: int
    policy: Rebuild
    accountant: Ledger
```

## Graph

```python
class Adjacency:
    def __init__(self, n: int) -> None: ...
    def add_edge(self, u: Vertex, v: Vertex, *, strict: bool = False) -> None: ...
    def remove_edge(self, u: Vertex, v: Vertex, *, strict: bool = False) -> None: ...
    def has_edge(self, u: Vertex, v: Vertex) -> bool: ...
    def degree(self, v: Vertex) -> int: ...
    def neighbors(self, v: Vertex) -> Iterator[Vertex]: ...
    def edges(self) -> Iterator[Edge]: ...
    def num_count: int    # cached
    def validate_vertex(self, v: Vertex) -> None: ...
    def copy(self) -> Adjacency: ...

class Graph(Protocol):
    n: int
    def add_edge(self, u: Vertex, v: Vertex) -> None: ...
    def remove_edge(self, u: Vertex, v: Vertex) -> None: ...
    def has_edge(self, u: Vertex, v: Vertex) -> bool: ...
    def degree(self, v: Vertex) -> int: ...
    def neighbors(self, v: Vertex) -> Iterator[Vertex]: ...
    def edges(self) -> Iterator[Edge]: ...
    def num_count: int
```

## Systems

```python
@dataclass
class System:
    graph: Graph
    z: int
    A: set[Vertex]
    B: set[Vertex]
    U: set[Vertex]
    M: set[Edge]
    lambda_lists: dict[Vertex, list[Vertex]]
    L_lists: dict[Vertex, list[Vertex]]

    @property
    def S(self) -> set[Vertex]: ...            # A | B
    @property
    def V(self) -> set[Vertex]: ...            # full vertex set

    def degree(self, v: Vertex) -> int: ...    # in M
    def partner_in(self, v: Vertex) -> Iterator[Vertex]: ...
    def check_bound(self) -> bool: ...         # degree bounds in M
    def check_u(self) -> bool: ...            # U-U degree bound
    def check_p1(self) -> bool: ...           # P1
    def check_p2(self) -> bool: ...           # P2
    def check_lambda(self) -> bool: ...        # &Lambda; lists correct
    def check_L(self) -> bool: ...            # &L; lists correct
    def check(self) -> bool: ...              # all six invariants
    def index(self) -> None: ...              # rebuild &Lambda; and &L;
    def maximal(self, matching: Matching) -> bool: ...

def build(graph: Graph, z: int) -> System: ...
def switch(graph: Graph, M: set[Edge], deg_M: dict[Vertex, int],
          z: int, u: Vertex, b_neighbors: list[Vertex]) -> bool: ...
def promote(graph: Graph, system: System, M: set[Edge],
            deg_M: dict[Vertex, int], z: int, u: Vertex) -> bool: ...

@dataclass
class Hierarchy:
    graph: Graph
    k: int
    levels: list[System]
    A1: set[Vertex]
    A2: set[Vertex]
    N1: set[Vertex]
    R1: set[Vertex]

    def check_i3(self, matching: Matching, r: int, z: int) -> bool: ...
    def maintain_i3(self, matching: Matching, r: int, z: int,
                    partner_of: callable, rematch: callable) -> int: ...

def build_hierarchy(graph: Graph, level_zs: list[int]) -> Hierarchy: ...
```

## Colorers

```python
class Colorer(Protocol):
    def color(self, graph: Graph, delta: int) -> Coloring: ...

class Greedy:
    """Degree-ordered greedy colourer. O(m * &Delta;) worst case."""

class Vizing:
    """Vizing's alternating-path colourer with backtracking fallback."""

class VizingColoringError(RuntimeError): ...

def recolor(graph, coloring, vertex_colors, u, v, max_colors) -> bool: ...
def find(graph, coloring, v, c) -> Edge | None: ...
def backtrack(graph, edges, idx, coloring, max_colors) -> bool: ...
def missing(graph, vertex, coloring, max_colors) -> list[Color]: ...
def alternating(graph, coloring, start, color1, color2) -> list[Vertex]: ...
def flip(coloring, path, color1, color2) -> None: ...
def color_one(graph, u, v, coloring, max_colors) -> None: ...
```

## Matching helpers

```python
def canonical(u: Vertex, v: Vertex) -> Edge: ...
def greedy(graph: Graph) -> Matching: ...
def is_maximal_matching(graph: Graph, matching: Matching) -> bool: ...
def partner_in(matching: Matching, v: Vertex) -> Vertex | None: ...
def partners(matching: Matching) -> dict[Vertex, Vertex]: ...
```

## Rebuild strategy

```python
class Rebuild(Protocol):
    name: str
    def configure(matcher: Matcher) -> None: ...
    def rebuild(matcher: Matcher) -> None: ...

class Basic: ...
class Tiered: ...

def from_mode(mode: str) -> Rebuild: ...
```

## Augmenting path utilities

```python
def flip(coloring: set[Edge], path: list[Vertex]) -> None: ...
def augment(matching: set[Edge], neighbors: callable, start: Vertex,
           is_matched: callable) -> bool: ...
```

## Ledger

```python
@dataclass
class Ledger:
    total_updates: int
    total_insertions: int
    total_deletions: int
    phase_rebuilds: int
    subphase_rebuilds: int
    rematch_u_scans: int
    rematch_b_scans: int
    rematch_a_scans: int
    greedy_rebuilds: int
    stale_cleanups: int

    def record_insertion(self) -> None: ...
    def record_deletion(self) -> None: ...
    def record_phase_rebuild(self, work_estimate: int = 0) -> None: ...
    def record_subphase_rebuild(self, work_estimate: int = 0) -> None: ...
    def record_rematch_u_scan(self, scanned: int = 1) -> None: ...
    def record_rematch_b_scan(self, scanned: int = 1) -> None: ...
    def record_rematch_a_scan(self, scanned: int = 1) -> None: ...
    def record_greedy_rebuild(self, work: int = 0) -> None: ...
    def record_stale_cleanup(self, count: int = 1) -> None: ...
    def snapshot(self) -> dict[str, int]: ...
```

## Invariant validators

```python
def is_maximal_matching(graph: Graph, matching: Matching) -> bool: ...
def valid(system: System) -> bool: ...
def check_i3(hierarchy: Hierarchy, matching: Matching, r: int, z: int) -> bool: ...
```

## Simulation

```python
Update = tuple[str, Vertex, Vertex]

def random_updates(n: int, steps: int, rng: random.Random,
                   existing: set[tuple[int, int]] | None = None) -> Iterator[Update]: ...
def replay(matcher: Matcher, updates: list[Update]) -> None: ...
```

## Parallel benchmarking

```python
@dataclass
class Benchmark:
    n: int
    mode: str
    updates: int
    elapsed_sec: float
    updates_per_sec: float
    matching_size: int
    is_maximal: bool
    phase_rebuilds: int
    subphase_rebuilds: int

def worker(n: int, mode: str, updates: int, seed: int) -> Benchmark: ...
def run_parallel(configs: list[tuple[int, str, int, int]],
                 max_workers: int | None = None) -> list[Benchmark]: ...
def compare(n: int, updates: int, seed: int = 42,
           max_workers: int | None = None) -> dict[str, Benchmark]: ...
```

## Visualization

```python
def visualize_system(system: System, width: int = 60) -> str: ...
def visualize_matching(matcher: Matcher, width: int = 60) -> str: ...
def visualize_adjacency(matcher: Matcher, width: int = 60) -> str: ...
```

## Types

```python
Vertex = int
Edge = tuple[Vertex, Vertex]
Matching = set[Edge]
Color = int
Coloring = dict[Edge, Color]

class Graph(Protocol): ...
class class Vector(Protocol): ...

class Colorer(Protocol): ...
```

## CLI

```python
def main(argv: list[str] | None = None) -> int: ...
```