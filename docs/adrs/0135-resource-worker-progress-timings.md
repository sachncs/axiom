# ADR 0135: Report progress within resource qualification deadlines

- Status: implemented; next constrained run pending
- Date: 2026-10-04

## Context

Two hosted Basic one-million-vertex growth/drain runs exceeded the existing
300-second worker deadline. ADR 0133 moved the failure past the earlier graph
insertion `MemoryError`; ADR 0134 reduced per-query verification overhead, but
the constrained worker still timed out. Both runs exposed only the outer
`subprocess.TimeoutExpired`, so it was unknown whether time was spent in durable
updates, matcher/service checks, backup, or memory/disk recovery.

## Decision

Keep the worker deadline unchanged. Emit flushed progress markers for the
durable-update phase at coarse 100,000-operation intervals, the start and
completion of large recovery audits, and backup/memory-pressure/disk-pressure
phase boundaries. Include elapsed monotonic time in completed phases. Emit
large-audit markers only for graph sizes of at least 100,000 vertices to keep
small unit-test output quiet.

## Consequences

- A timeout log can identify the last completed phase and the durable update
  rate envelope without needing an eventual JSON result.
- The markers do not affect acknowledged state, update order, snapshots, or the
  qualification deadline.
- The next hosted run still must finish within the existing limits; telemetry
  alone is not a resource or performance pass.

## Verification

The focused resource-envelope tests, Ruff, and mypy pass locally. The next
hosted run must report its final progress marker or complete the qualification.
