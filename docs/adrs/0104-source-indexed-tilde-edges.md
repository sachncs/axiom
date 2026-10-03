# ADR 0104: Index H-tilde outgoing edges by source

- Status: implemented; aggregate memory/performance qualification remains open
- Date: 2026-10-04

## Context

`ProcUpdate` removes the outgoing H-tilde edges for a changing source. The old
implementation searched the complete directed-edge set and allocated a list of
matches on every call. Its cost was therefore O(|H-tilde|) even when the
source had no outgoing edges. Matcher rollback already uses `Auxiliary` to
journal related inserted-edge and incoming-H-tilde changes.

## Decision

Maintain a sparse source-to-target set alongside the authoritative H-tilde set
and its existing target-to-source reverse index. Add, delete, and full rebuild
paths update all three views. `Auxiliary` journals the new root and bucket cells
in the same transaction; its local certificate checks touched directed edges,
and its independent complete audit reconstructs the source index. Full-state
`Witness` comparisons include the index.

Source cleanup now enumerates only the selected source's outgoing targets, in
deterministic order, and removes matching incoming reverse cells. The update
cost is proportional to that source's H-tilde out-degree rather than the global
edge count. This adds a sparse index proportional to live H-tilde source/edge
cells; its aggregate memory cost must be included in future skew and process-RSS
qualification. The index is omitted for sources without outgoing edges.

## Consequences

- A missing or corrupted source-index delta fails the local certificate and
  rolls back all matching/auxiliary state rather than publishing partial views.
- Phase rebuilds retain a full independent oracle for all three H-tilde views.
- The optimization changes data access, not the matching algorithm or ordering
  of candidates; target iteration is sorted before source cleanup.
- The synthetic timing below isolates an empty-source cleanup at a fixed
  H-tilde set size. It is not a Matcher, Durable, or Service throughput claim.

## Evidence

The regression suite rejects iteration of the global H-tilde set during source
cleanup, checks outgoing and incoming index synchronization, and exercises
Matcher failure rollback/rebuild audits. On Python 3.11.16/macOS ARM64, a local
100,000-edge set took an average of 4.265 ms per old-style full-set
comprehension (50 repetitions). The indexed empty-source call averaged 146 ns
over 100,000 repetitions, approximately 29,243x lower for that isolated shape.
The input set was synthetic, the run was not repeated in fresh processes, and
the added index's RSS cost was not measured. See
[`htilde-source-index.json`](../../benchmarks/results/paper/htilde-source-index.json).
