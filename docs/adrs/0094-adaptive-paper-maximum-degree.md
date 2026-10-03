# ADR 0094: Adapt maximum-degree scans to graph sparsity

Date: 2026-10-04
State: Implemented; recursive high-degree seed qualification remains

## Context

`Paper.color` rejected an insufficient `delta` only after checking every label
in `range(n)`. `Paper.seed` repeated the same full-universe scan at each
recursive partition level to calculate child degree bounds. On sparse graphs
with many isolates this work depends on the declared universe, not the live
edge set. Conversely, scanning endpoints for every edge in a dense graph would
query high-degree vertices repeatedly.

## Decision

Centralize the operation in `Paper.maximum`. When `2*m < n`, stream both
endpoints of each edge and take the largest incident degree. This performs at
most `2*m` degree calls and needs no endpoint set or other graph-sized scratch.
Otherwise, scan the vertex universe once, bounding degree calls by n. Use this
same selection for the public colorer precondition and both recursive child
palette bounds. Isolates have degree zero, so omitting them cannot change the
maximum, including for an empty graph.

## Correctness evidence

The sparse regression verifies the exact maximum on a 100,000-label graph with
three edges and requires no universe scan. The dense regression constructs a
complete eight-vertex graph and verifies the maximum as well as the retained
single universe scan. Existing low-delta rejection, random graph, and K34
recursive seed tests exercise the callers and palette bounds.

## Measurement and limits

Five alternating probes on the same 100,000-label `Packed` graph with three
edges compared the previous `max(degree(v) for v in range(n))` with
`Paper.maximum`. Both returned degree 2. Baseline median was 3.760 ms; candidate
median was 0.302 ms (91.97% lower). Median traced scratch was 408 bytes before
and 536 bytes after, a 128-byte increase. This is a maximum-degree component
probe only; it does not measure complete coloring, recursive rebuild behavior,
process RSS, or service performance. The crossover is an operation-count rule,
not a universally benchmarked runtime optimum.

## Alternatives

- Always scan all labels: rejected for sparse graphs with a large universe.
- Always scan endpoints: rejected because dense graphs can cause up to 2m
  repeated degree queries instead of n.
- Build an endpoint set: rejected because it adds O(active vertices) Python
  storage when the edge stream can be consumed directly.
- Add active-vertex enumeration to the public Graph protocol: rejected for this
  bounded optimization because edge streaming already supplies the needed
  candidates without imposing a new method on custom Graph implementations.

## Follow-up

Measure recursive `Paper.seed` on large sparse high-degree graphs and connected
near-threshold graphs. Continue the remaining paper state snapshot migration,
then add exact paper-mode persistence and independent durable qualification.
