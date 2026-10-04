# ADR 0132: Reuse matching indexes during audit and maximality checks

- Status: implemented; constrained Linux qualification pending
- Date: 2026-10-04

## Context

The latest million-vertex recovery passed graph construction and the
matching-state consistency check, then failed in `is_maximal_matching()` while
allocating a fresh set of all matched vertices. `Matcher.audit()` also built a
set for each matching color class. Those structures duplicated the existing
`matched_vertices` index at the same recovery point where memory is bounded.

## Decision

Use a fixed-width marker array to verify vertex-disjoint color classes, reusing
the same array across colors. Verify matching edges and the maintained vertex
and partner indexes with cardinality and direct lookup checks (ADR 0131), then
check maximality by scanning unmatched vertices against the existing
`matched_vertices` index. `Matcher.maximal()` uses that same audited path;
general callers of `is_maximal_matching()` retain the standalone helper.

## Consequences

- Full paper audits and `Matcher.maximal()` avoid Python sets/dictionaries
  proportional to the matching size.
- The color-class marker costs four bytes per vertex and is reused for every
  color; matching and graph invariants remain fully checked.
- A regression runs the complete Matcher audit with guarded matched-vertex and
  partner indexes that reject iteration, while separate tests corrupt each
  index and require rejection.
- The constrained Linux worker must be rerun; no 512 MiB success is claimed.

## Verification

Focused matcher and recovery tests pass locally. The most recent hosted resource
attempt reached maximality auditing but failed in the pre-change snapshot set.
