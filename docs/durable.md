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

Default replay history is 65,536 operations including no-ops/retry retention.
New requests reject when it fills; retries still work. Native checkpoints and
safe history/dedup retirement are not implemented. SQLite WAL checkpoints are
physical database maintenance, not Axiom graph checkpoints.

The separate [native checkpoint primitive](checkpoint.md) is now implemented and
tested. It does not by itself change this durable format or remove its history
limit; atomic image/control/history publication and retirement are still pending.

Defaults: native budget 1 GiB, group bound 256, database page budget 64 MiB. Page
budgets exclude WAL/SHM, allocator/RSS, Python results, and filesystem overhead.
Cache/journal-size settings do not hard-bound those resources. There is no
asynchronous request aggregator, network API, maximum group-wait SLA, arbitrary
graph import, or Windows owner locking yet.

Remaining gates: native checkpoints/compaction, bounded dedup retirement, client
aggregation/admission, recovery/backup limits, sustained balanced/skewed churn,
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
