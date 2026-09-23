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
│  Adjacency    │ │  System +     │ │ Basic + Multilevel│
│               │ │  build/promote│ │                 │
└───────────────┘ │  /switch      │ └────────┬────────┘
                  └───────┬───────┘          │
                          │                  │
                          ▼                  ▼
                   ┌───────────────┐  ┌─────────────────┐
                   │ axiom.hierarchy│  │ axiom.core       │
                   │ Hierarchy +   │  │ Matcher: local   │
                   │ System/       │  │ insert/delete/   │
                   │ maintain_i3   │  │ rematch dispatch │
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
                  │ axiom.matching │ │ axiom.visualize   │
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

### `Matcher.__init__(n, mode, graph, colorer)`

1. Validate `n >= 0` and `mode in {"basic", "multilevel"}`.
2. Construct `self.graph = Adjacency(n)`. The default colourer is `Vizing()`
   for `basic` and `PaperFanColorer()` for `multilevel` (or the provided
   colourer).
3. Allocate `matched_edges`, `matched_vertices`, `partners` (empty).
   The matcher also maintains the paper's directed `H`, reverse-`H`,
   `H_tilde`, and `S_hat` indexes from the live matching state.
4. Resolve the internal rebuild policy from the canonical mode:
   `basic` selects `Basic()` and `multilevel` selects `Multilevel()`.
5. Call `policy.configure(self)` to set `z`, `phase_length`,
   `subphase_length`, `k`, `level_zs`.
6. Call `policy.rebuild(self)` to perform the initial rebuild:
   - `Basic` builds a single `System`, partitions its `M` into colour
     classes, picks `seed_matching = matchings[0]`, then calls
     `Matcher.refresh()` to extend the seed to a maximal matching.
   - `Multilevel` recursively derives `k` levels, retains inherited
     regions and lists, uses the configured `colorer` for every recursive
     edge partition, sets `system` to the innermost level, then
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
    │ check subphase boundary -> internal augmentation
    │ check i3 -> internal I3 repair
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

Start from `seed_matching`, verify that it is a valid matching over
`graph`, greedily extend it to a maximal matching, and rebuild `partners`
from the resulting `matched_edges`.  An invalid seed is a hard invariant
failure; it is never silently repaired.

### `policy.rebuild(matcher)`

`Basic.rebuild`:

```
system = build(graph, z)
partition()                # colour M into z+1 matchings
refresh()                  # extend seed to maximal M*
update_count = subphase_count = 0
accountant.record_phase_rebuild()
```

`Multilevel.rebuild`:

```
multi = build_hierarchy(graph, level_zs)
system = multi.levels[-1]        # innermost level
z = level_zs[-1]
partition()
refresh()
update_count = subphase_count = 0
accountant.record_phase_rebuild()
```

### `Hierarchy.check_i3(matching, r, z)` (public)

Return True iff at most `2 * tau = 64 * r / z` edges of `matching`
cross between `A1` and `R1`.

### `Hierarchy.maintain_i3(matching, r, z, partner_of, rematch)`

Break up to `2 * tau` offending `(A1, R1)` edges and call
`rematch(endpoint)` on each endpoint. The matcher invokes this internally
after every update in multilevel mode.

## State held by Matcher

| Field | Type | Purpose |
|---|---|---|
| `n` | `int` | vertex count (fixed) |
| `mode` | `str` | `"basic"` or `"multilevel"` |
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
| `multi` | `Hierarchy \| None` | multi-level system, present in `"multilevel"` mode |
| `level_zs` | `list[int]` | per-level `z` values in decreasing order |
| `level_phase_lengths` | `list[int]` | per-level `z_i · eta` phase budgets |
| `eta` | `int` | power-of-two scheduler scale |
| `H`, `H_reverse`, `H_tilde` | directed indexes | rematching indexes for live and inserted edges |
| `S_hat` | `set[Vertex]` | unmatched saturated vertices |
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

`Basic` is the single-level paper-target strategy; `Multilevel`
is the recursive multi-level construction. The implementation does not claim
the paper's asymptotic bounds until its deferred colouring and update pieces
are complete. The Matcher holds one
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
| Local repair | `axiom.core` (private `__handle_insertion`, `__handle_deletion`, `__rematch_*`) |
| Augmenting-path search | `axiom.augment` |
| Empirical counters | `axiom.ledger` |
| Invariant validation | `System.check`, `Hierarchy.check` |
| Update sequences | `axiom.simulation` |
| Parallel benchmarks | `axiom.parallel` |
| ASCII visualisation | `axiom.visualize` |
| Type vocabulary | `axiom.types` |
| CLI entry point | `axiom.cli` |

Pure logic is kept separate from I/O. The CLI module does no work besides
parsing arguments and printing results; the benchmark module is the only one
that drives parallel I/O.
