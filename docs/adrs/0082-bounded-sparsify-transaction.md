# ADR 0082: Bound the `Spectrum.sparsify` transaction

Date: 2026-10-03
State: Implemented; fan algorithm work and broader qualification remain

## Context

`Spectrum.sparsify` took a full assignment dictionary, a full fan tuple, and a
full set of colored edge keys before it began. Yet its global color change is
a palette permutation, and subsequent `Modify-Types` operations alter colors
only along known alternating paths. In addition, `Fans.relabel` materialized a
sorted list and tuple even though it stages a separate replacement collection
and never mutates the source during construction.

## Decision

Retain only the original coloring incidence/index roots and fan index roots
before the transaction. Apply the global coloring permutation in place using
the staged indexes from ADR 0081. Enlist each subsequent Modify-Types
first-write path-color before-image in an outer `ColorJournal`; nested batch
journals still provide local failure atomicity. On outer failure, restore
touched edges to their post-permutation values, apply the inverse permutation
to restore original colors, and reattach the untouched original index roots.
The fan relabel operation stages new roots and only publishes after successful
construction; retain the old roots by reference and reattach them on failure.
Thus the transaction no longer duplicates the complete coloring, complete fan
membership tuple, or colored-edge key set.

`Fans.relabel` now iterates its immutable source membership directly while
building replacement indexes. It does not sort/materialize a source tuple;
public iteration remains deterministic through `Fans.__iter__`.

The colored-edge invariant is checked by cardinality at the transaction
boundary; the permitted operations (`Partial.relabel` and alternating path
flips) preserve the assignment key set by construction. The full fan/color
compatibility and coloring audits remain at boundaries.

## Correctness evidence

The sparsification rollback test now performs a real Modify-Types batch and
injects failure after it completes. It verifies exact original coloring and
fan contents, identity of all original coloring/fan index roots, and full
post-rollback validation. Existing deterministic success and cross-block
tests independently verify complete output and that the colored edge set is
unchanged. Relabel staging and invalid-precondition tests remain in place.

## Measurement and limits

Five alternating runs of complete `Spectrum.sparsify` on a 66,000-vertex
fixture with 30,000 unrelated colored matching edges and 2,000 independent
fans reduced median traced peak from 34,831,232 bytes to 31,588,264 bytes
(9.31% lower). Median elapsed time changed from 384.08 ms to 396.86 ms
(3.33% slower). Fixture setup and independent post-operation audits were
excluded. This is a synthetic disconnected fixture; it does not qualify
connected/skewed graphs, process RSS, or production service performance.

See the [raw comparison](../../benchmarks/results/paper/bounded-sparsify-transaction.json).

## Alternatives

- Keep full state copies for recovery: rejected because the relabel inverse and
  path journal recover the exact original state without assignment-key copies.
- Remove transaction rollback or compatibility audits: rejected; the
  failure-after-success regression and full boundary checks remain.
- Claim all sparsification work is local: rejected; the algorithm still
  globally relabels every assignment/fan and retains paper-level scans/indexes.

## Follow-up

Profile connected/skewed inputs and identify the largest remaining workspaces
inside the `Modify-Types` loop. Consider a compact fan delta only if repeated
fan index construction is shown to dominate; fan relabel remains a global
staged transformation by algorithm design.
