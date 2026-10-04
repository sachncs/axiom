# ADR 0111: Localize Modify-Types fan repair

- Status: implemented; end-to-end performance effect remains unmeasured
- Date: 2026-10-04

## Context

`Spectrum.modify()` applies a batch of alternating-path flips and repairs fans
whose missing-color compatibility changed. A flip preserves missing colors at
interior vertices; only path endpoints can gain or lose a missing color.
`Fans.vertices` already indexes exactly the fans incident to each affected
endpoint. Despite that local mutation region, the operation previously made a
full `tuple(fans)` snapshot and tested every fan after each batch. It also ran
the same full coloring/fan audits both before opening the color journal and
again immediately after opening it, without an intervening mutation.

## Decision

Retain the full entry and exit coloring, fan-index, and compatibility
certificates. Remove the duplicate pre-mutation validation inside the journal
scope. After path flips, gather candidate fans only from `Fans.vertices` rows
for the already-proven affected vertices, then process them in deterministic
center/leaf order. The existing local before-image region remains the rollback
authority.

## Consequences

- Mutation-time compatibility repair is proportional to fans incident to
  changed path endpoints rather than all retained fans.
- Duplicate full certificates are eliminated while independent entry/exit
  audits remain intact.
- The full boundary audits still scale with the complete coloring/fan state;
  this change is not a claim that `Spectrum.modify()` has become a local-time
  operation end to end.
- Deterministic ordering and exact rollback behavior are preserved.

## Evidence and remaining qualification

A 128-fan regression applies a one-fan batch and verifies only the two required
whole-collection entry/exit compatibility passes occur; repair uses the local
fan index. Existing path-flip and failure-injection tests retain coloring and
fan rollback certificates. Basic/Multilevel end-to-end throughput, allocation,
and adversarial fan-density qualification remain open.
