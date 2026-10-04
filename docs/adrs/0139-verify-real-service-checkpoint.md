# ADR 0139: Verify the Service checkpoint contract directly

- Status: implemented; hosted rerun pending
- Date: 2026-10-04

## Context

After the resource worker completed its one-million-update workload, it looked
for `checkpoint_generation` in `Service.status()`. The Service API exposes
committed graph/history status, but no checkpoint generation; explicit SQLite
WAL maintenance is a separate `Service.checkpoint()` operation returning
`busy`, `wal_pages`, and `checkpointed_pages`.

## Decision

The resource worker now performs the explicit checkpoint and validates its real
statistics: this WAL-backed store must report no busy checkpoint, nonnegative
WAL page counts, and every reported WAL page checkpointed. A `0/0` empty WAL is
valid; negative no-WAL sentinel values are rejected because Durable requires
WAL mode. It also verifies the exact acknowledged operation/history prefix,
graph version, expected graph counts, configured history cap, and a full
Service graph audit before backup and pressure tests.

## Consequences

- Qualification tests the public Service/Durable contract instead of a removed
  checkpoint-generation field.
- Status, explicit WAL maintenance, and the independent graph audit are each
  checked at the actual resource-test phase boundary.
- The million-update run has reached 6,093 updates/s on the hosted constrained
  runner, below the 10k/s goal. This fix validates maintenance only; it does
  not claim the target rate or complete the resource qualification.

## Verification

Unit tests cover valid empty/nonempty WAL results, inconsistent or malformed
checkpoint statistics, wrong history counts, and a failed graph audit. A
hosted rerun must complete the remaining memory, backup, disk-exhaustion, and
recovery phases.
