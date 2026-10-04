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

Applications can register exact strings, signed 64-bit integers, or UUIDs with
`register_identifier(value)`. Its receipt completes after the mapping is
durable; retain and use the external ID in application code.
`submit_external()` and `submit_external_batch()` accept `ExternalRequest`
values, while `partner_external()`, `has_edge_external()`, and
`read_snapshot_external()` return external identities at a coherent committed
version. Register every endpoint before submitting updates. An unknown ID
rejects that request without stopping a healthy Service. Mappings are
immutable and never reused, but registration is limited by the configured
fixed vertex count: dynamic vertex growth and deletion are not supported. A
verified SQLite v1 operation log is transactionally migrated to v2 on open.

```python
from uuid import uuid4

from axiom.durable import ExternalRequest
from axiom.service import Service

worker, job = uuid4(), uuid4()
with Service("graph.db", n=128) as graph:
    graph.register_identifier(worker).result(timeout=5)
    graph.register_identifier(job).result(timeout=5)
    graph.submit_external(ExternalRequest(1, "insert", worker, job)).result(timeout=5)
    print(graph.partner_external(worker).result(timeout=5))
```

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
append-only hash chain. `check()` runs a complete graph, matching, auxiliary
index, and selected paper-mode structure audit, and
`backup()` publishes a bounded owner-consistent database image without
overwriting an existing target. Automatic WAL and manual maintenance consume
the same serialized owner; expensive explicit audits/backups also obey
`maintenance_capacity`.

`metrics()` is a thread-safe, in-process diagnostics interface. Existing state,
capacity, outstanding, accepted/completed, grouping, and sequence keys are
unchanged. It also reports `failed_work` and fixed-size cumulative latency
histograms for `update`, `read`, and `maintenance` work. Each class has
`<class>_latency_le_<bound>_ns` buckets at 100,000; 500,000; 1,000,000;
5,000,000; 10,000,000; 50,000,000; 100,000,000; 500,000,000;
1,000,000,000; 5,000,000,000; and 30,000,000,000 ns, plus
`<class>_latency_le_infinity_ns` and `<class>_latency_sum_ns`. Buckets are
cumulative (`le` means duration less than or equal to the bound); infinity is
the total observation count. Durations and sums use monotonic nanoseconds and
cover receipt admission through receipt completion, including time waiting in
the service queues. They are cumulative for this Service object's lifetime and
are not reset on reads.

An update is newly admitted mutation work, including external-ID registration
and fresh batches. A historical retry that is checked against durable history
is classified as read work. Reads that run maintenance (checkpoint, full audit,
or backup) are classified as maintenance rather than read. `accepted` and
`completed` count admitted receipts, including identical retries that share a
pending work item. `failed_work` counts internal work items resolved with an
exception, including accepted queued work failed during fail-stop; it is not a
failed-receipt count (a shared retry can add receipts without adding a work
item). Synchronous validation, capacity, overload, and closed-service
rejections are deliberately not counted: they were never admitted, and
instrumenting every rejection is not part of this interface. Consequently
these counters do not expose a rejection rate or derive an updates/sec or query
rate. Histogram cardinality and storage are constant per Service regardless of
operation lifetime; no per-operation samples or graph snapshot are retained.

Metrics are snapshots of service counters, not graph state, and provide no
exporter, OpenTelemetry/Prometheus integration, process-memory measurement,
matching/edge/vertex counts, database/WAL size, recovery duration, or rollback
telemetry. Queue limits bound admitted work, not total process RSS, SQLite
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
