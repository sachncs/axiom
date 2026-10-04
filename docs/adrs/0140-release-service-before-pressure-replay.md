# ADR 0140: Release the closed Service before resource-pressure replay

- Status: implemented; hosted rerun pending
- Date: 2026-10-04

## Context

The constrained worker closes its million-vertex `Service` after the update,
audit, and backup phases, then opens the same durable database again for memory
pressure. `Service.close()` drains and closes the Durable owner, but a local
reference to the closed Service still retains that owner's Matcher and all
million-vertex paper state. Replaying the database while retaining this state
caused `MemoryError` during matcher construction, before the intended injected
allocation-pressure assertion.

## Decision

After leaving the Service context and collecting its scalar status/metrics,
release the closed Service reference and collect cyclic garbage before measuring
peak usage or opening any pressure-test owners.

## Consequences

- The memory-pressure test isolates the resource under test instead of
  accidentally holding two full paper matchers at once.
- The retained database and its operation history remain unchanged; this does
  not reduce the documented recovery or replay resource cost.
- The hosted resource job must still verify bounded memory failure/recovery,
  separate disk exhaustion, and exact backup restoration.

## Verification

The latest hosted run completed one million updates, maintenance audit, and
backup, then exposed the retained Service reference during the memory phase.
Ruff, mypy, and the local full suite passed before this lifecycle correction; a
new constrained hosted run is required for evidence.
