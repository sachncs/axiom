# 0020: Isolated resource exhaustion and exact recovery

Date: 2026-10-02. Status: million-vertex Linux exhaustion/recovery stage passed;
production deployment quotas and hardware power-loss validation pending.

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

CI explicitly uses Bash with pipefail: logging through `tee` must not mask a
failed child or timeout. The first run's complete verified report establishes
its successful execution; the subsequent pipeline fix makes failures dependable.

RLIMIT_AS limits virtual address space, not page cache or aggregate deployment
memory. The filesystem fixture is not a production disk quota installation.
This is not a throughput gate, a power-cut test, replication, or billion-vertex
qualification. Hardware power-loss validation remains outstanding; process death
and SQLite FULL cannot establish storage-device flush correctness.
