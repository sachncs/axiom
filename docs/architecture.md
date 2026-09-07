# Architecture

This document describes the module boundaries of Axiom and the
data flow through the algorithm.

## Module dependency graph

```
                ┌─────────────────────┐
                │    axiom.cli        │  command-line entry point
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │    axiom.core       │  Matcher (orchestrator)
                └─┬──────┬──────┬─────┘
                  │      │      │
        ┌─────────┘      │      └─────────┐
        ▼                ▼                ▼
┌───────────────┐ ┌───────────────┐ ┌─────────────────┐
│  axiom.graph  │ │  axiom.system │ │  axiom.rebuild   │
│  Adjacency    │ │  System +     │ │  Basic + Tiered  │
│               │ │  build/promote│ │                 │
└───────────────┘ │  /switch      │ └────────┬────────┘
                  └───────┬───────┘          │
                          │                  │
                          ▼                  ▼
                  ┌───────────────┐  ┌─────────────────┐
                  │ axiom.hierarchy│  │ axiom.repair     │
                  │ Hierarchy +   │  │ local insert /   │
                  │ check_i3 /    │  │ delete / rematch │
                  │ maintain_i3   │  └─────────────────┘
                  └───────┬───────┘
                          │
                          ▼
                  ┌───────────────┐  ┌─────────────────┐
                  │  axiom.color  │  │  axiom.matching  │
                  │  Colorer +    │  │  greedy, partner │
                  │  Greedy /     │  │  partners,       │
                  │  Vizing       │  │  canonical       │
                  └───────────────┘  └─────────────────┘

                  ┌───────────────┐  ┌─────────────────┐
                  │ axiom.augment │  │  axiom.ledger    │
                  │ augment / flip│  │  Ledger          │
                  └───────────────┘  └─────────────────┘

                  ┌───────────────┐  ┌─────────────────┐
                  │ axiom.invariant│ │ axiom.visualize   │
                  │ invariant     │  │  ASCII renderer  │
                  │ checkers      │  └─────────────────┘
                  └───────────────┘

                  ┌───────────────┐  ┌─────────────────┐
                  │axiom.simulation│ │ axiom.parallel   │
                  │ sequence,     │  │  Benchmark +     │
                  │ replay        │  │  worker, compare │
                  └───────────────┘  └─────────────────┘

                          │
                          ▼
                  ┌───────────────┐
                  │  axiom.types  │  shared vocabulary
                  │  Vertex, Edge,│
                  │  Matching,    │
                  │  Graph Proto, │
                  │  Colorer Proto│
                  └───────────────┘
```

## Algorithm data flow

### `Matcher.__init__(n, mode, graph, colorer, policy)`

1. Validate `n >= 0` and `mode in {"basic", "tiered", "multilevel"}`.
2. Construct `self.graph = Adjacency(n)`, `self.colorer = Greedy()` (or
   the provided colourer).
3. Allocate `matched_edges`, `matched_vertices`, `partners` (empty).
4. Resolve `self.policy`: explicit `policy=` wins, otherwise
   `from_mode(mode)` returns `Basic()` or `Tiered()`.
5. Call `policy.configure(self)` to set `z`, `phase_length`,
   `subphase_length`, `k`, `level_zs`.
6. Call `policy.rebuild(self)` to perform the initial rebuild:
   - `Basic` builds a single `System`, partitions its `M` into colour
     classes, picks `seed_matching = matchings[0]`, then calls
     `Matcher.refresh()` to extend the seed to a maximal matching.
   - `Tiered` builds `k` independent `System` levels, splits the
     level-1 `A` into `A1/A2`, derives `N1 = A2 | B` and
     `R1 = V \ (A1 | N1)`, sets `system` to the innermost level, then
     calls `Matcher.refresh()`.

### `Matcher.insert(u, v)`

```
graph.add_edge(u, v)
    │
    ▼
__handle_insertion(u, v)
    │ try the (A, U) fast path: if either endpoint is in A and the
    │ other in U and the U-endpoint is currently matched and the
    │ A-endpoint is unmatched, swap their matches.
    │ otherwise
    ▼
refresh() [only if not maximal after fast path]
    │
    ▼
__advance_update_counter()
    │ increment update_count
    │ check subphase boundary -> augment() (public)
    │ check i3 -> maintain_i3() (public)
    ▼
if update_count >= phase_length:
    policy.rebuild(self)
```

### `Matcher.delete(u, v)`

```
if graph.has_edge(u, v):
    graph.remove_edge(u, v)
        │
        ▼
    __handle_deletion(u, v)
        │ if (u, v) was in matched_edges: drop_match(u, v)
        │ __cleanup_stale_edges()
        │ __rematch_vertex(u), __rematch_vertex(v)
        │ __cleanup_stale_edges()
        │ if not maximal: refresh()
        ▼
    __advance_update_counter()
else:
    accountant.record_deletion() (no-op)
```

### `Matcher.refresh()`

If `system is None`, run `greedy(graph)` and rebuild `partners` from
the result.

Otherwise, start from `seed_matching`, greedily extend to a maximal
matching over `graph`, drop any duplicate-vertex edges from the seed
first, and rebuild `partners` from the resulting `matched_edges`.

### `policy.rebuild(matcher)`

`Basic.rebuild`:

```
system = build(graph, z)
partition()                # colour M into z+1 matchings
refresh()                  # extend seed to maximal M*
update_count = subphase_count = 0
accountant.record_phase_rebuild()
```

`Tiered.rebuild`:

```
multi = Hierarchy(graph=graph, k=k)
for z in level_zs:
    multi.levels.append(build(graph, z))
# split level-1 A into A1/A2, derive N1, R1
system = multi.levels[-1]        # innermost level
z = level_zs[-1]
partition()
refresh()
update_count = subphase_count = 0
accountant.record_phase_rebuild()
```

### `Matcher.augment()` (public, was `__augment_seed_at_subphase_boundary`)

For every vertex in `system.S` that is currently unmatched in the seed
matching, run `try_augment` (a BFS over alternating paths). Return the
number of paths applied.

### `Matcher.try_augment(start, matched)` (public)

Delegate to `axiom.augment.augment(seed_matching, graph.neighbors, start, matched.__contains__)`.

### `Matcher.flip(path)` (public)

Delegate to `axiom.augment.flip(seed_matching, path)`.

### `Hierarchy.check_i3(matching, r, z)` (public)

Return True iff at most `2 * tau = 64 * r / z` edges of `matching`
cross between `A1` and `R1`.

### `Hierarchy.maintain_i3(matching, r, z, partner_of, rematch)`

Break up to `2 * tau` offending `(A1, R1)` edges and call
`rematch(endpoint)` on each endpoint. Used by `Matcher.maintain_i3()`
which is called after every update in tiered mode.

## State held by Matcher

| Field | Type | Purpose |
|---|---|---|
| `n` | `int` | vertex count (fixed) |
| `mode` | `str` | `"basic"` or `"tiered"` |
| `graph` | `Adjacency` | underlying dynamic graph |
| `colorer` | `Colorer` | used to colour `M` for partitioning |
| `matched_edges` | `Matching` (`set[Edge]`) | the reported maximal matching |
| `matched_vertices` | `set[Vertex]` | cache of matched vertices |
| `partners` | `dict[Vertex, Vertex]` | O(1) partner map, kept in lockstep with `matched_edges` |
| `z` | `int` | current degree parameter |
| `phase_length` | `int` | updates between full rebuilds |
| `subphase_length` | `int` | updates between seed augmentations |
| `update_count` | `int` | updates since last rebuild |
| `subphase_count` | `int` | subphase augmentations performed |
| `system` | `System \| None` | active single-level system (or innermost level) |
| `matchings` | `list[Matching]` | colour classes of the most recent colouring |
| `seed_matching` | `Matching` | first colour class, kept as the seed |
| `multi` | `Hierarchy \| None` | multi-level system, present in `"tiered"` mode |
| `level_zs` | `list[int]` | per-level `z` values in decreasing order |
| `k` | `int` | number of levels |
| `accountant` | `Ledger` | bookkeeping counters |

## Strategy pattern: Rebuild Policy

The `Rebuild` Protocol has two implementations:

```
class Rebuild(Protocol):
    name: str
    def configure(matcher): ...     # set z, phase_length, etc.
    def rebuild(matcher): ...        # full z-system rebuild
```

`Basic` is the single-level `&Otilde;(n^{2/3})` strategy; `Tiered`
is the multi-level `n^{1/2+o(1)}` strategy. The Matcher holds one
instance and delegates both configuration and rebuilding. This makes
the algorithm pipeline traceable: every phase boundary hits
`policy.rebuild(self)`, every construction step hits
`policy.configure(self)`.

## Single responsibility

| Concern | Module |
|---|---|
| Graph storage | `axiom.graph` |
| Single-level z-system | `axiom.system` |
| Multi-level hierarchy | `axiom.hierarchy` |
| Edge colouring | `axiom.color` |
| Phase rebuild policy | `axiom.rebuild` |
| Local repair | `axiom.repair` |
| Augmenting-path search | `axiom.augment` |
| Empirical counters | `axiom.ledger` |
| Invariant validation | `axiom.invariant` |
| Update sequences | `axiom.simulation` |
| Parallel benchmarks | `axiom.parallel` |
| ASCII visualisation | `axiom.visualize` |
| Type vocabulary | `axiom.types` |
| CLI entry point | `axiom.cli` |

Pure logic is kept separate from I/O. The CLI module does no work
besitself the orch argument and to print; the benchmark module is the
only one that does parallel I/O.