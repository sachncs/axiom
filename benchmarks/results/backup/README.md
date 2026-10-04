# Bounded backup and independent disaster restore

> Historical native-matcher result only. The native matching engine described
> below was removed on 2026-10-04. These timings are not evidence for the current
> `basic` or `multilevel` paper modes and must not be used as their performance
> or reliability qualification. Current paper-mode measurements must be
> generated with `benchmarks/backup.py` and archived separately with mode,
> environment, and database-size details.

Core/backup source `e661452`, benchmark `ab37b27`. Isolated installed wheel SHA-256
`006372521cf3d12a57e851a6a17aae8c8a244dc50520a777f3fe585aafcbe1d2`.
Apple M3 Pro, 18 GiB, internal SSD/APFS, macOS 26.7.1, CPython 3.14.7,
SQLite 3.53.4. Sequential fresh processes with no competing local test/build jobs.
Archived benchmark runner excludes checkout package imports:

```bash
python -I runner/benchmarks/backup.py --source /private/local/path/source.db \
  --destination /private/local/path/backup.db --vertices 1000000 --updates 40000
```

Repeat at 32000 and 128000 vertices. Degree-four ring, real ring/chord edits
preserve the final topology but can change matching. Bootstrap commits 40000 real
updates, one native checkpoint at 32768 and a 7232-operation tail, with retry
retirement. Backup cap 64 MiB, native budget 1 GiB; FULL/fullfsync retained.
Independent source and disaster-restored audits check every expected edge, proper
maximal matching and exact partner digest. Original retry and expired-ID checks
pass. The source is closed before restoring; no second live native graph is
retained during backup. Restore uses a clone, preserving the master/hash.

| Vertices | Backup image | Backup incl. audit/copy/hash/sync | Open/recovery | Separate independent restore audit | Peak RSS |
| --- | --- | --- | --- | --- | --- |
| 32000 | 2.36 MB | 44.4 ms | 38.4 ms | 106.2 ms | 43.1 MB |
| 128000 | 4.67 MB | 60.2 ms | 45.4 ms | 423.5 ms | 60.4 MB |
| 1000000 | 25.62 MB | 122.6 ms | 102.3 ms | 3.336 s | 187.5 MB |

These are single staged samples, not an RTO SLA or a maintained backup schedule.
The image cap does not hard-limit total disk/RSS; retained SQLite free pages,
source/WAL, backup and restore clones require headroom. Backup occupies the owner;
no concurrent query/update latency is measured here. Maintenance-class admission
was added subsequently and is not measured by these records. The manifest's
sequence identifies the recovery point, not later acknowledged updates. No
replication, disk-loss zero-RPO or physical power-cut qualification is claimed.
[ADR 0013](../../../docs/adrs/0013-bounded-owner-backups.md).
