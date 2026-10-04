# ADR 0107: Search S-hat through local graph neighbors

- Status: implemented; workload qualification remains open
- Date: 2026-10-04

## Context

Basic U/B/A rematching used `sorted(S_hat)` as a fallback and checked graph
adjacency for each unmatched saturated vertex. The same helper runs in
Multilevel fallback paths. This allocated and sorted the complete S-hat set for
each query, even when the queried vertex had only a few neighbors.

## Decision

For a vertex `v`, enumerate `graph.neighbors(v)`, retain the minimum neighbor
that is both in S-hat and unmatched, and return it. This is the same candidate
the previous sorted-S-hat traversal selected: both compute the minimum vertex
in the exact intersection of S-hat, unmatched vertices, and `N(v)`. The new
work is O(deg(v)) with constant auxiliary memory and no global S-hat iteration.
Existing S-hat membership updates and rollback remain unchanged.

## Consequences

- The tie-breaking result stays deterministic even when the graph backend's
  neighbor iteration order is not sorted.
- The existing rematch scan counter now records the local neighbor probes on
  the U path instead of the number of globally sorted S-hat entries visited.
- No persistent index or per-update allocation is added. Full matching and
  phase-boundary validation remain unchanged.
- The regression prohibits S-hat iteration, verifies lowest-ID selection,
  checks a real U-rematching fallback, and certifies maximality. It proves the
  targeted access path, not whole-engine throughput.

## Evidence

The complete repository suite, strict mypy, and Ruff pass on the implementation
revision. No isolated speedup or production throughput claim is published.
