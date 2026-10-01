# ADR 0011: Bound accepted work and aggregate it under one durable owner

Date: 2026-10-01. Status: local threaded service implemented/tested; concurrent
performance measured in short stages; sustained/full-service qualification pending.

## Context

`Durable.apply` accepts preassembled groups and rejects concurrent calls with
`BusyError`. This is a sound owner primitive, not a client aggregation layer.
Previously measured query latency was from synchronous queries after each group;
it excluded arrival contention and maintenance queue wait. Separate fsync barriers
for every individual client update would discard the throughput benefit of group
commit. An unbounded executor/future queue would instead hide overload in memory.

## Decision

Expose explicitly selected `axiom.service.Service`: one local worker owns the
native graph/matching and SQLite connection, with bounded admission from client
threads. New stores use checkpoint v2 (interval 32768 by default); existing v2
inherits persisted policy and existing v1 is refused, not silently migrated.
No transport, authentication, distributed ownership or new paper algorithm is added.

Bound **all outstanding receipts**, including active groups, queued updates,
queries and duplicate waiters, by `queue_capacity` (default 1024, cap 16384).
Do not free capacity merely when work leaves the queue. Full admission raises
`BusyError` synchronously: no receipt, mutation or sequence consumption. Input
validation rejects before admission. Require capacity <= persisted retry retention;
this covers the minimum in-flight envelope, not arbitrarily delayed external
clients or every already-old ID. Completed receipts retained by clients consume
caller memory and are not an unlimited server result cache. Queue bounds alone
are not hard RSS/WAL/disk limits.

Callers own one globally sequenced stream. Fresh IDs must be contiguous in
admission order, not merely submission intent across independent threads. Pending
identical canonical retries attach bounded waiters to the original work; conflicts
reject without mutation. Never run a pending retry ahead of its original update.
Already committed retries run on the durable owner's retained-outcome path;
conflicts/expiration return errors, never new mutations. Durable sequences and
`next_admission_sequence` are deliberately different high-water marks.

Aggregate fresh updates up to the persisted batch bound. A monotonic deadline from
the oldest admitted update limits **assembly wait** (default 1 ms, configurable
0–100 ms), not execution, disk or end-to-end latency. Group capacity flushes early;
closing bypasses assembly wait. Reserve the bounded work container before removing
admission records, so container allocation failure cannot lose accepted waiters.
Native preparation, certificates, FULL-WAL persistence and coherent publication
remain the existing `Durable` protocol, not a second implementation of durability.

Schedule at most one bounded read turn between ready update groups. Service reads
use the same owner and see one committed graph/matching version, never private
updates. They are **not FIFO barriers relative to pending writes**: they can read
an older committed prefix or observe later overlapping writes. Wait for an update
acknowledgment before submitting a read-your-write query. Grouped writes and queries
linearize through the owner; there is no eventually inconsistent matching view.
Independent full audits and explicit checkpoints are expensive maintenance reads,
not constant-time queries. They block this worker; no maintenance-isolated query
SLA is claimed. Versioned pages remain bounded and stale continuation rejects.
Receipt count does not bound the cost of repeated whole-graph audits/checkpoints;
exposing them to untrusted clients would also require class-specific work admission.

ADR 0012 supersedes the owner-queued scheduling for `partner` only: coupled
published-prefix reads can run during durability waits. Other reads and expensive
maintenance retain this owner protocol. The original queued-read measurements
below remain historical evidence, not measurements of the newer path.

Return `Receipt`, not a cancellable executor future. Receipt creation means
**accepted in memory**, not persisted. Only successful `result()` is a durable
update acknowledgment. Wait timeout leaves work accepted and possibly committed;
retain the receipt or retry the original ID/payload. Never allocate a new ID to
resolve uncertainty. No user callback runs on the owner thread, avoiding callback
reentrancy/deadlock and arbitrary owner-thread work. Completion carries monotonic
admission/start/delivery timing for separating assembly/queue wait from execution.
Once delivered, an outcome cannot be overwritten by later fail-stop handling.

Any fresh-group exception stops service admission, including a healthy native
capacity/preparation rejection: subsequent accepted IDs would otherwise create a
sequence gap. Fail unresolved current waiters and queued work explicitly; preserve
already delivered acknowledgments. Close/recover and reconcile the committed prefix.
Queries/retries can reject nonmutating input, stale versions, expiration or allocation
only when the durable owner remains healthy; unavailable/certificate/persistence
failures disable the service. Exceptions are never proof of noncommit.

`close` stops admission and drains accepted work before releasing the owner lock.
A join timeout means closing continues; call close again, not a competing owner.
Concurrent close calls reject. If database close fails, retain ownership and retry
release instead of silently losing the lock. Explicit close/context use is required.
The worker is daemonized: process exit can discard queued-only work; recovery and
original-ID retries, not queue persistence or finalizers, are the authority.

## Alternatives and consequences

Unbounded executors, per-edge sync acknowledgment, callbacks on the owner, hidden
ID assignment, cancellation after acceptance, graph sharding and stale matching
publication are rejected. Separate read snapshots/checkpoint workers may reduce
maintenance tails, but require bounded coexistence and atomic version ownership;
do not introduce an unlocked version-then-partner race. Scheduling priorities trade
query queue latency against update batching, and must be measured end to end.

## Evidence and remaining gates

33 service tests cover group outcomes/reference versions, concurrent clients and
queries, exact recovery, pending retries/conflicts, capacity including active work,
timeout without cancellation, draining/idempotent close, rejected policy/owner
release, expiry, stale pages, pre-SQL allocation failure and bounded-container
reservation failure. Persistence/commit/publication and response-delivery failures
verify fail-stop, exact committed prefixes and immutable delivered acknowledgments.
Process-death tests with queued clients interrupt before/after commit/publication;
they are not device power-cut tests. Isolated wheel/sdist CI smoke now exercises
service aggregation/query/drain/recovery, not checkout-shadowed imports.

The streaming [service benchmark](../service.md) separately measures queue wait,
execution, observed acknowledgment and concurrent query latency with fixed-size
histograms; records percentile overflow rather than clipping it. Qualification
still needs declared latency/resource gates, longer maintenance-inclusive churn,
skewed/hub/burst and open-loop overload traces, hard service resource admission,
backup/recovery limits and durability assumptions. This stage does not complete
the million-vertex 10k/s production goal or establish billion-vertex support.

Three short concurrent million-vertex runs (`546464e`) reach 13.8k–14.0k real
durable changes/s with approximately one queued partner query per real update,
six native checkpoints each, exact audits and live/recovered matching agreement.
Ack p99 upper bounds are 27.7–27.9 ms, query p99 13.8–14.2 ms, maxima ~200 ms.
Native query execution is tens of microseconds; queue/sync/maintenance delay
dominates. The proposed 10 ms query gate is not met. Raw commands/resource values
and workload limitations are in [service contracts](../service.md). Do not declare
completion from ~14-second closed-loop traces or from starting a longer soak.
