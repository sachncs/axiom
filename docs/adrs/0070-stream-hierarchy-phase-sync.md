# ADR 0070: Stream hierarchy phase synchronization without edge-set copies

Date: 2026-10-03  
State: Implemented; broad phase-boundary qualification remains open

## Context

When rebuilding a hierarchy phase graph, `Hierarchy.sync_graph` added deferred
edges and live edges to a new graph, then materialized
`set(phase_graph.edges())` only to prune matching edges in each System. This
created an additional Python tuple/hash-table copy proportional to all phase
edges. Built-in `Adjacency` and `Packed` graphs enumerate canonical edges in
deterministic order; deferred edges are a set and can be sorted once for a
two-way merge.

## Decision

For built-in graphs, merge sorted deferred edges with the ordered live-edge
stream, exclude current inserted edges, and collapse duplicate edges as they
arrive. Preserve the input backend through `empty(graph)`. Pass the resulting
phase graph directly to `System.restrict`, which checks matching liveness with
graph membership. Opaque custom Graph implementations retain the previous
add-and-deduplicate fallback. Deferred edges remain included even if absent
from the live graph.

## Correctness and failure behavior

The synchronization regression checks deferred-edge retention, full hierarchy
validity and that every matching restriction receives the exact published
phase graph rather than a detached edge set. A custom non-native Graph test
exercises the fallback with reverse edge order. The full suite independently
checks update rollback and hierarchy certificates.

## Evidence and limits

Three traced `sync_graph` repeats compare source `3b9928d` with the candidate
on a 50,000-vertex/50,000-edge `Packed` ring and a 25,000-edge perfect
matching. Graph construction is outside the timed/traced region. Median time
fell from 0.613 s to 0.401 s (34.5%); peak traced Python allocation fell from
18,343,280 to 7,770,424 bytes (57.6%). Both variants passed `System.check()`
and produced identical 50,000-edge phase graphs and 25,000-edge matching
states. This excludes native graph allocation and process RSS. See the
[raw comparison](../benchmarks/results/paper/phase-sync-streaming.json).

Passing a graph to `System.restrict` trades the removed edge-set allocation for
one graph membership lookup per matching edge. This measured ring is sparse;
broader degree/skew and phase-boundary workloads are still required.

## Alternatives

- Build a Python edge set for constant-time matching cuts: rejected for the
  extra O(m) tuple/hash storage at every full synchronization.
- Use sorted merging for arbitrary Graph implementations: rejected because
  the protocol does not guarantee ordered iteration; keep the compatibility
  fallback instead.
- Omit deferred edges absent from the live graph: rejected because deferred
  deletions are intentionally retained in the phase graph.

## Follow-up

Measure phase synchronization within complete rebuild traces over sparse and
dense partitions, with native allocation and process RSS recorded separately.
