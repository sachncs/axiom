# ADR 0092: Discover paper partition components from live edges

Date: 2026-10-04
State: Implemented; global partition-bound scans remain

## Context

`Paper.partition` initialized component discovery with `set(range(n))`, then
visited every vertex and asked the graph for its neighbors, including all
isolates. The partition only emits edges and builds components containing live
edges. On sparse graphs with a large declared universe, the vertex set and
isolate traversal were unnecessary O(n) Python state/work before the Euler
partition began.

## Decision

Seed the unseen-vertex set from the endpoints in the already-materialized edge
list. Every discovered component is therefore nonempty and can be retained
directly. Root selection, component traversal, edge ordering, odd-degree dummy
pairing, Euler tours, and output assignment order remain unchanged. The later
global maximum-degree and per-output degree-bound scans are deliberately
retained; this decision removes the isolate-only discovery pass, not all O(n)
work in the function.

## Correctness evidence

A sparse `Packed` regression checks the exact number of full-universe `range`
scans (only the existing degree-bound and output-bound checks remain), verifies
the output edge sets are disjoint, and verifies their union is the original
edge set. The K34 seed palette-reduction regression also uses this partition
path and certifies the resulting complete coloring.

## Measurement and limits

Three alternating before/after runs partitioned the same 2,048-label `Packed`
graph with three edges (two components, 2,045 isolated vertices). Output edge
sets matched in every run. Baseline times were 28.115, 28.921, and 28.229 ms;
candidate times were 0.305, 0.288, and 0.288 ms. Median elapsed time fell from
28.229 ms to 0.288 ms (98.98%). Median traced peak fell from 192,360 to 3,264
bytes (98.30%). This isolated shape demonstrates isolate-discovery cost, not
large connected-graph behavior, full Paper.color throughput, RSS, or durable
service qualification. Remaining global degree-bound scans dominate as the
vertex universe grows.

## Alternatives

- Scan every vertex: rejected because isolates cannot participate in the edge
  partition and cost O(n) before useful work.
- Keep an ordered endpoint list and deduplicate by sorting: rejected because a
  set already gives deterministic root selection through `min(unseen)` and the
  live endpoints are already bounded by the edge count.
- Remove the final degree-bound scans: rejected; they independently certify
  the parity partition contract and are outside this optimization.

## Follow-up

Profile the remaining O(n) degree-bound scans and choose a graph backend
primitive that preserves the independent degree guarantee without paying a
Python call per vertex. Continue paper snapshot migration and durable-mode
integration separately.
