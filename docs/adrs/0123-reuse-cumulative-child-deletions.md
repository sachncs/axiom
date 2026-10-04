# ADR 0123: Reuse the cumulative deletion root in child refinement

- Status: implemented
- Date: 2026-10-04

## Context

Multilevel child refinement formed the union of the Matcher-owned cumulative
deleted-edge set and the previous hierarchy's deferred-deletion set. The
deferred set is a subset of cumulative deletions throughout a child phase:
delete adds the edge to both, insert removes it from both, refinement selects
deferred edges from the cumulative set, and a parent boundary clears both.
Consequently, the union duplicated O(|E_D|) Python set entries at each child
rebuild.

## Decision

Before child refinement, verify the deferred subset invariant with
`set.issubset` and pass the original `matcher.deleted_edges` root directly.
Reject an invalid internal state before replacing the active hierarchy. Do not
allocate a copied union.

## Consequences

- Removes one temporary set allocation proportional to accumulated deletion
  history at each child rebuild.
- The subset check remains O(|E_D'|) membership work but creates no intermediate
  collection; refinement still performs its required projection and graph work.
- An invariant violation fails closed and is rolled back when rebuild is inside
  Matcher transaction boundaries.
- This does not remove the parent-boundary live-graph snapshot or other
  state-sized phase allocations.

## Verification

A child-rebuild regression first performs a real deletion so the deferred set is
nonempty, then verifies refinement receives the exact Matcher-owned deletion
root and the rebuilt hierarchy remains certified. A negative regression injects
an undeclared deferred edge inside a Matcher batch and verifies the precondition
failure restores the complete paper Witness exactly. Focused rebuild tests,
full-suite tests, and typed checks provide correctness evidence; allocation
savings are inferred from the removed set union and have not been separately
measured.
