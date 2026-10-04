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
- The first telemetry-enabled hosted run on `1890c72` reported 100,096 updates
  at 126.274 seconds and 200,192 at 240.985 seconds, then hit the 300-second
  deadline while still processing Service updates. The timer began before
  Service construction, so those rates include initialization; the worker did
  not reach audit, backup, or pressure recovery. This is a measured update-path
  failure against 10k/s, not a resource or performance pass. The next run
  separates initialization from updates and records actual Service group count
  and largest group at each progress marker, distinguishing per-request commit
  overhead from matcher-transaction overhead.

## Verification

The focused resource-envelope tests, Ruff, and mypy pass locally. The telemetry
proved that verifier batching in ADR 0134 was not on this run's critical path;
the next step is to quantify Service aggregation and Durable/Matcher transaction
overhead without changing the qualified deadline.
