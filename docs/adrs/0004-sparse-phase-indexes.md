# ADR 0004: Allocate phase overlay indexes only for participating vertices

Date: 2026-10-01. Status: implemented and regression-tested in `48353b9`; full-scale qualification pending.

## Context

The matcher allocated `inserted_incident_edges[v] = set()` and
`inserted_incident_counts[v] = 0` for every vertex, including basic mode where
these multilevel overlay maps remain unused. Every snapshot copied those entries;
the validator and parent reset allocated/scanned all vertices again. Coloring
validation similarly created empty color sets for every vertex even when only a
small subgraph was colored.

## Decision

Use canonical sparse dictionaries. Incident edge buckets exist only for live
`E_I` endpoints; remove a bucket when its last edge is removed. Missing buckets
mean no inserted edges. Missing insertion counters mean zero. Counters continue
to accumulate insertion events within the parent phase—they are **not** decremented
on deletion or derived from current live bucket sizes. Clear the sparse maps at
the actual parent boundary; child rebuilds preserve their parent-phase scope.

Reconstruct the validator's expected map from live inserted edges and require exact
dictionary equality. Extra empty/nonempty buckets are corruption, not silently
ignored. Coloring conflict checks allocate color buckets for colored endpoints
only; complete/proper/palette checks remain mandatory. Code/tests inspecting
removed incident buckets must use membership or `.get`, not assume dense keys.

## Consequences and alternatives

Memory and copy/reset work depend on overlay participation rather than vertex
universe size. This does not eliminate remaining full matcher snapshots or
global validators. Keeping touched-but-empty buckets indefinitely was rejected
because churn would recreate the original retained-memory problem. Disabling
overlay consistency checks was rejected.

## Evidence

Identical 512-vertex sparse-degree-4 churn traces (seeds 7, 29, 101; 32 real calls;
five fresh repetitions) improved median basic rate from 327.7 to 509.0 updates/s.
Trace digests and final independent matching certificates agree. Traced peaks
fell from approximately 1.79–1.85 MB to 1.29–1.33 MB; per-seed ordinary p99 samples
also decreased. These short results do not qualify steady-state/million throughput
or reach the earlier provisional 2× gate. Raw before/after evidence is in
`benchmarks/results/sparse-index-before/` and `sparse-index-after/`.

Tests exercise canonical bucket bounds/lifecycle, basic-mode empty overlays,
native/reference graphs, parent/child phase scope, counter behavior inherited
from existing tests, corruption rejection, and exact failed-update rollback.
The full suite passed 461 tests; 285 relevant core/storage tests also passed under
optimized Python, with strict typing/lint/format checks passing.
