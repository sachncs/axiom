# 0021: Bound moderate-row scans instead of indexing every degree-64 adjacency

Date: 2026-10-02. Status: candidate implemented; local correctness/sanitizers,
CI and installed fixed-trace comparison pass; wider service qualification pending.

## Context and decision

The degree-64 million-vertex diagnostic rejects its 1 GiB native budget before
any acknowledgment. At threshold 32 all rows become indexed. Sixty-four million
directed keys require 134,217,728 slots of 16 bytes: 2 GiB before adjacency or
metadata. Ring construction already reserves/builds that index once; repeatedly
growing it is not the cause of this minimum. Raising the budget would conceal
the storage-policy cliff, not improve efficiency.

Move index promotion to degree 128. Unindexed membership/location searches remain
bounded below 128 neighbors; large hubs still receive the same index. Preserve
reserve-before-mutation, exact logical/index-flag rollback, mandatory local/full
certificates, deterministic matching and existing budget/ownership contracts.
No checkpoint format change is needed: indexes are derived during restore, and
exact persisted graph/partners/version remain authoritative.

This does not eliminate hash overhead for arbitrarily dense graphs or promise
billion-vertex support. Indexed rows/capacity may persist after shrinking until
the existing bounded compaction path rebuilds them. A larger bounded scan is a
compute/memory tradeoff that requires measurement, not a free speedup claim.

## Verification and evidence required

Local tests force failed promotion at degree 128, reuse after failure, exact
promotion/index-count rollback and successful repromotion. A degree-64 ring fits
a 200 KiB small-graph budget without a hash table, independently checks all
neighbors, rolls back edits and restores exact checkpoints. Different arena row
orders after logical undo must still produce identical future matching decisions;
each checkpoint encoding independently round-trips exactly.

The complete local suite passes 815 tests including the fixed-profile helper;
ASan/UBSan pass 200,000 differential storage edits (now 256 vertices to cross the
new boundary) and 100,000 matching edits. Lint/format/types pass. These are
correctness gates, not throughput qualification.

The removed `benchmarks/index.py` used a public `Trial` class to compare fixed real traces
and partner checks without producer misses changing the workload. Constructor,
timed updates, native allocation, process RSS, checkpoint hash and exact matching
hash remain separate. The [installed comparison](../../benchmarks/results/independent/index-policy-fixed.json)
uses 18 sequential fresh processes: three baseline/candidate repetitions per
degree, 8,192 vertices and 200,000 real edits each. All checkpoint and matching
hashes agree. This is historical evidence for the removed native matcher, not
current `Packed` or paper-mode qualification. Degree-64 native allocation fell from 20,621,024 to 3,843,808 bytes
(81.4%), but median core rate falls from 2.862 million to 1.751 million updates/s
(38.8%). Degree-four median falls about 2.7%; degree-16 is approximately unchanged.
This is an explicit compute/memory tradeoff, not a throughput improvement. The
short nondurable traces do not establish durable service performance or tail SLAs.

The following stages repeat the rejected million-vertex stage under the
same native cap and the existing hub/durable release gates. Old degree-four soaks
must not silently become new-binary qualification.

The [candidate million-vertex degree-64 diagnostic](../../benchmarks/results/independent/dense64-candidate-million.json)
now constructs under the same 1 GiB native cap and passes exact recovery after
200,938 acknowledged real updates and 230,013 coherent queries. Native allocation
is 469,142,880 bytes, but peak process RSS is 1,345,044,480 bytes. Throughput is
only 6,640.4/s including drain, with 76,816 update IPC drops and 52,048 Busy
rejections. All three latency histograms exceed their one-second p99 range;
maximum ack/query latency is 2.390/1.510 seconds. Six checkpoints complete.
This fails degree-64 throughput/latency qualification. Bounded scans and larger
full-audit/image/SQLite maintenance costs require separate profiling; the fixed
core comparison alone does not identify the service bottleneck. The accepted
release workload remains degree four, not this denser diagnostic.

The [new-binary degree-four smoke](../../benchmarks/results/independent/candidate-sweep-million.json)
passes under explicit 128 MiB native and 64 MiB database/image caps: 329,959 real
updates at 10,975.4/s including drain, 299,889 coherent queries, ten checkpoints
and exact recovery. Ack/query p99 upper bounds are 185.6/1.8 ms. There are no
IPC drops or Busy rejections; producer misses remain reported. Native allocation
is 49,142,880 bytes and peak owner RSS 182,501,376 bytes. This is a 30-second
stage, not sustained/hub qualification by itself; those stages are reported below.

The [indexed-hub candidate repeat](../../benchmarks/results/service/rowpolicy-hub-million.json)
also passes: one million vertices, degree-65,536 hub, 200,000 real durable updates
and 200,000 queries, eight checkpoints including bootstrap, exact recovery and
retry outcomes. It reaches 16,622.1/s; ack/query p99 upper bounds are 24.5/0.4 ms,
native allocation 79,233,888 bytes and peak RSS 283,328,512 bytes. Trace/matching
hashes match the earlier long hub stage. This short closed-loop repeat preserves
indexed-hub behavior, not an open-loop or sustained hub SLA.

The [new-binary 30-minute full-ring soak](../../benchmarks/results/independent/candidate-soak-sweep-million.json)
now passes under 128 MiB native and 64 MiB database/image caps, with 19,797,233
real durable updates at 10,998.3/s including drain, 17,996,758 exact versioned
queries and 603 checkpoints. Independent topology/proper-maximal matching and
recovery agree on its precise odd prefix: 1,999,999 edges and 499,999 matched
edges. Ack/offered-ack/query p99 upper bounds are 186.1/186.9/1.9 ms; maxima are
241.5/242.9/29.6 ms, with no one-second histogram overflow. Update producer
misses/IPC drops are 2,575/192; query misses/drops are 2,042/1,200; both have zero
Busy. Native allocation is 49,142,880 bytes; owner/producer peak RSS is
182,026,240/29,212,672 bytes. This passes the new-binary sustained degree-four
full-ring stage, not the failing degree-64 gate or unmeasured growth/drain/bursts.
The old hot soak remains old-binary evidence. No aggregate deployment quota,
network protocol, hardware power-loss or maximum-latency guarantee follows.

The [first growth/drain stage](../../benchmarks/results/independent/pulse-million.json)
subsequently completes 1,319,810 real updates at 10,996.6/s, 1,199,839 queries and
40 checkpoints with exact recovery, including a full million-update cycle.
Native allocation is 77,130,592 bytes under 128 MiB, but peak process RSS reaches
913,391,616 bytes. Thus scoped growth/drain throughput/correctness passes while
bounded total-memory qualification remains open. This is not evidence that the
native index policy caused the process residency spike; diagnose checkpoint,
SQLite and allocator contributions separately without transferring instrumented
profiling rates into throughput claims.
