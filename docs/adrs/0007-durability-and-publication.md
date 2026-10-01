# ADR 0007: Separate undo, durable commit, publication, and acknowledgment

Date: 2026-10-01. Status: bounded durable batches/replay implemented;
native checkpoints implemented in opt-in v2; aggregation and full qualification pending.

## Context

An exception-safe in-memory graph is not durable after process death, machine
failure, or disk-full. A fast edge update is not an acknowledged service update.
Queries can also be wrong if they combine a new graph with an old matching.

## Decision

Use one sequenced transaction owner, a versioned WAL/commit marker, verified
checkpoints, bounded admission, and a bounded group-commit policy. The intended
ordering is admission → reserve/prepare → apply and certify privately → persist
the unambiguous committed outcome through the specified durability barrier →
publish coherent graph/matching version → acknowledge. Reads cannot observe the
private intermediate state. A batch may publish multiple sequential operations
together, but every outcome/version and acknowledgment must be well-defined.

Specify operation IDs/session sequence rules and bounded deduplication retention.
A crash after durable commit but before acknowledgment must allow a retry to
discover the original outcome without a second logical mutation. Torn/incomplete
records cannot become committed operations. Checkpoint/replay carries graph,
matching, sequence/dedup state, and backend/format versions required by the chosen
deterministic replay contract. Validate checkpoints/logs and recover only a
certified committed version.

Group commit is allowed to amortize persistence barriers for 10k/s, but batch
size, maximum waiting, journal capacity, admitted queue, and acknowledgment
latency must be bounded and measured. Do not count buffered/unflushed operations
as durable throughput. The barrier and supported failure model must be tested
on the actual filesystem/device. Process-kill recovery is **not** evidence of
power-loss durability; document hardware/OS assumptions and remaining tests.

On persistence failure, ambiguous commit/publication, corrupt recovery input, or
failed undo/certification, enter an explicit fail-stop/degraded state. Never
acknowledge success or continue serving uncertain state. Once durable commit is
known, recovery—not silently erasing the committed record—is the authority.

Partner/size queries are bounded and versioned; matching enumeration uses bounded
pages/streams and rejects stale versions or retains explicitly budgeted versions.
Queueing, reader retention, checkpoint copies, and query contention count toward
resource/latency qualification.

## Consequences and alternatives

An append-only text file without commit/recovery rules, fsync-less acknowledgment,
unbounded operation-ID caches, and eventual graph/matching consistency are rejected.
Durability introduces disk capacity, barrier latency, format compatibility, and
recovery obligations absent from the present Python matcher API.

## Evidence

`axiom.durable.Durable` implements FULL-WAL group commits, private native updates,
coherent queries, bounded contiguous-sequence retry retention, verified replay,
and fail-stop persistence/publication behavior. Tests exercise partial failures,
process death, actual SQLite page-limit exhaustion, recovery and original retries.
See [ADR 0009](0009-sqlite-wal-durable-owner.md) for choices and limits.
Native graph checkpoints/history compaction are implemented in explicit v2
(ADR 0010). Admission aggregation, power-loss
qualification, and sustained gates remain pending. Native undo alone still
provides only in-memory atomicity.
