# ADR 0064: Stream native hierarchy projections

Date: 2026-10-03  
State: Implemented for built-in graphs; custom graph fallback retained

## Context

ADR 0063 removed the live-edge and working-graph-membership copies but retained
one `working_edges` set because `project` sorted an edge set to guarantee
deterministic insertion. For built-in `Adjacency` and `Packed`, the graph edge
iterators already yield canonical edges in strictly increasing order. The
phase graph can therefore be filtered as a stream, and the independently sorted
inserted batch can be merged into it without storing the full phase edge set.

## Decision

`project` accepts an iterable plus an explicit ordered-stream contract. In
ordered mode it verifies strict increase while inserting; unordered callers
retain the sorted compatibility behavior. Refinement on built-in graphs filters
deleted edges while streaming the existing graph and merges sorted inserted
edges. Opaque custom graphs retain a set plus the sorted fallback because their
iterator order is not guaranteed. Projection from reference `Adjacency` creates
an isolated `Packed` graph; a `Packed` source retains its budget.

## Guarantees and limits

The working graph edge set is the same as the prior set expression:
phase-graph edges excluding non-deferred deletions, plus inserted edges. Deferred
deletions remain when selected. Ordered mode rejects duplicate or unsorted input
rather than silently producing nondeterministic state. Memory for the common
path is now O(batch insertions) Python scratch plus the output graph, rather than
an additional O(E) Python set and sorted list. The opaque custom-graph fallback
still materializes state-sized sets. The hierarchy algorithm, working graph,
working System, and level state remain substantial and still require resource
qualification.

## Evidence

- A 100,000-vertex `Packed` ring with 200,000 edges was projected in one
  isolated `tracemalloc`-instrumented sample per path.
- Materializing a Python edge set and then using the sorted projection path used
  36,356,048 traced peak bytes and 0.444 s. Passing the ordered native edge
  stream directly used 448 traced peak bytes and 0.146 s. Both output graphs
  reported the same 4,445,992 bytes native allocation and passed `Packed.check()`.
- Regression tests cover both built-in backends, strict-order rejection,
  independent child ownership, inserted/deleted refinement equivalence through
  existing hierarchy tests, and graph-backed matching-cut rollback.

See the [raw measurement](../benchmarks/results/paper/stream-projection.json).

## Alternatives

- Keep a Python set and sort it: rejected for built-in sources with ordered edge
  streams.
- Assume every custom graph is ordered: rejected because `Graph` does not promise
  iteration order for opaque implementations.
- Remove runtime order checks: rejected because an invalid stream could change
  deterministic tie-breaking silently.

## Follow-up

Measure full multilevel rebuild/refinement peak RSS and native memory under
representative sizes, deletions, insertions, and deferred-edge cases. Migrate
remaining hierarchy working-graph/System copies and multi-source A/N/R unions
with exact owner-journal rollback; this commit only removes redundant edge
materialization.
