# ADR 0131: Audit matching indexes without duplicate snapshots

- Status: implemented; constrained Linux qualification pending
- Date: 2026-10-04

## Context

After recovery began releasing the failed Matcher and clearing exception-frame
references, the installed million-vertex worker reached `Matcher.refresh()`
during committed-state replay. `__check_matching_state()` allocated a second
set of every matched vertex and a second partner dictionary, then compared them
with the already-maintained indexes. Under the 512 MiB address-space limit,
`expected_vertices.update()` raised `MemoryError`.

## Decision

Validate the maintained matching structures using cardinality and direct
membership lookups instead of rebuilding them. Require the vertex and partner
indexes to each contain exactly twice the matching edge count. For each
canonical graph edge in the matching, verify both endpoints are indexed and
the partner map points in both directions. These conditions reject shared
endpoints, missing entries, and stray entries without an O(|M|) duplicate set
or dictionary.

## Consequences

- Matching-state verification remains complete while its additional memory is
  constant with respect to the matching size.
- The check still costs O(|M|) time and uses the existing matching, vertex, and
  partner structures as the state under test.
- Corruption tests cover endpoint membership and partner consistency; a guarded
  set/dict proves the check does not iterate to materialize duplicate indexes.
- Only the installed constrained Linux worker can establish whether the full
  paper-backed service now fits its address-space and disk limits.

## Verification

Focused matcher and Durable recovery tests pass locally. The latest hosted
resource attempt failed in the old snapshot-based check before this change; a
new constrained run is required.
