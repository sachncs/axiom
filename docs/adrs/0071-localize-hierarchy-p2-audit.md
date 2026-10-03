# ADR 0071: Localize the hierarchy matching P2 audit

Date: 2026-10-03  
State: Implemented; broad certificate qualification remains open

## Context

`Hierarchy.check()` verified each A-level vertex's matching restriction by
rescanning the entire finest-level matching. If A has O(n) vertices and M has
O(n) edges, this costs O(n|M|), even when the graph is sparse. The graph and
matching are already independently checked, and the Graph contract exposes
each vertex's incident edges.

## Decision

For each vertex in each disjoint A-level partition, inspect its graph neighbors
and test canonical-edge membership in the finest matching. Apply the same
lower-A-prefix-or-N condition for every matching edge incident to that vertex.
This retains the full P2 certificate but changes traversal work to the incident
edges of A-level vertices, O(m) total for disjoint level partitions, plus
constant-time matching membership tests. It allocates no matching-partner map.

## Correctness

Every edge in the finest matching is checked as live before this P2 pass. For a
valid Graph implementation, iterating a vertex's neighbors enumerates every
live incident edge; membership in the matching therefore finds exactly the
same relevant edges as scanning the whole matching and filtering by endpoint.
The lower-level and N-level predicates remain unchanged. A counted matching
regression guards against reintroducing per-vertex full matching iteration;
existing deliberate corruption tests and randomized hierarchy checks retain
the negative certificate coverage.

## Evidence and limits

On a 1,024-vertex Packed cycle with 512 matching edges, both the prior and
candidate checker returned `True`; five alternating repeats measured median
check time of 15.58 ms prior versus 2.86 ms candidate (5.45x). On a 50,000-
vertex/25,000-matching-edge cycle, the candidate full hierarchy certificate
returned `True` in 142 ms. The prior nested scan did not complete within a
90-second diagnostic run; its stack was inside the per-A-vertex matching scan,
so that run is not reported as a completed baseline timing. The graph shape
uses one A-level partition with all vertices in A; it is an adversarial audit
shape, not a production rebuild rate. See the
[raw comparison](../benchmarks/results/paper/hierarchy-check-p2.json).

## Alternatives

- Keep the global matching scan for every A vertex: rejected due its
  O(n|M|) sparse-graph behavior.
- Build a full matching partner index: rejected because graph adjacency gives
  the local candidate edges without another O(n) allocation and cache.
- Remove P2 validation or defer it to occasional audits: rejected; the full
  immediate certificate remains mandatory.

## Follow-up

Profile full `Hierarchy.check()` on multilevel sparse/dense and skewed graphs.
Retain graph-consistency audits so custom implementations cannot claim an edge
through `has_edge` while omitting it from neighbor iteration.
