# ADR 0083: Prove recursive color-group scopes disjoint

Date: 2026-10-04
State: Implemented; connected/skewed qualification remains

## Context

`Extension.extend` retained a `scopededges` set containing every edge already
merged from a child, solely to reject overlap with the next child's
`edgescope`. The active child already materializes its own edge scope, so this
ledger duplicated O(m) edge keys across the recursion level.

## Decision

Require the returned color groups to be pairwise disjoint, checked in color
space with storage proportional to the palette, not the graph edge count.
`Extension.project` has an explicit scope contract: it includes colored edges
whose color is in the group plus spokes of fans whose complete two-color type
belongs to the group. Distinct fan colors and disjoint groups assign each fan
to at most one child. `Fans.compatible` ensures fan spokes are uncolored and
pairwise edge-disjoint. A colored edge belongs to exactly one group because it
has one color. Therefore sibling scopes are disjoint by construction, and the
per-recursion O(m) edge ledger and its repeated overlap/update work are removed.

## Correctness evidence

An explicit two-group `Extend` test projects and merges two independent fan
families and validates the complete result. A separate adversarial spectrum
provider returns overlapping color groups and is rejected before recursive
projection, leaving coloring and fan state unchanged. Existing projection,
fan compatibility, recursive synchronization, and full coloring tests remain
active.

## Measurement and limits

Five alternating full `Extension.extend` runs with 5,000 independent fans,
two disjoint color groups, no precolored edges, and 15,000 vertices measured
median traced peak of 14,103,016 bytes before and 13,418,808 bytes after
(4.85% lower). Median elapsed time changed from 801.25 ms to 805.85 ms
(0.57% slower). Fixture setup and independent final validation were excluded.
This synthetic disconnected workload does not qualify connected graphs,
high-degree/skewed scopes, process RSS, or production service performance.

See the [raw comparison](../../benchmarks/results/paper/disjoint-extension-scopes.json).

## Alternatives

- Keep the full `scopededges` overlap ledger: rejected because disjointness
  follows from certified color partition and fan invariants.
- Trust arbitrary overlapping groups: rejected; color-group disjointness is
  explicitly checked before projection.
- Remove all edge-scope contracts: rejected; project now documents the exact
  scope required for the proof, and end-to-end multi-group tests exercise it.

## Follow-up

Continue memory profiling of `Extension.project`, especially its `edgescope`,
degree preflight, and child graph construction, on connected and skewed inputs.
Keep independent validation at recursion boundaries.
