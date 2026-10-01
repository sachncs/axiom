# Bounded local native service

`axiom.service.Service` aggregates individually submitted updates from local
threads through one native/FULL-WAL owner. This is explicitly selected production
engineering, not the paper engine or a qualified network service.
[ADR 0011](adrs/0011-bounded-service-admission.md) documents the tradeoffs.

```python
from axiom.service import Service
from axiom.durable import Request

with Service("service.db", n=128) as graph:
    a = graph.submit(Request(1, "delete", 0, 1))
    b = graph.submit(Request(2, "insert", 0, 4))
    first, second = a.result(timeout=5), b.result(timeout=5)
    version, partner = graph.partner(0).result(timeout=5)
    assert version >= second.version
    timing = b.timing()  # Admission/start/completion monotonic nanoseconds.
```

Use a private local POSIX directory and a fresh path or compatible checkpoint-v2
store. New stores default to interval 32768/retention 16384; reopen inherits stored
policy. Legacy v1 refuses service; there is no implicit migration. Native budget,
image cap, database pages and persisted batch/history policy are as in
[durable contracts](durable.md). `queue_capacity` defaults to 1024, caps at 16384,
and cannot exceed retention. `batch_wait_ms` defaults to 1 and caps at 100.

## Admission and acknowledgment

- One application-owned request stream. Coordinate sequence assignment with
  admission order across threads; future sequence gaps reject synchronously.
- Active work, queued work, queries and pending duplicate waiters all consume the
  outstanding cap. `BusyError` means nothing was admitted; retry admission under
  bounded caller policy using the same ID. Pending canonical retries share one
  original outcome; conflicting payloads reject. Retired IDs raise `ExpiredError`.
- A receipt is only in-memory acceptance. Successful update `result()` follows
  FULL-WAL commit and coherent publication. Timeout **does not cancel** accepted
  work or prove noncommit. Keep the receipt or retry the original ID/payload.
- Fresh-group failure stops the service and resolves remaining receipts as errors.
  Even a healthy preparation rejection stops it to avoid admitted sequence gaps.
  Recovery decides the committed prefix. Previously delivered success stays success.
- `close(timeout=...)` stops admission and drains. Timeout means drain continues;
  call close again. Explicit context/close use is required. Process exit may lose
  queued-only work, never converting it into a successful acknowledgment.
  Concurrent close callers may receive `BusyError`; this prevents double release.

## Query and scheduling contract

`partner`, `has_edge`, `page`, `status`, `checkpoint` and `check` return receipts.
`partner` reads the last publication directly, including while a private batch
waits for durability. It returns an already completed receipt, never private
partners. Other queries run on the owner between bounded update groups.
They are not FIFO barriers against pending updates: wait for the update result
before submitting a read-your-write query. They may include overlapping newer
updates but never private intermediate graph/matching state. Stale page versions
reject without disabling a healthy owner; audits/certificate failure fail closed.

`metrics()` is an immediate bounded admission diagnostic, not a graph query.
`next_admission_sequence` is **not** the durable sequence; `status().result()`
reports the committed one. Assembly wait is not a maximum acknowledgment SLA.
Concurrent client calls and receipt waiters are supported on GIL-enabled CPython;
free-threaded engine builds explicitly reject. One worker owns mutation. There is
no cross-call snapshot: compare returned versions when combining queries.
[ADR 0012](adrs/0012-committed-partner-reads.md) records synchronization and the
additional budgeted 4 bytes/vertex. Native checkpoints/full audits block the GIL;
SQLite I/O blocks the worker but not published partner reads. Receipt timing separates
queue/assembly wait from execution; client-observed latency also includes delivery
and scheduling. Never measure only ordinary native edits to claim service latency.

## Measure concurrent clients

```bash
python benchmarks/service.py --database /private/local/path/fresh.db \
  --vertices 32000 --pairs 100000 --seed 599
```

Four update clients each keep at most 64 individual updates in flight; one query
client uses windows of 128 reads. Shared server capacity is 512. Streaming churn uses
the same uniform-vertex fixed 8192-pair pool as the earlier durable benchmark;
headline timing includes queries, original retries, native/SQLite checkpoints,
construction of requests and client scheduling. The current benchmark issues exactly
one partner query per real update; any remaining queries after writers stop also count
in headline time. Report how many completed while writers were active.

Histograms use fixed 100us buckets below one second and an explicit overflow bin;
p99 is a conservative bucket upper bound, not an exact sorted sample. Percentile
overflow reports `None`, never a clipped passing latency. Exact maxima are retained.
Histogram memory does not grow with operation count, enabling longer runs. Live
matching pages capture exact partners; independent recovered topology/proper-maximal
matching and exact partner digest are checked outside headline update timing.

This is a bounded **closed-loop** workload: clients wait for their windows. It does
not model externally offered arrival rate, overload, network delay, hub degrees,
hard RSS/disk caps, device power loss, backup or a production recovery SLA. The
service and benchmark do not by themselves complete the accepted full-service
qualification goal.

## Earlier queued-read evidence

Source `546464e`, service `1a6bafb`; Apple M3 Pro / 18 GiB / internal SSD/APFS,
macOS 26.7.1, CPython 3.14.7, SQLite 3.53.4. Fresh sequential processes, 200000
real updates each; four update clients and one pipelined query client, supplied
one request at a time. FULL/fullfsync remain enabled. Each run completes 200064
partner queries, 199936 while writers are active, 1600 original retry outcomes
and six native checkpoints. Largest actual group 256; peak outstanding 384/512.

| Vertices | Real durable changes/s | Ack p99 upper bound | Query p99 upper bound | Peak RSS |
| --- | --- | --- | --- | --- |
| 32000 | 14528 | 27.1 ms | 14.0 ms | 48.2 MB |
| 128000 | 14319 | 27.6 ms | 14.4 ms | 64.0 MB |
| 1000000, three seeds | 13795–14036 | 27.7–27.9 ms | 13.8–14.2 ms | 210.1–210.6 MB |

Million-vertex traces last 14.25–14.50 seconds. Ack maxima are 198.5–205.4 ms;
query maxima 189.2–193.9 ms. Query execution maxima are only 28.5–55.2 us;
query queue-wait p99 upper bounds are 12.4–12.7 ms. Scheduling/persistence,
not just native lookup compute, therefore needs attention. The proposed 10 ms
query p99 gate is **not met**; deployment latency gates remain to be agreed.

All independent exact topology/proper-maximal audits and exact live-to-recovered
partner digests pass. Recovery/open is 0.097–0.099 seconds plus a separately timed
approximately 3.2-second independent audit. Native capacity remains 73.01 MB;
sampled database/WAL/SHM peak is 55.06 MB. These are measured process/resource
values, not hard enforced service RSS/disk limits.
[Raw records, commands and limitations](../benchmarks/results/service/README.md).

Query and update RNG streams are independent here; traces differ from the earlier
durable benchmark, which used one RNG for both. Do not interpret differing rates
as an identical-trace causal speedup/slowdown. Tests verify that the service update
trace and matching do not depend on client/query/group scheduling.

For a duration-bounded soak, choose a high pair ceiling and a watchdog with drain
headroom, e.g. `--pairs 100000000 --duration 1800 --timeout 1900`. Duration stops
**new admission**, then drains accepted updates/queries and audits the actual
completed prefix. `requested_duration_completed` must be true; reaching the pair
ceiling early is not a passing 30-minute soak. A pending/started soak is not evidence
of successful completion. Closed-loop/fixed-pool and all other limits above remain.

## Committed-partner query stage

Source `b8c36e7`, benchmark `ec9926e`, same machine and isolated installed wheel.
Three million-vertex seeds each acknowledge 200000 real updates and complete
exactly 200000 published partner reads. Rates are 15.24k–15.39k changes/s; query
p99 upper bound 0.5 ms, maxima 0.614–0.715 ms. Ack p99 is 25.9–27.0 ms, maxima
200.3–207.9 ms. Native retained capacity is 77.01 MB, peak RSS 214.3–214.9 MB.
Exact topology, proper maximal matching and live/recovered partner audits pass;
update/final matching digests agree with the earlier same-seed traces.
[Raw provenance and limits](../benchmarks/results/service/README.md).

This fixed-credit 1:1 mix differs in query scheduling from the earlier queued
workload. Reads may observe the preceding publication; they are not independently
offered across every maintenance interval. These ~13-second traces do not prove
an overload/skew SLA or hard memory/disk bounds. The new code still needs a soak;
the completed old-code 30-minute result is recorded separately in the raw README.

Earlier baseline verification: 616 tests, 141 focused optimized-mode tests, strict typing/lint,
isolated wheel/sdist service/compaction/recovery smoke, documentation examples and
site build/link checks pass. The earlier coverage run measured 96% service and
85% rounded total Python source coverage (not C++ coverage). The added duration/
scheduling tests exercise benchmark controls; they do not establish a soak result.
