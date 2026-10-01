# Architecture decision records

These records explain the scalability/reliability work, including what is being
replaced, why, the guarantees retained, alternatives, and verification still
required. **Accepted design is not evidence of completed implementation.**
Dates use the project's user-facing calendar (1 October 2026).

| Record | Decision | State |
| --- | --- | --- |
| [0001](0001-production-qualification.md) | Qualify 10k durable real updates/s at one million vertices | Target accepted; qualification pending |
| [0002](0002-native-storage.md) | Compact native storage instead of per-vertex Python sets | Implemented; storage-only evidence |
| [0003](0003-bounded-transactions.md) | Bounded undo instead of whole-state `deepcopy` | Native graph/partner journals and separate durability implemented; paper snapshot migration pending |
| [0004](0004-sparse-phase-indexes.md) | Sparse phase overlays instead of eager empty maps | Implemented and regression-tested; short-trace evidence only |
| [0005](0005-incremental-certificates.md) | Immediate incremental certificates, not disabled checks | Native production certificates implemented; paper hierarchy work pending |
| [0006](0006-native-production-matcher.md) | Separate native production matcher, retaining the paper engine | Native core plus first durable layer implemented; full service qualification pending |
| [0007](0007-durability-and-publication.md) | WAL, bounded group commit, coherent query versions and recovery | Durable owner and opt-in checkpoints implemented; full-service qualification pending |
| [0008](0008-resource-and-release-gates.md) | Single ownership, resource limits, independent qualification gates | Partially implemented; full-service gates pending |
| [0009](0009-sqlite-wal-durable-owner.md) | SQLite FULL-WAL commits with private native publication and bounded replay | Legacy v1 plus opt-in checkpoint v2; sustained qualification pending |
| [0010](0010-native-checkpoint-and-history-compaction.md) | Exact portable native images before atomic replay/dedup retirement | Codec/publication/retirement tested; short maintenance-inclusive evidence; sustained qualification pending |
| [0011](0011-bounded-service-admission.md) | Bounded client receipts and single-owner group aggregation/query scheduling | Local service tested; short concurrent evidence; sustained/latency/resource qualification pending |
| [0012](0012-committed-partner-reads.md) | Coupled published partner reads using bounded undo indexes, not whole-state copies | Threaded regression coverage; latency/resource qualification pending |
| [0013](0013-bounded-owner-backups.md) | Bounded self-contained SQLite snapshots with no-overwrite publication | Failure/crash/exact-restore tests; device-loss qualification pending |
| [0014](0014-maintenance-admission.md) | Separate active/queued audit/checkpoint/backup work bound | Implemented; overload/RSS/disk qualification pending |
| [0015](0015-skew-and-offered-load-qualification.md) | Force hub repair and reconcile scheduled/rejected/missed/acknowledged load | Benchmarks tested; million hub throughput below target |

The [engineering assessment](../engineering.md) remains the complete roadmap;
[storage contracts](../storage.md) describe the delivered container. Subsequent
changes must update the relevant record's implementation/evidence section rather
than silently changing an accepted contract or declaring an unfinished goal done.

## Migration inventory

| Previous cost/risk | Replacement and reason | Guarantee/limit and current status |
| --- | --- | --- |
| Per-vertex Python adjacency sets/objects | Native blocked adjacency and degree-sensitive indexes reduce object and allocation overhead (0002) | Shared native budget; Python reference storage remains available |
| Whole-state `deepcopy` before each edit | Reserve-before-mutation graph/partner undo journals make ordinary production edits local (0003) | Exact logical rollback, allocation-free native undo, fail-stop on certificate/undo corruption; Python paper snapshots remain |
| Eager empty phase dictionaries/sets | Sparse live-endpoint overlays avoid allocating empty vertex buckets (0004) | Phase counters/lifecycle unchanged; regression-tested |
| Global scans on every ordinary production edit | Local dependency certificates plus separate independent full audits (0005) | Immediate proper/maximal matching checks are retained, not disabled; paper hierarchy scans still present |
| Paper coloring/fans/hierarchy on the production path | Explicit `axiom.engine.Engine`, with deterministic incremental maximal matching (0006) | Research engine retained; different matching choices and no transferred paper theorem; hub deletion remains degree-dependent |
| Treating an in-memory commit as success after a crash | FULL-WAL barrier, then coherent publication/acknowledgment (0007/0009) | Replay/dedup/process recovery implemented; native `commit` alone remains nondurable; sustained qualification pending |
| Lifetime operation-log growth and replay from genesis | Exact checkpoints plus atomic history/retry retirement (0010) bound replay and table rows | Opt-in v2 implemented; expired IDs reject, v1 remains capped; physical disk/RSS and maintenance latency still need qualification |
| Rebuilding a different valid matching after restart | Persist exact compact partner state and audit a separate candidate (0010) | Exact partners/version preserved; invalid images refuse recovery, never silently repaired |
| Per-row temporary hash-node allocation in full native audits | Reuse one compact row vector and sort for duplicate detection (0010) | Full certificates retained; scratch and worst-case degree-dependent work still count |
| Preassembled batches or unbounded executor queues | Bounded individual admission, pending-ID fan-out and short assembly deadlines (0011) | Active/queued/query/duplicate work shares one cap; timeout is not cancellation, no owner callbacks; maintenance still blocks queries |
| Partner queries queued behind durability barriers | First-write undo indexes expose only the last publication (0012), adding 4 bytes/vertex | Coupled version/partner reads support concurrent clients on GIL-enabled CPython; other reads remain owner-queued; audits/native CPU work can still delay calls |
| Copying a live SQLite main file or exporting only edges | Owner snapshot captures committed WAL state, partners and retry retirement (0013) | Bounded image, no-overwrite publication, independent restore required; not replication or power-loss proof |
| Unbounded growth or claiming capacity from a short microbenchmark | Native budget, bounded pages, single ownership and full-service release gates (0008) | Native limits implemented; queue/RSS/disk limits and sustained durable qualification remain pending |

## What is not being abandoned

- Proper **maximal**, not necessarily maximum-cardinality, matching.
- Deterministic behavior under the specified backend and update order.
- All-or-nothing accepted updates and coherent committed graph/matching queries.
- Explicit rejection, rollback/fail-stop behavior, and independent verification.
- The existing research engine, including its coloring/fan/hierarchy regression
  requirements and the reference snapshot path until replacements are certified.

The changes remove implementation overhead and introduce an explicitly different
production algorithm. They do not silently weaken the paper engine or claim its
theoretical bounds for the new backend.
