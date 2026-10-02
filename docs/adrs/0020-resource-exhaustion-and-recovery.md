# 0020: Isolated resource exhaustion and exact recovery

Date: 2026-10-02. Status: million-vertex Linux exhaustion/recovery stage passed;
production deployment quotas pending; hardware power-loss deferred by user.

## Decision

Run `scripts/verify_resource_envelope.py` against an installed wheel on Linux,
in a subprocess with a hard 512 MiB address-space limit and a dedicated fresh
192 MiB ext4 filesystem. CI owns and mounts the disposable image; the drill
refuses ordinary host directories, symlinks, populated volumes and oversized
filesystems. Native allocations have a separate 128 MiB budget. These limits
are test conditions, not a production RSS or latency SLA.

The million-vertex degree-four ring receives 40,000 real balanced updates,
crosses automatic maintenance and produces an immutable self-contained backup.
Actual allocation exhaustion must reject checkpoint creation before persistence,
leave its generation and acknowledged state unchanged, and permit a subsequent
checkpoint after pressure is released. Actual filesystem exhaustion must produce
SQLite FULL, fail-stop the service and reject queries until reopening.

After each pressure stage and backup restore, independently check every expected
edge and exact partner, counts, committed version, native certificate and the
original retry outcome. Compare partner digests across the entire data flow;
a different valid matching is not an exact recovery. Restore a copy, never mutate
the backup master. Remove only the exclusively created, owned ballast file.

## Structure and conventions

`Volume` owns filesystem validation and pressure-file lifecycle. `Audit` owns
the deterministic reference. `Pressure` defines a reusable polymorphic contract;
`Memory` and `Disk` implement distinct failure/recovery behavior. `Envelope`
coordinates service, backup and recovery. Classes and their public methods and
local variables use single-word names; Python protocol names and external API
identifiers are necessary exceptions. Tests may use descriptive snake case.

Apply these conventions to new work without adding single-use wrappers or
silently renaming established public APIs. Existing paper/native APIs require a
separate compatibility migration, not a cosmetic mass rewrite. Classes encapsulate
state and lifecycle; polymorphism is used where behavior actually varies.

## Evidence and limits

Local component coverage exercises unsafe mounts, file ownership, partial/stalled
writes, flush errors, invalid references, changed topology, changed exact matching
and retry data flow. It does not simulate evidence of real Linux exhaustion.

[CI job 110611262441](https://github.com/sachncs/axiom/actions/runs/36934396108/job/110611262441)
passed on source `3a4eee38b4ca64c3855e8174a09b10580be87b20`, Ubuntu 24.04,
CPython 3.12.14, SQLite 3.45.1. The installed wheel completed all 40,000 real
updates, automatic maintenance, actual allocation failure and SQLite FULL,
same-owner OOM recovery, fail-stop/reopen disk recovery and immutable backup
restore. Exact audits and all partner digests agreed. The usable filesystem was
171,745,280 bytes; backup size was 25,612,288 bytes. Peak RSS was 509,104,128
bytes **including deliberate memory ballast**, not ordinary service memory.
The [archived report](../../benchmarks/results/resource-envelope.json) retains
the stage metadata. No production-engine bug was found in these drills.

## Changing-density extension

The `--growth` profile adds a complete antipodal-chord growth/drain cycle before
the existing 40,000 balanced updates: 1,040,000 real changes at one million
vertices. `Cycle` extends `Audit` with domain operation mapping and validation;
the same independent final topology/partner/retry certificate is reused by memory,
disk and backup drills. Every acknowledged transition must be real and have its
exact expected sequence/version. The graph visits 2.5 million edges, returns to
the original two-million-edge ring, then completes the balanced tail.

CI selects that profile without changing 128 MiB native, 512 MiB address-space
or dedicated 192 MiB filesystem limits. The isolated worker deadline becomes
300 seconds (outer timeout 360 seconds) for the larger trace. The report's
`working` field captures peak RSS through active updates and backup before
deliberate memory ballast; `peak` still includes exhaustion. `cycle` identifies
whether the prefix ran. Legacy balanced mode and its archived evidence remain.

All 866 local tests pass, including every possible small-graph edge/partner after
each owner/Service cycle change, restart/retry data flow, same-count wrong-topology
rejection and invalid-reference rejection before worker launch. Lint, formatting
and types pass. The extended installed Linux hard-limit run on `49bbe15`
([job 110799841329](https://github.com/sachncs/axiom/actions/runs/36995030785/job/110799841329))
failed with actual ENOSPC at `shutil.copyfile(backup, restored)`, after reaching
the memory/disk recovery steps. No successful final report was produced. This
contradicts changing-density backup/restore qualification: unused SQLite pages
are copied too, and the live source, backup master and independent restore must
coexist. The older balanced report does not cover this failure.

The focused correction compacts only a private staged backup with `VACUUM INTO`
when it contains free pages. It never vacuums the live authority, deletes the
backup master, changes checkpoint encoding or increases any resource cap.
Unlike in-place VACUUM, INTO avoids rewriting the original staging file through
a rollback journal. A second private output still requires transient headroom;
ENOSPC or interruption must clean staging and leave the live owner usable.
The progress handler checks the original deadline and is removed on failure;
final integrity/control, size, digest, mode, fsync and no-overwrite publication
checks remain. SQLite physical bytes may differ; explicit integer primary keys,
exact native checkpoint blobs, committed history and retry semantics must not.
See [SQLite VACUUM documentation](https://www.sqlite.org/lang_vacuum.html).
All 870 local tests, lint, formatting and source types pass with the correction.
Regressions compare every control/history/checkpoint column (including image
bytes), exact restore/retries/future matching, source main-file bytes and page
counts. Injected disk-full, allocation and deadline failures leave no published
image or temporary directory, clear the handler, and allow a successful backup
retry and subsequent graph mutation. A new installed Linux resource run is still
required before calling this correction qualified.

CI explicitly uses Bash with pipefail: logging through `tee` must not mask a
failed child or timeout. The first run's complete verified report establishes
its successful execution; the subsequent pipeline fix makes failures dependable.

RLIMIT_AS limits virtual address space, not page cache or aggregate deployment
memory. The filesystem fixture is not a production disk quota installation.
This is not a throughput gate, a power-cut test, replication, or billion-vertex
qualification. On 2026-10-02 the user deferred hardware power-loss validation for
this version. It remains future engineering with no power-cut guarantee; process
death and SQLite FULL cannot establish storage-device flush correctness.
