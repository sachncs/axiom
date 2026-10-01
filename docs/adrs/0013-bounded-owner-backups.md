# ADR 0013: Back up the durable authority, not the live main file

Date: 2026-10-02. Status: implemented; failure/restore tests; large-graph and
device power-loss qualification pending.

## Context and decision

A raw main-file copy misses acknowledged changes in WAL. Independent copies of
main/WAL/SHM can mix generations. An edge export loses exact matching, versions,
checksum anchors and retry retirement. Recomputing another valid matching is not
exact recovery. Per-update whole-state copies remain rejected (ADR 0003).

`Durable.backup(path, max_bytes=64 MiB, timeout=30s)` holds the owner gate,
audits native graph/matching and compares control with the publication, then uses
SQLite's backup API in 256-page steps. `Service.backup` schedules the same owner
snapshot. No native graph clone or whole-file Python bytes allocation occurs;
hashing streams in 1 MiB chunks and SQLite cache is bounded. Partner reads remain
available during copying/I/O; native audits still hold the GIL. The result includes
sequence/version, exact file bytes, SHA-256 and destination path.

Cap source page count, destination page allocation and final image bytes. Progress
checks size, contention and deadline; deadlines do not interrupt blocking I/O,
a native audit or final sync. Copying retains free pages; it is not VACUUM.
Use a private temporary directory on the destination filesystem, convert the
copy to a self-contained DELETE-journal database, check SQLite structure/exact
control, close, sync the file (also F_FULLFSYNC on macOS), publish with a
no-overwrite hard link and sync the directory. Allocate the result before linking.

Hold the destination's persistent POSIX `.owner` lock through publication; never
unlink lock files. Reject existing targets/sidecars, symlinks and source reserved
names. Require private local directories, no direct database users or adversarial
directory replacement. A target error raises `BackupError` without mutating or
disabling a healthy source, including through Service. Audit/control disagreement
disables the source. Failure after linking can leave a complete target without a
success result: inspect/restore it or choose a fresh path, never overwrite.
Ordinary failure cleans the private temporary copy. Process death may leave an
unpromoted `.axiom-backup-*` directory; it is not a valid published backup.

## Restore, resources and durability limits

Keep the returned SHA-256/sequence/version in a separately protected catalog;
verify bytes before opening. Clone the archival master to a fresh working path
and open `Durable` there. Recovery validates format, exact graph/partners,
checkpoint/history digests, retry outcomes and retirement. Opening with a writable
owner changes SQLite journal settings and may invalidate the file hash without
any graph edits; preserve an untouched master.

There is no implicit merge with newer/unrelated logs. The captured sequence is the
recovery point; later acknowledged changes need the original store or separately
qualified replication/log shipping. This is not zero-RPO device-loss recovery.
Same-filesystem temporary/final linking does not duplicate image bytes, but backup
and restore copies, retained free pages, scratch/cache and source files need
headroom. `max_bytes` is an image cap, not a hard total disk/RSS quota.

## Verification and alternatives

Tests contrast a stale raw main-file copy with a complete WAL snapshot; restore
legacy/v2 exact topology/partners/versions and retry/expiry state. Inject copy,
sync, pre-link, post-link and post-sync failure. Process death during a genuinely
partial SQLite step and publication leaves the target absent or complete; source
recovery is exact. Size/deadline/contention, owner conflicts, reserved paths,
no-overwrite, source control disagreement and concurrent service behavior are tested.

These are **not physical power-cut tests**. A controlled device/VM/storage runner
must independently record acknowledged IDs, interrupt persistence/publication,
restart and verify all acknowledged changes plus exact checkpoint/tail state.
Record filesystem/device/controller/cache configuration and barrier behavior.
Do not extrapolate process death to power loss.

Raw live-file copying, silent overwrite, callbacks on the owner and unbounded
backup/replay are rejected. VACUUM INTO may compact artifacts but requires
separate cost/barrier qualification. References: [SQLite backup API](https://www.sqlite.org/backup.html),
[Python binding](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
