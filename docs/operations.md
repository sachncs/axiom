# Production operations and remaining qualification

The local native Service is a delivered component, not a turnkey network daemon.
This runbook distinguishes its enforced bounds from deployment controls that the
embedding application must supply. Do not claim a production release solely from
a throughput sample or green unit tests. See [current roadmap](engineering.md)
and [resource evidence](adrs/0020-resource-exhaustion-and-recovery.md).

## Ownership and storage

Use one mutation owner for a connected graph, one application-coordinated ordered
request stream, and a private local POSIX directory. Never let a second process
write the database directly or delete its persistent owner-lock file to bypass
ownership. SQLite checkpoint plus committed tail is the complete durable authority;
native graph/matching memory is its live compute representation. Independent graphs
may use independent owners. Arbitrary partitions of one graph are not independent.

Keep database, WAL and shared-memory companions together during operation. A copy
of only the live main database is not a backup. Use the bounded owner `backup`
operation to produce a self-contained immutable master at a fresh destination.
Keep separate generations according to a bounded retention policy outside the
live graph filesystem; avoid deleting a last known-good backup before certifying
its replacement. Copy a master to a fresh restore path before opening it.

Backups with unused SQLite pages are compacted privately before publication.
The live database is not vacuumed: its free pages remain available for reuse.
Compaction temporarily needs both a copied image and a compact output, in addition
to the live database/WAL. Final restoration needs the live source, immutable
master and restore copy to coexist. Include these phases in disk sizing; the
image byte cap is not an aggregate filesystem quota. Backup failure is local to
that operation; inspect a possibly published destination before retrying at a
fresh path. Do not delete the source or master to conceal insufficient headroom.

## Capacity controls

| Control | Enforced by component | Additional deployment responsibility |
| --- | --- | --- |
| Native allocations | `budget`, including graph/partner journals and indexes | Total process/worker memory, allocator overhead, Python/SQLite and page-cache accounting |
| Pending work | `queue_capacity`, read reservation, maintenance capacity | Bounded caller retries, request retention and any transport buffers |
| Persistent state | Database page cap, snapshot cap, checkpoint/history policy | WAL/companions, multiple backups, filesystem capacity and reserved recovery headroom |
| Workload | Fixed vertex universe; memory rejection and bounded batches | Declare allowed edges/degrees/skew, burst/query mix and recovery objectives |
| Deadline | Receipt waits and bounded backup-copy checks | Supervisor outage handling; timeout does not cancel a mutation or interrupt native/filesystem work |

The 512 MiB RLIMIT_AS and 192 MiB ext4 image in CI prove an isolated exhaustion
stage. They do not install deployment memory/page-cache quotas or guarantee every
allocation can recover under a kernel OOM kill. A supervisor must treat abrupt
owner death as a recovery event, not fabricate success for pending requests.
Choose aggregate limits from measured constructor, active-update, maintenance,
backup and restore peaks, including transient headroom. No numeric production
memory limit or recovery deadline has been accepted yet.

### macOS allocator residency

Changing-density checkpoints can leave freed large allocations resident in the
OS allocator. The measured growth/drain experiment reduces peak owner RSS from
913 MB (default launch) to 208 MB with `MallocLargeCache=0`, without changing the
graph budget, encoding or durability. This is a scoped launch-policy measurement,
not a hard RSS limit; VM inspection perturbs tails. See [ADR 0022](adrs/0022-allocator-residency.md).

For an explicitly selected macOS deployment profile, set the variable before
launching the application, for example `env MallocLargeCache=0 /path/to/python app.py`.
The library does not set global allocator policy or re-execute its host process.
Requalify the actual OS/runtime, workload, maintenance and backup/restore peaks;
the setting does not replace deployment quotas or Linux hard-resource testing.

## Monitor and respond

Sample `metrics()` for admission diagnostics; it does not enqueue owner work.
Use bounded sampling of `status().result()` for committed state, because it shares
admission and scheduling with other work. Do not enqueue an unbounded backlog of
status, audit, checkpoint or backup calls when the owner is slow.

- Alert immediately on failed state, certificate/recovery rejection and unexpected
  close errors. Stop admission and preserve diagnostic evidence.
- Track `outstanding/capacity`, update admission limit, maintenance outstanding,
  accepted/completed counts and Busy rates. Sustained saturation requires bounded
  backpressure/rejection, not another unlimited queue.
- Track committed sequence, checkpoint sequence/generation, retired floor and
  retained operations. Admission sequence is not a durable watermark; counters
  from separate calls are not an atomic combined graph snapshot.
- Track acknowledgment/query p99 and maxima separately from native execution;
  include timeouts, failures and producer/transport losses in reports.
- Measure process and deployment memory, filesystem free space, database/WAL and
  backup bytes. Track growth across repeated checkpoints, not just one final size.

Thresholds and alert integration belong to the deployment; this repository does
not yet ship an external monitoring collector or supervisor. Current latency is
accepted for this version; tighter latency/background maintenance is future work.

## Failure and restart

1. Stop new admissions after persistence/certificate uncertainty. Keep original
   request IDs and payloads; a timed-out receipt is not evidence of rollback.
2. Close/drain if possible. A close timeout leaves draining in progress; do not
   start a competing owner while the previous owner is still alive.
3. Preserve the failed store and backup master. Restore capacity without manually
   editing SQLite tables, truncating WAL, repairing matching or deleting locks.
4. Reopen through Durable/Service so control, images, replay and matching are
   verified. Reject corrupt state rather than silently rebuilding another matching.
5. Retry uncertain requests with their original IDs/payloads. Expired IDs cannot
   be recovered from the bounded dedup window; reconcile with the application's
   durable acknowledgment ledger rather than assigning a new ID blindly.
6. Resume only after committed state agrees with the application's reference and
   recovery limits. Backup recovery may restore an older committed prefix; define
   its allowed data-loss window before calling it disaster recovery.

## Hardware power-loss gate

Process termination, memory failure and SQLite FULL tests have passed, but none
proves that a device honors flushes after sudden power removal. This gate requires
a disposable dedicated host/device and explicit operator control; do not cut power
on the shared workstation or use production data.

Run ordered real updates and coherent queries through maintenance and backups.
Record acknowledged request IDs, payloads, versions and outcomes on an independent
durable observer outside the device under test. Trigger power interruption at varied
apply/commit/publication/acknowledgment and backup boundaries. After each reboot,
preserve evidence, reopen without repairs, and compare the exact recovered prefix
to that observer. Every observed successful acknowledgment must survive. Later
unacknowledged requests may have committed; retry them by original ID and require
the original outcome. Independently certify all edges, exact partners, maximality,
versions, history and backup absent-or-complete publication.

Record source/wheel hashes, OS/filesystem, SQLite settings, drive/controller/cache
configuration, interruption timing and every failure. Repeat with the deployment's
actual quotas and device policy. Qualification for one combination is not proof
for other devices or filesystems. This hardware gate remains unexecuted. On
2026-10-02 the user deferred it for this version; retain this protocol as future
engineering, not a current-version release prerequisite or delivered guarantee.
