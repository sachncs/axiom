# ADR 0078: Journal Pruning.construct coloring changes

Date: 2026-10-03  
State: Implemented; other state-sized paper snapshots remain

## Context

`Pruning.construct` wrapped all alpha groups in a full copy of the current
coloring assignment map. This duplicate scaled with every pre-existing colored
edge even when construction changed only a small set of pending spokes. Its
inner `Pruning.prune` and `Pruning.reduce` stages now have complete changed-edge
regions: prune journals exposed spokes, while reduction journals chain paths
and fan spokes before each activation.

## Decision

Introduce a reusable first-write `ColorJournal` with optional parent propagation.
The outer construct owns one journal and passes it into prune/reduce. Child
captures preserve the outermost original color while retaining local
before-images for prune's own atomic failure. Reduction records activation
edges/spokes before mutation and records both colliding chains before calling
the collision resolver. If any later stage fails, construct restores the
deduplicated set of touched coloring cells through `Partial.replace`, preserving
assignment/index roots. The previous full coloring dictionary snapshot is
removed.

## Correctness

Every coloring mutation reachable from `Pruning.construct` occurs in prune's
expose/assign branches or reduce's Vizing chain/spoke activation. Each such
region is captured before mutation. The existing prune rollback remains local;
its captures propagate to the enclosing journal so a later alpha-group failure
can undo already completed work. A regression injects failure after an inner
reduction has completed and proves that the outer operation restores the
original coloring contents and root identities. Independent full coloring,
fan-index, and compatibility checks remain at construction boundaries.

## Evidence and limits

On a 100,200-vertex sparse graph with 50,000 pre-colored matching edges and 100
pending matching edges, three traced runs measured peak temporary allocation
of 43,037,680 bytes before and 40,427,552 bytes after (6.06% lower). Median
elapsed time was 927.98 ms before and 917.06 ms after (1.18% lower); the timing
difference is small and is not claimed as a throughput improvement. All pending
edges were colored and independent end-state audits passed. See the
[raw comparison](../../benchmarks/results/paper/construct-color-journal.json).

## Alternatives

- Copy all coloring assignments at construct entry: rejected because the
  mutation set is explicitly captured by nested journals.
- Remove failure rollback: rejected; the outer journal preserves cross-group
  atomicity while nested prune rollback remains intact.
- Journal every edge in the graph: rejected; only actual chain/spoke regions
  are recorded on first write.

## Follow-up

Keep all mutation sites in prune/reduce inside the captured-region contract.
Extend the same parent-journal mechanism only when each nested operation exposes
its complete changed-edge set; `Construction.small`, `Sparsify-Types`, and
remaining hierarchy transitions still retain state-sized snapshots.
