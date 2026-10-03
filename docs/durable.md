# Durable paper matching

`axiom.durable.Durable` owns one `Matcher` in either supported paper mode,
`basic` or `multilevel`, and stores its accepted update stream in SQLite. The
default is `basic`. There is no native matching algorithm or compatibility
reader. `axiom.storage.Packed` is only the compact graph representation used by
the matcher; it does not select a matching algorithm.

```python
from axiom.durable import Durable, Request

with Durable("graph.db", n=128, mode="basic") as graph:
    outcomes = graph.apply([
        Request(1, "insert", 0, 4),
        Request(2, "delete", 0, 4),
    ])
    assert graph.check()

# Reopen by replaying the exact committed operation stream.
with Durable("graph.db", mode="basic") as graph:
    assert graph.status()["sequence"] == 2
```

## Commit and recovery contract

`apply()` accepts a bounded list/tuple of typed requests with contiguous new
sequence numbers. One call is one atomic durable group. To keep paper undo
storage bounded, the private Matcher starts with at most eight updates per
journal slice. If a component reaches its bounded journal capacity, Durable
replays the committed prefix and retries the whole group with half-sized
slices, down to one update per slice. Intermediate matcher states are not
observable through `Durable`: its
exclusive owner lock spans every slice, and `Service` sends reads through the
same serialized owner. The owner retains the bounded operation rows and calls
SQLite only after all slices pass their invariants. One SQLite transaction
inserts every operation and updates the control sequence, graph version, and
hash-chain tail together; only after that commit does the call acknowledge.

If an earlier private slice succeeds but a later slice fails before persistence,
the owner reconstructs its previously committed matcher by replaying the
database prefix while still holding the lock. It verifies the sequence, hash
chain, paper transitions, and final matching before accepting more work. A
failed reconstruction fail-stops the owner. The replay path is also used
before retrying a journal-capacity failure. A single update that exceeds a
component's own fixed journal cap still fails atomically; it is never
acknowledged as committed. Persistence or post-commit publication uncertainty
also fails closed; close and recover before retrying the same sequence and
payload. This avoids retaining a graph-sized snapshot or all per-slice
journals for the entire user batch, at the cost of replay work on the
exceptional rollback path.

SQLite WAL with full synchronization is required. A POSIX advisory owner lock
prevents two cooperating processes from writing the same database. Calls on a
busy `Durable` owner fail fast with `BusyError`; `Service` provides bounded
thread-safe admission and serialization for concurrent clients. Do not modify
the database directly or use uncoordinated copies of its live files.

Identical retries return the saved outcomes. Conflicting retries, gaps, and
malformed input reject before mutation. New updates stop at the configured
`max_operations` limit. `max_batch`, `max_operations`, mode, vertex universe,
and graph initialization width are persisted; changing explicitly supplied
values on reopen is rejected. Existing unsupported schemas, including native
matcher stores and the former checkpoint format, are rejected rather than
silently migrated. Export a backup and initialize a new store to change formats.

`partner`, `has_edge`, `page`, and `read_snapshot` are serialized against
updates by the durable owner. `read_snapshot` returns aligned partner and edge
answers for one graph version. `history` exports a bounded, verifiable page of
the append-only operation chain. `checkpoint()` performs SQLite WAL maintenance
only; it is not a graph-state checkpoint and does not shorten replay.

## Limits and qualification status

The operation history is bounded by `max_operations` (default 1,000,000), and
the SQLite main database has a page limit (default 64 MiB). These limits do not
hard-bound total process memory, WAL/SHM files, filesystem cache, or device
write amplification. Monitor and provision those separately. When a hard
resource limit is reached, reject new work rather than acknowledge an update
that could not be committed.

Recovery reconstructs the selected paper matcher from its initialization graph
and deterministically replays the full committed history. Its startup work is
therefore linear in retained operations. There is not yet a paper-state decoder
or compacting algorithm checkpoint. This is the principal scale/recovery-time
limit of the current durable paper path; bounded atomic batches do not solve
that separate issue. Recovery audits the result and refuses service if stored
history, checksums, versions, or paper transitions disagree.

This design provides a single-host durable owner, not replication, network
transport, or hardware-independent power-loss guarantees. FULL synchronization
requests the strongest SQLite/filesystem contract available on the host; actual
device behavior still requires deployment-specific qualification. Hardware
power-cut tests are deferred and are not claimed by the test suite.

See [service contracts](service.md), [graph modes](modes.md), [storage](storage.md),
and [ADR 0009](adrs/0009-sqlite-wal-durable-owner.md).
