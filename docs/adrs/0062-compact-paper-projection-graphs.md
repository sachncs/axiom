# ADR 0062: Use compact graph storage for paper projection snapshots

Date: 2026-10-03  
State: Implemented; broader paper-engine qualification remains open

## Context

After sparse coloring indexes removed per-vertex empty color sets, recursive
`Extension.project` still created an isolated `Adjacency` child whenever the
input used the Python reference backend. `Adjacency(n)` allocates an empty Python
set for every vertex. A million-vertex child with only two edges therefore
retained roughly 224 MB in empty rows, dominating the projection's remaining
memory.

## Decision

For paper color-group projections, an `Adjacency` source now produces an isolated
native `Packed` child graph. A `Packed` source continues to use `Packed.empty()`,
which preserves the configured native budget. Opaque custom graph implementations
continue through `graph.empty()`'s documented reference-backend fallback. This
is scoped to private recursive coloring subgraphs; the caller's graph is neither
converted nor mutated.

## Guarantees and limits

The child still contains exactly the selected color-group edges and owns its
storage independently. Edge iteration and neighbor ordering remain deterministic.
The public `Adjacency` implementation and general `empty(graph)` contract are
unchanged. Native allocation is separately budgeted and is not included in
`tracemalloc`; inspect `Packed.memory()` and process RSS for complete accounting.
This change does not imply the Python reference graph or paper hierarchy is
billion-vertex ready, and it does not transfer native Matcher throughput results
to paper modes.

## Evidence

- On the same one-million-vertex source and two-edge projection, the sparse
  `Adjacency` child from ADR 0061 peaked at 224,457,760 traced bytes and took
  1.0287 s under tracing. The compact child peaked at 8,784 traced bytes and
  took 0.0009 s; its reported native allocation was 13,000,456 bytes (four live
  blocks). Combined incremental allocation in this measurement was about
  13.01 MB, 94.2% below the reference child. The source graph was prepared
  outside tracing, so this is projection cost, not process RSS.
- Tests verify edge-scope isolation for `Adjacency` inputs, native-budget
  preservation for `Packed` inputs, complete proper child coloring behavior, and
  existing custom graph fallback coverage elsewhere in the suite.

See the [raw comparison](../benchmarks/results/paper/packed-projection.json).

## Alternatives

- Keep an `Adjacency` child for an `Adjacency` parent: rejected for these internal
  snapshots because it creates a million object rows unrelated to scoped edges.
- Change the public `Adjacency` row representation: rejected in this scoped
  change because callers and tests use its public mutable `adj` list.
- Share the source graph: rejected because later recursive path operations must
  be isolated from edges outside the color-group scope.

## Follow-up

Exercise recursive extension workloads under native-memory limits, include
`Packed.memory()` and process RSS, test native allocation failure rollback, and
retain compatibility tests for opaque graph implementations.
