# ADR 0009: Use SQLite WAL for the first durable single-owner layer

Date: 2026-10-01. Status: bounded replay implementation plus opt-in v2 native
checkpoints (ADR 0010) and separate local aggregation (ADR 0011);
sustained qualification pending.

## Context

The native core removes whole-state copying from ordinary production edits but
cannot acknowledge survival after process death or storage failure. A custom WAL
would require torn-write handling, commit boundaries, locking, persistence
barriers, recovery, and physical log maintenance, separate from matching repair.

## Decision

Use Python's bundled SQLite binding and SQLite WAL for committed operations/control
state, not as ordinary graph adjacency or matching storage. SQLite supplies the
physical transaction boundary; Axiom supplies deterministic replay, semantic
checksums/certificates, outcomes, private updates, publication, and ownership.

Require/read back `journal_mode=WAL`, `synchronous=FULL`, `fullfsync=ON`, and
`checkpoint_fullfsync=ON`. Never silently use NORMAL/OFF for an acknowledged rate.
FULL synchronizes WAL commits; fullfsync requests the stronger macOS sync method
where supported. Device/OS behavior remains a qualification assumption, not
something pragma readback or process-kill tests prove.
[SQLite synchronization](https://www.sqlite.org/pragma.html#pragma_synchronous),
[fullfsync](https://www.sqlite.org/pragma.html#pragma_fullfsync).

The first `axiom.durable.Durable` format persists fixed universe/ring-or-empty
genesis, format/backend versions, a contiguous request stream, transition outcomes,
mutation versions, a checksum chain, and committed control high-water mark.
Recovery bounds history before replay, verifies every outcome/version/checksum,
and audits the complete graph/matching before serving. Missing history cannot
silently lower the committed high-water mark.

One process owns a persistent, nonblocking POSIX advisory lock file. Never unlink
it: replacing its inode could permit two owners. A nonblocking in-process gate
covers edits/queries/close. There is no unbounded internal queue; contention gets
explicit backpressure. Require a private **local** directory and no independent
database users. SQLite WAL requires same-host shared state and does not support
network filesystems. [SQLite WAL restrictions](https://www.sqlite.org/wal.html).

Prepare/certify native edits privately; persist the bounded group and control
record in one FULL transaction; publish native state; return prebuilt outcomes.
Commit/publication exceptions disable the owner. Never treat an exception as
proof of noncommit: close/recover and retry the exact sequence/payload. SQLite
may leave or cancel a transaction after I/O/storage/memory failures; explicitly
roll back any remaining transaction and fail closed.
[SQLite transaction errors](https://www.sqlite.org/lang_transaction.html).

One request stream starts at 1, requires contiguous new sequence numbers, and
rejects reordering/conflicting retries before mutation. Retained retries return
original outcomes without another mutation. Intermediate operation versions are
historical outcomes, not retained query snapshots; queries see final group state.
No client/session namespace is silently inferred.

## Limits and consequences

- Default group bound: 256 supplied requests, configuration capped at 4096.
  The separate local service aggregates individual arrivals with bounded assembly
  wait; this primitive does not. No end-to-end latency SLA is claimed.
- Default history/dedup bound: 65,536 operations including no-ops. Reject new
  operations at the bound; retain retries. Configured history caps at one million.
  This legacy v1 mode is **not** sustained unlimited operation. Opt-in v2 bounds
  retained rows through atomic checkpoint/retirement rather than lifetime sequence;
  see ADR 0010 for policy and expiration semantics.
- Native allocation, database pages, batch/history, and page scans are bounded.
  Cache/journal-size settings do not hard-bound total RSS/WAL/disk usage; full
  service resource gates remain pending.
- Automatic SQLite WAL checkpoints occur at 256 pages and are included in commit
  timing. They are **not** native graph checkpoints or replay compaction. Native
  snapshots and bounded dedup retirement are now separate opt-in v2 maintenance;
  their end-to-end recovery/latency/resource gates remain unqualified.
- Current genesis supports ring/empty initialization, not arbitrary graph import.
  Format/backend mismatches refuse recovery instead of guessing.
- Backups need a SQLite-aware procedure; copying only a live WAL database's main
  file is not a service backup. Windows owner locking is not implemented.

Custom WAL/VFS development and weaker buffered acknowledgments are not selected
for this stage. Physical database recovery does not replace semantic matching
verification or qualify billion-vertex support.

## Evidence

Tests cover Python reference agreement, real/no-op durable outcomes, identical
retries, conflicting/reordered admission, exact recovery, private visibility,
ownership, bounded history, native budget rollback, partial-write/commit/publication
exceptions, actual SQLite page-limit exhaustion, corrupt history/control/backend,
checksum-valid wrong outcomes, and process death before/after commit/publication.
Process-death tests are not power-cut tests. The full-service 10k gate remains open.

Staged million-vertex runs with 256-operation groups, matching queries and physical
WAL checkpoints reach 30.4k–30.9k real acknowledged changes/s across three seeds.
They last only 1.29–1.32 seconds. Independent exact audits/recovery pass; these are
not native-checkpoint/soak/production qualification. Source/raw commands and limits
are recorded in [durable contracts](../durable.md).
