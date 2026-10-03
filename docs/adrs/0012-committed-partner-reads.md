# ADR 0012: Read committed partners without waiting for durable writes

Date: 2026-10-02. Status: implemented and regression-tested; short fixed-mix
latency measured; full production qualification pending.

## Context

Queued partner lookups execute in microseconds, but the earlier million-vertex
service runs have query p99 near 14 ms and maxima near 200 ms. Queries wait behind
group commits and checkpoint maintenance. Removing synchronization or reading
private partners would expose a graph/matching state that is not committed.
Copying the whole graph or matching before every batch would reintroduce the
`deepcopy`-style cost explicitly rejected in ADR 0003.

## Decision

Keep one mutation owner. Use the existing partner undo journal plus one uint32
first-write index per vertex. Untouched vertices return their current partner;
touched vertices return the earliest undo value. Couple that partner with the
pre-batch version until native publication. Repeated edits must not overwrite
the earliest index. Commit/rollback clears only touched indexes, without allocation.
The index adds `4*n` bytes plus vector metadata: approximately 4 MB at one million
vertices, included in the shared native budget and candidate-growth accounting.
It is ephemeral; checkpoint format and exact persisted state are unchanged.

Implementation update 2026-10-03: the dense per-vertex index described above
was replaced by an inline-plus-sparse open-addressed journal index sized to
distinct vertices touched by a batch. The coupled read and publication contract
is unchanged; see [ADR 0030](0030-sparse-committed-partner-index.md) for memory,
budget, rollback, and measured-trace evidence.

`Engine.committed_partner(vertex)` returns `(version, partner)` even during a
private transaction, including to another client thread. Ordinary native queries
still reject unpublished transactions. `Service.partner` returns an already
completed receipt from this view; its admission/completion shares the service
capacity and diagnostic counters. It can return the previous committed state
while the owner prepares a batch or waits for SQLite. This is a linearizable
published-prefix read, not access to arbitrary historical graph versions.
Wait for an update acknowledgment before issuing a read-your-write query.

## Thread safety and failure

Concurrent service submit/query/receipt/metrics/close calls use explicit locks.
Mutation remains single-owner; callers still coordinate the global contiguous
request sequence. The CPython binding retains the GIL through the entire coupled
native read/write/commit/rollback. Free-threaded CPython builds explicitly refuse
to import the engine: the standalone C++ core is not a concurrently callable API.
Adding arbitrary concurrent C++ writers or releasing the GIL requires a new
synchronization design and qualification, not a documentation-only promise.

A publication lock serializes read availability checks with owner failure/close
and full-audit failure detection. Corrupt native indexes fail closed. A delivered
read remains a result of its earlier publication even if a subsequent operation
fails. No private graph or partner array escapes. Owner-queued topology/pages and
partner reads may return different committed versions; compare versions when
combining results. There is no cross-call snapshot transaction.

## Consequences and verification

Native full audit and snapshot still retain the GIL and can delay client calls;
this change does not promise a worst-case latency bound. Python scheduling,
admission contention and resource pressure still count in observed latency.
Checkpoint I/O remains on the owner. SQL remains the durable authority, not live
adjacency: checkpoints plus committed tail recover the complete graph/matching.

Tests cover repeated partner changes, foreign readers during private edits, exact
rollback/commit/restore, index corruption, native budget rejection, paused update
and checkpoint persistence, and four writers/four readers against an exact
versioned reference. Native differential stress checks 9.6 million old-publication
reads under address/undefined-behavior sanitizers. The benchmark now declares an
exact 1:1 partner-query/update mix rather than allowing faster reads to silently
multiply offered query work. Retain old raw measurements unchanged and distinguish
their queued-read workload from new results. Overload/skew, hard process/disk
limits, backup and real power-cut qualification remain separate open gates.

Three short installed-wheel million-vertex runs measure 15.24k–15.39k durable
real updates/s with exactly one partner read/update, query p99 upper bound 0.5 ms
and peak RSS 214.3–214.9 MB. Exact independent audits/recovery pass. This is not an
independent open-loop query workload or maintenance latency bound. [Raw records,
source, artifact and limitations](../../benchmarks/results/service/README.md).
