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

`benchmarks/index.py` uses the public `Trial` class to compare fixed real traces
and partner checks without producer misses changing the workload. Constructor,
timed updates, native allocation, process RSS, checkpoint hash and exact matching
hash remain separate. The [installed comparison](../../benchmarks/results/independent/index-policy-fixed.json)
uses 18 sequential fresh processes: three baseline/candidate repetitions per
degree, 8,192 vertices and 200,000 real edits each. All checkpoint and matching
hashes agree. Degree-64 native allocation falls from 20,621,024 to 3,843,808 bytes
(81.4%), but median core rate falls from 2.862 million to 1.751 million updates/s
(38.8%). Degree-four median falls about 2.7%; degree-16 is approximately unchanged.
This is an explicit compute/memory tradeoff, not a throughput improvement. The
short nondurable traces do not establish durable service performance or tail SLAs.

Next repeat the rejected million-vertex stage under the
same native cap and the existing hub/durable release gates. Old degree-four soaks
must not silently become new-binary qualification.
