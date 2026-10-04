# ADR 0109: Index nonempty matching color classes

- Status: implemented; workload qualification remains open
- Date: 2026-10-04

## Context

Matcher deletion previously broadcast every removed edge to all `z + 1`
matching classes. Sparse/low-degree graphs can have thousands of configured but
empty color sets, so those membership probes were unrelated to the update's
write set. A one-million-vertex Basic matcher can configure about 10,000 colors.

## Decision

Maintain `Matcher.activecolors`, the set of indices whose matching class is
nonempty. Build it in the same pass that partitions the colored System
matching. Deletion visits those indices in sorted order, preserving the prior
deterministic color order. Removing a class's last edge journal-deactivates the
index; seed alias handling and subphase seed replacement update color zero
explicitly. Class journal rollback restores both membership cells and the
original index root/content. `Witness` includes the new logical field, and
root-replacement validation recomputes the expected index.

## Consequences

- A deletion no longer calls `Classes.remove` for configured empty classes.
- If many classes are active, deletion remains proportional to that active
  count; this is not an edge-to-color index and does not promise O(1) lookup.
- Class-journal construction and validation still inspect class roots. This
  change only removes absent-class work from the deletion fan-out.
- The index is redundant state and therefore participates in exact rollback,
  Witness comparison, and rebuild validation.

## Evidence and limits

Tests cover journaled last-member deactivation with both commit and exact
rollback, direct unjournaled seed removal, deletion with many empty configured
classes, and the full Basic/Multilevel regression suites. No throughput or
allocation improvement is claimed until installed repeated measurements cover
sparse and dense color-class populations and a high-degree/skewed workload.
