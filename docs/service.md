# Thread-safe local service

`axiom.service.Service` exposes one durable paper matcher to concurrent local
clients. It admits bounded work from threads, sequences accepted writes, groups
nearby updates into durable transactions, and serializes graph reads with those
transactions. `basic` is the default paper mode; `multilevel` is the other
supported mode. Both use the same SQLite durability and service path.

```python
from axiom.durable import Request
from axiom.service import Service

with Service("graph.db", n=128, mode="basic", queue_capacity=256) as graph:
    batch = graph.submit_batch(
        [
            Request(1, "insert", 0, 4),
            Request(2, "insert", 1, 5),
        ]
    )
    outcomes = batch.result(timeout=5)
    snapshot = graph.read_snapshot([0, 1], [(0, 4)]).result(timeout=5)
```

## Admission, ordering, and durability

`submit()` admits one request. The application assigns one contiguous sequence
stream and coordinates IDs with admission order across client threads. Nearby
individual requests may share one SQLite transaction. `submit_batch()` reserves
one explicit group as one transaction; it is never merged into another group.
Both paths use `Durable.apply()` and the paper matcher's sparse rollback journal.
An acknowledgment is returned only after the database commit and in-memory
publication both succeed.

Active, queued, and read work all count against `queue_capacity` (default 1024,
maximum 16384). `query_reserve` defaults to one slot (zero for capacity one),
leaving admission room for reads during update saturation. A `BusyError` means
the work was not admitted and its sequence was not consumed. Accepted receipt
timeouts do not cancel work or establish non-commit; retain the receipt or retry
the original sequence and payload. Conflicting retries reject. Uncertain storage
or publication failures stop the owner and fail remaining receipts. Close and
recover before retrying the durable prefix.

`close()` stops new admission and drains accepted work before releasing the
single-process owner lock. A timed-out close continues draining; call it again.
Use a context manager or explicitly close every service.

## Reads and maintenance

`partner`, `has_edge`, `page`, `read_snapshot`, `history`, `status`,
`checkpoint`, `check`, and `backup` return receipts. They execute on the same
owner worker, so they never observe a private partially applied update group.
Single queries carry the version they read. `read_snapshot()` returns aligned
partner/edge results for one version, with at most 4096 total queries. It is a
bounded read operation, not historical MVCC. Wait for a write receipt before a
read-your-write query; queued reads do not promise to be barriers behind every
pending update.

`checkpoint()` advances SQLite WAL maintenance only; it does not serialize or
compact paper algorithm state. `history()` exports bounded pages from the
append-only hash chain. `check()` runs a complete graph/matching audit, and
`backup()` publishes a bounded owner-consistent database image without
overwriting an existing target. Automatic WAL and manual maintenance consume
the same serialized owner; expensive explicit audits/backups also obey
`maintenance_capacity`.

`metrics()` reports bounded admission counters and worker state; it is not a
graph snapshot. Queue limits bound admitted work, not total process RSS, SQLite
WAL/SHM, or filesystem/device caches. Enforce deployment memory/disk limits at
the process and volume layers as well as through the database page cap.

## Threading and deployment boundary

Concurrent client threads are supported on GIL-enabled CPython. One worker owns
the `Durable` instance and all matcher mutation; direct concurrent use of a
`Matcher` is not supported. The database owner uses a POSIX advisory lock and
SQLite WAL. This is a single-host service, not a network protocol or replicated
service. Power-cut behavior depends on the complete filesystem/device stack and
has not been hardware-qualified; see [operations](operations.md) for deployment
gates and recovery practices.

The durable engine replays the bounded operation history on startup. No
paper-state snapshot/decoder or history compaction is implemented, so recovery
time increases with accepted history length. See [durable contracts](durable.md) and [ADR
0009](adrs/0009-sqlite-wal-durable-owner.md).
