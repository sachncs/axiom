# ADR 0103: Maintain the Multilevel I3 crossing index incrementally

- Status: implemented; performance qualification remains open
- Date: 2026-10-04

## Context

Multilevel's ordinary update path scanned and sorted all of `matched_edges` in
`Hierarchy.maintain_i3`, then scanned it again in `Hierarchy.check_i3`. It also
computed `seed_matching - matched_edges` after every update. Those operations
made local edits scale with the full matching size even when no I3 crossing or
seed edge had changed.

## Decision

`Matcher` maintains the active A1/R1 crossing edges as matching edges are added
and removed. The existing `Views` transaction journals changed crossing cells,
so rollback restores both the set's contents and its original root. A hierarchy
rebuild still performs the full I3 audit and reconstructs the index once after
the partition roots are finalized. Ordinary update checks use the indexed count;
the public full `Hierarchy.check_i3` scan remains available for explicit audits
and rebuild validation. Dropping a matching edge now removes that edge from the
seed class immediately, avoiding a full seed/matching set difference each call.

## Consequences

- Ordinary I3 maintenance sorts only indexed boundary crossings rather than
  the complete matching. Valid states bound that set by the I3 threshold.
- Crossing-index edits participate in exact Matcher rollback and the full-state
  `Witness`, including injected failure after an index mutation.
- An index bug could hide a missed crossing from the constant-time bound check;
  rebuilds retain the full scan, while focused tests compare the maintained
  index with an independent full derivation after updates.
- This is not a change to the paper algorithm or a performance qualification.

## Evidence

The deterministic 128k-vertex, average-degree-four Durable trace at batch 32
increased from 49.29 to 3,057.28 acknowledged updates/s in one before/after
sample, with exact replay and independent audit passing. A one-million-vertex
trace at batch 256 measured 3,135.88 updates/s, 81.3 ms ack p99, 1.80 GB peak
RSS, and exact recovery. A 4,096-update single group measured only 1,559.32/s,
2.60 s ack p99, and 1.88 GB RSS. These short, single-run results show a material
hot-path improvement but miss the 10k/s target and expose that very large atomic
groups have unacceptable latency; neither mode is performance-qualified.

The test suite checks that ordinary updates do not call the full I3 scan, that
successful insert/delete transitions maintain a nonempty crossing index, and
that failure after a crossing edit restores graph, matching, and index state.
The captured smoke outputs are in
[`multilevel-incremental-i3-smoke.json`](../../benchmarks/results/paper/multilevel-incremental-i3-smoke.json).
