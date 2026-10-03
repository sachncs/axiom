# ADR 0081: Stage color indexes without copying assignments

Date: 2026-10-03
State: Implemented; whole-sparsification qualification remains

## Context

`Partial.relabel` previously materialized a second edge-to-color dictionary,
reindexed all assignments, then ran a full validator which built another
incidence view. Global color relabeling necessarily visits every colored edge,
but duplicating the assignment table was not necessary for correctness.

## Decision

Validate that the requested mapping is a palette permutation, then stage the
new incident-color and vertex/color-to-edge indexes while the original
assignment values are still intact. Staging also checks every edge remains in
the graph and rejects duplicate mapped colors at either endpoint. Only after
the complete replacement indexes are built does relabel update existing
assignment dictionary values in place and publish the new indexes. Thus a
failed precondition or staging allocation/check leaves all coloring roots and
contents untouched, and successful relabel avoids a second assignment dict.

The index-building pass is also the relabel certificate: it reconstructs both
indexes and checks graph membership and properness, the invariants previously
checked by `reindex` followed by `validate`.

## Correctness and measurement

Tests prove assignment-root reuse and correct indexes after a nontrivial
permutation, rejection of incomplete mappings, and exact root/content
preservation when a colored graph edge is absent during staging. The existing
full paper-coloring suite independently validates downstream behavior.

Five alternating fresh-state runs on a 200,000-vertex disjoint matching with
100,000 colored edges measured median relabel peak of 175,614,488 bytes before
and 76,972,336 bytes after (56.17% lower), and median elapsed time of 930.40 ms
before and 435.33 ms after (53.21% lower). Setup and post-operation full
validation were excluded; the previous implementation's internal full
validation was included. The staged construction performs equivalent graph,
properness, and index checks in one pass. This is traced Python memory and
component elapsed time, not process RSS or a full `Spectrum.sparsify` result.

See the [raw comparison](../../benchmarks/results/paper/in-place-color-relabel.json).

## Alternatives

- Build a second assignment dictionary, then reindex: rejected because every
  edge assignment is duplicated without changing edge keys.
- Mutate assignment values before building replacement indexes: rejected
  because staging failure could expose colors inconsistent with existing
  indexes.
- Skip graph/properness validation: rejected; the staged index pass certifies
  these invariants before publication.

## Follow-up

Measure this path inside repeated `Spectrum.sparsify` workloads, including
large palettes, graph shapes with concentrated degrees, and injected staging
failures. The fan relabel path still builds an entire replacement collection.
