# ADR 0073: Use the existing fan membership index

Date: 2026-10-03  
State: Implemented; broader fan-operation qualification remains open

## Context

`Fans` owns a set of active fans, but two ownership checks converted the whole
collection to a fresh set before checking membership. In `Spectrum.modify`,
this conversion occurred once for every batch member, turning a batch of F fans
into O(F²) iteration and temporary fan-reference allocation. `Construction.activate`
also paid an O(F) collection conversion for a single membership query. `Fans.add`
allocated a one-element set for a duplicate check.

## Decision

Use `fans.members` directly for ownership checks and direct set membership in
`Fans.add`. The maintained member index is the canonical source of membership;
no auxiliary index or scan is required.

## Correctness

These checks only test the same fan equality/set-membership relation previously
used after materializing the collection. Fan insertion still checks member,
spoke, and vertex-color collisions before changing indexes. A regression test
uses 64 fans and counts collection iterations during a complete Modify-Types
batch, preventing per-member collection rescans while checking resulting fan
validity and compatibility.

## Evidence and limits

Three runs over a deterministic 400-fan batch on 1,200 vertices measured median
Modify-Types time of 45.95 ms before and 9.95 ms after (4.62x); every result
passed fan and coloring compatibility checks. This isolates batch processing,
excludes setup and final validation, and does not measure allocation peaks or
end-to-end Matcher throughput. See the
[raw comparison](../../benchmarks/results/paper/fan-batch-membership.json).

## Alternatives

- Recreate the member set inside each predicate: rejected as quadratic and
  allocation-heavy.
- Add a second fan membership index: rejected because `members` already is the
  exact index required.
- Skip batch ownership validation: rejected; direct indexed checks preserve it.

## Follow-up

Profile remaining fan repair and transaction snapshots across adversarial fan
counts; this change does not migrate whole-coloring or whole-fan rollback state.
