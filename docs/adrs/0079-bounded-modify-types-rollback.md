# ADR 0079: Bound Modify-Types rollback to path edges and affected fans

Date: 2026-10-03
State: Implemented; full boundary audits remain

## Context

`Spectrum.modify` computes all relevant alternating paths before mutating, but
then copied every coloring assignment and materialized the whole fan collection
for rollback. Path flips recolor only path edges and affect fan missing-color
state only at path endpoints; batch fan removal/replacement affects the selected
fans themselves. The full edge-key set was also copied merely to verify its
cardinality remained unchanged after path flips.

## Decision

After path construction and overlap-safe mutation-region preparation, capture
only unique path edges in `ColorJournal`. The affected fan region consists of
the selected fan vertices plus each path's endpoints; snapshot fans through the
existing vertex-to-fan index. On failure, restore touched coloring cells and
fans in that region while preserving outer container roots and unrelated fan
state. Replace the full colored-edge-set copy with an O(1) assignment-count
check; path flipping changes colors only and never inserts/removes assignments.
Full coloring, fan-index, and compatibility audits continue at operation
boundaries.

## Correctness

Every coloring change goes through `Fans.flip` on one of the precomputed paths.
The path edge set is deduplicated and captured before any fan is discarded.
`Fans.flip` updates fan records only at path endpoints, while Modify-Types
explicitly removes/re-adds each batch member; their vertices are included in the
affected set. The stale-fan cleanup can only remove fans whose assigned missing
colors changed at those endpoints. A post-replacement failure regression checks
exact color/fan state, stable outer roots, and preservation of an unrelated
compatible sentinel fan. Existing tests cover nontrivial flips, overlap
rejection, and invalid preconditions.

## Evidence and limits

On a 50,007-vertex fixture with 10,000 unrelated fans and 10,000 unrelated
colored edges, three traced runs measured median temporary peak of 20,519,888
bytes before and 19,621,984 bytes after (4.38% lower). Median elapsed time
changed from 800.69 ms to 811.73 ms (1.38% slower), so this is a bounded-memory
improvement, not a throughput claim. Full audits still account for most work.
See the [raw comparison](../../benchmarks/results/paper/modify-types-local-rollback.json).

## Alternatives

- Copy the whole coloring and all fans for a batch-local operation: rejected
  because all relevant paths are known before mutation.
- Drop rollback or skip compatibility checks: rejected; local before-images and
  full boundary audits remain.
- Retain a full colored-edge set to certify path flips: rejected because the
  only mutator preserves assignment cardinality and each touched edge receives
  local certification during the flip.

## Follow-up

Measure allocation and latency for large batches and overlapping-path failures.
`Spectrum.sparsify` and other paper operations still retain full snapshots and
need separate transaction-region proofs.
