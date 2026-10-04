# ADR 0114: Count hierarchy color classes without edge buckets

Date: 2026-10-04
State: Implemented; end-to-end performance qualification pending

## Context

Recursive hierarchy refinement colored the prior level's matching into a
mapping, then copied every colored edge into a second set of per-color buckets.
It intersected each bucket with retained phase deletions to rank colors, and
scanned selected buckets again to form the deferred and chosen matchings. The
per-color edge buckets duplicated O(|M|) hash-table membership during an
already allocation-heavy refinement.

## Decision

Retain the independent coloring completeness, color-range, and properness
certificates. Count retained deleted edges by color in a compact `z + 1`
integer row, preserving the exact `(count, color)` order and empty-color slots.
Then select the same first `z_prime` colors and scan the existing coloring and
retained deletion set to build the required deferred/chosen edge sets. Keep the
existing floor deletion budget and fail-closed check unchanged.

## Consequences

This removes the second edge-to-color bucket representation and its O(|M|)
hash memberships. Refinement still performs the coloring and its global
certificates, keeps the result sets needed by later phases, and may allocate
O(z) counts/selected colors. No asymptotic runtime or end-to-end throughput
claim follows from this allocation reduction.

## Verification

Deterministic tests compare the resulting deferred set with the prior bucket
selection on tied counts, empty colors, zero and rounded-down deletion budgets,
and nonmatching deleted graph edges. Existing hierarchy and paper-mode tests
continue to validate the full resulting hierarchy and invariants. Full
allocation/time measurement and Basic/Multilevel production qualification
remain open.
