# 0033: Stage fan indexes before publishing a color relabel

Date: 2026-10-03. Status: implemented; success, invalid-map, and injected staging
failure regressions pass.

## Context

`Fans.relabel()` removed every live fan and index entry before translating the
colors. A missing or conflicting mapping could then raise after destructive
mutation; its exception handler cleared the collection, losing the valid
pre-operation state. This violates the paper engine's rollback contract for a
routine used during color-symmetry transitions.

## Decision

Build and validate the full replacement collection using the same runtime
Fans class before changing the live object. Only after every translated fan and
all derived indexes have been accepted are the six collection roots published on
the existing Fans instance. Failed mapping lookup, fan construction, index
conflict, or staging allocation leaves all original collection roots and
contents untouched. The operation does not copy or mutate the coloring.

## Verification and limits

Tests cover a valid color permutation, a non-injective map rejected by fan
construction, and an injected failure on the second staged insertion. Failure
cases compare every index value and root identity before/after and run the
independent Fans invariant audit. This closes one concrete failure mode; it does
not prove all paper mutations are journaled or integrated into durable service.
