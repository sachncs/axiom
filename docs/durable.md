# Bounded durable native batches

`axiom.durable.Durable` adds persistence to the explicitly selected native core.
It is an engineering stage, **not yet a qualified production service**.
[ADR 0009](adrs/0009-sqlite-wal-durable-owner.md) explains the choice of SQLite WAL
instead of a new physical transaction/recovery subsystem.

```python
from axiom.durable import Durable, Request

# Private, existing local POSIX directory; only one live owner may open this store.
with Durable("graph.db", n=128) as graph:
    result = graph.apply([
        Request(1, "delete", 0, 1),
        Request(2, "insert", 0, 4),
    ])
    version, partner = graph.partner(0)
    assert version == result[-1].version

# Omit n to recover the original universe/genesis and exact deterministic state.
with Durable("graph.db") as graph:
    assert graph.apply([Request(1, "delete", 0, 1)])[0] == result[0]
```

## Guarantees and error handling

- `apply` accepts a bounded list/tuple and publishes atomically after FULL-WAL
  commit. Returned outcomes, including no-ops, are durable under the declared
  SQLite/filesystem/device assumptions. Full-sync/checkpoint full-sync are requested
  on macOS; no option silently downgrades to buffered acknowledgment.
- New sequences start at 1 and must be contiguous. The application owns this one
  stream. Identical canonical retries return original outcomes/versions;
  conflicting or reordered requests reject before mutation.
- Outcome versions identify each operation's mutation position. Queries see the
  group's final published version, not private intermediate versions. `partner`
  and `has_edge` return `(version, result)`; `page` is bounded/versioned and rejects
  stale continuation versions.
- Concurrent calls fail fast with `BusyError`, not an unbounded queue or private
  visibility. Retry admission under a bounded caller policy. Do not allocate new
  IDs for an operation whose acknowledgment may have been lost.
- `CapacityError` rejects before new mutations on group/history exhaustion.
  Prevalidated input errors leave the owner usable. Native preparation failures
  roll back and permit reuse only if the engine remains healthy and undo succeeds.
- Persistence/publication exceptions are **ambiguous outcomes**, never success
  acknowledgments or proof of noncommit. Later calls raise `UnavailableError`;
  close/recover and retry original sequences. Full-audit failure also disables
  the owner. Corrupt/incompatible recovery refuses service with `RecoveryError`
  or the underlying storage/allocator error.

Advisory locking cannot stop processes that ignore the protocol. Direct SQL,
private Python attributes, and independent live database users/backups are not
supported public update/query APIs. `width` is initialization-only on a new store;
recovery always uses persisted genesis.

## Bounds and pending work

Default legacy v1 history is 65,536 operations including no-ops. New requests
reject when it fills; retries still work. Existing stores are not silently upgraded.
SQLite WAL checkpoints are physical maintenance, not Axiom graph checkpoints.

New stores may explicitly select checkpoint v2:

```python
with Durable("checkpointed.db", n=1_000_000,
             checkpoint_interval=32768, retain_operations=16384) as graph:
    # Apply contiguous requests as above. Automatic maintenance runs before the
    # next fresh group after 32768 operations since the latest graph checkpoint.
    graph.checkpoint()  # Optional manual maintenance; graph version is unchanged.
    floor = graph.status()["retired_floor"]
```

V2 atomically commits the exact native image, control generation, checksum anchors
and history retirement. At checkpoint sequence C, records through
`max(0, C-retain_operations)` retire. Those IDs raise `ExpiredError`, never mutate
again or return an invented outcome. Retained identical retries still return
their original outcomes. Size retention for the client's in-flight/retry window;
expiration is not evidence whether an old uncertain request committed.

Policies persist: reopening without overrides inherits interval/retention/batch/
history bounds; conflicting overrides refuse recovery. Require retention >= batch
and interval + retention + batch <= history bound. The bound now limits retained
rows, not lifetime sequence. Recovery restores/audits exact partners and graph,
verifies the retained cache, and replays only the post-checkpoint suffix.
[ADR 0010](adrs/0010-native-checkpoint-and-history-compaction.md) gives the protocol
and failure boundaries. Automatic maintenance is a separate transaction preceding
the fresh update: it can retire retries even if that new update later fails.

The owner gate also covers checkpoints; concurrent calls get `BusyError`. Any
uncertain checkpoint persistence/publication disables the owner; close/recover.
Image capacity (`max_snapshot_bytes`, default 64 MiB) is admitted before growth.
Retirement bounds logical history, not physical file/RSS: old/new images, binding
buffers, WAL and reusable SQLite pages still consume space. A million-vertex,
degree-four image alone is 24,000,040 bytes. Maintenance-inclusive latency and
sustained throughput are not yet qualified.

Defaults: native budget 1 GiB, group bound 256, database page budget 64 MiB. Page
budgets exclude WAL/SHM, allocator/RSS, Python results, and filesystem overhead.
Cache/journal-size settings do not hard-bound those resources. The separate
[local service](service.md) now provides bounded asynchronous aggregation; this
primitive itself remains fail-fast. There is no network API, end-to-end latency
SLA, arbitrary graph import or Windows owner locking yet.

Remaining gates: maintenance/concurrent scheduling performance, full resource admission,
recovery/backup limits, sustained balanced/skewed churn,
concurrency/overload, power-loss assumptions/tests, and the accepted million-vertex
**10k real durable updates/s including queries** qualification.

## Measure this stage

```bash
python benchmarks/durable.py --database /private/local/path/fresh.db --vertices 32000
```

The benchmark toggles a fixed pool of up to 8192 ring/non-ring edge pairs sampled
across the vertex universe while retaining average
degree four. It counts only real committed/published changes. Whole-trace timing
includes partner queries, sampled retries, request preparation, SQLite automatic
WAL checkpoints, and disk sampling. Admitted-to-acknowledged p99/max are reported.
Independent exact topology/proper-maximal matching and exact recovery are verified
separately; construction/audits/recovery times are explicit. Short bounded-history
results do not qualify sustained native-checkpoint/maintenance/soak behavior.

## Staged evidence

Measured implementation: `dfaf93a`, Apple M3 Pro / 18 GiB RAM / internal SSD/APFS,
macOS 26.7.1, CPython 3.14.7, SQLite 3.53.4. Sequential fresh-process runs use
20,000 pairs, 256-operation groups, 20,000 partner queries, and 1,280 verified
retry outcomes each. Grouping is essential: this is not 30k separate sync barriers
per second. No fsync-less results are counted.

| Vertices | Real durable changes/s | Acknowledgment p99 | Process peak RSS |
| --- | --- | --- | --- |
| 32,000 | 31,371 | 18.66 ms | 41.9 MB |
| 128,000 | 31,054 | 14.21 ms | 51.6 MB |
| 1,000,000 (three seeds) | 30,377–30,943 | 14.36–15.51 ms | 132.7–133.1 MB |

Raw: [32k](../benchmarks/results/durable/32k-599.json),
[128k](../benchmarks/results/durable/128k-599.json),
[million 599](../benchmarks/results/durable/million-599.json),
[600](../benchmarks/results/durable/million-600.json),
[601](../benchmarks/results/durable/million-601.json).
Every independent exact graph/proper-maximal audit and exact matching recovery
check passes. Million-vertex replay/open takes approximately 0.410–0.416 seconds;
its independent post-recovery public-query audit takes a separate 3.33–3.36
seconds. Three traces last only 1.29–1.32 seconds each. They demonstrate durable
compute/I/O headroom, **not sustained native-checkpoint qualification** or
hardware-independent guarantees. The fixed 8192-pair pool does not substitute
for broad/skewed, maintenance-inclusive and concurrent-client workloads.

Local verification: 513 tests pass with 84.28% Python source coverage; 123 focused
tests pass under optimized Python; isolated wheel/sdist installs pass durable
commit/recovery/original-retry/close smoke tests. C++ coverage is not measured by
that Python coverage number. CPython 3.14 measurements do not establish a new
supported-version policy.

## Opt-in checkpoint v2 evidence

Source `525cbca` (`f9b5d9b` durable implementation), same declared M3 Pro/APFS
machine. Three fresh million-vertex traces each acknowledge 200,000 real changes,
execute 100,000 partner queries and verify 6,400 retry outcomes, with six native
checkpoint/retirement transactions inside headline timing. Interval 32768,
retention 16384, supplied group bound 256; FULL/fullfsync remain enabled.

| Million-vertex seeds | Real acknowledged changes/s | Ack p99 | Ack max | Peak RSS |
| --- | --- | --- | --- | --- |
| 599–601 | 27,585–28,451 | 14.16–15.02 ms | 192.64–203.97 ms | 219.3–221.4 MB |

All independent exact graph/proper-maximal audits, exact matching recovery,
retained retries and expiration checks pass. Final sequence 200000, checkpoint
196608, retired floor 180224, retained rows 19776. Recovery/open takes
0.097–0.099 seconds, with a separate approximately 3.2-second independent audit.
Sampled database/WAL/SHM peak is 55.06 MB, not a hard disk bound.
[Raw evidence, commands and limitations](../benchmarks/results/compaction/README.md).

Traces last only 7.03–7.25 seconds. Six of 782 groups include native checkpoints,
so p99 can miss their roughly 200 ms tail; the maximum is important. Queries run
after acknowledgments, not concurrently during maintenance, and do not include
client queue wait. Thus these are **not** concurrent-query latency or long-soak
qualification. Fixed-pool, skewed/overload and full-service resource gates remain
open. Current local verification: 571 tests, 85% rounded Python source coverage
(not C++ coverage), 101 focused optimized-mode tests, strict typing/lint and
isolated wheel/sdist checkpoint/compaction/recovery/retry smoke tests pass.
