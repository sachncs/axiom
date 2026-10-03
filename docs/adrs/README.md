# Architecture decision records

These records explain the scalability/reliability work, including what is being
replaced, why, the guarantees retained, alternatives, and verification still
required. **Accepted design is not evidence of completed implementation.**
Dates use the project's user-facing calendar and are recorded per decision.

| Record | Decision | State |
| --- | --- | --- |
| [0001](0001-production-qualification.md) | Qualify 10k durable real updates/s at one million vertices | Target accepted; qualification pending |
| [0002](0002-native-storage.md) | Compact native storage instead of per-vertex Python sets | Implemented; storage-only evidence |
| [0003](0003-bounded-transactions.md) | Bounded undo instead of whole-state `deepcopy` | Matcher recursive `deepcopy` removed; durable paper integration and state-sized admission/certificates remain |
| [0004](0004-sparse-phase-indexes.md) | Sparse phase overlays instead of eager empty maps | Implemented and regression-tested; short-trace evidence only |
| [0005](0005-incremental-certificates.md) | Immediate incremental certificates, not disabled checks | Native production certificates implemented; paper hierarchy work pending |
| [0006](0006-native-production-matcher.md) | Native production matcher, retaining the paper engine | Native service implemented; permanent nondurable paper split superseded by 0023 |
| [0007](0007-durability-and-publication.md) | WAL, bounded group commit, coherent query versions and recovery | Durable owner and opt-in checkpoints implemented; full-service qualification pending |
| [0008](0008-resource-and-release-gates.md) | Single ownership, resource limits, independent qualification gates | Partially implemented; full-service gates pending |
| [0009](0009-sqlite-wal-durable-owner.md) | SQLite FULL-WAL commits with private native publication and bounded replay | Legacy v1 plus opt-in checkpoint v2; sustained qualification pending |
| [0010](0010-native-checkpoint-and-history-compaction.md) | Exact portable native images before atomic replay/dedup retirement | Codec/publication/retirement tested; short maintenance-inclusive evidence; sustained qualification pending |
| [0011](0011-bounded-service-admission.md) | Bounded client receipts and single-owner group aggregation/query scheduling | Sustained degree-four service stages and Linux hard-resource recovery pass; wider repeatability active |
| [0012](0012-committed-partner-reads.md) | Coupled published partner reads using bounded undo indexes, not whole-state copies | Threaded regression coverage; latency/resource qualification pending |
| [0013](0013-bounded-owner-backups.md) | Bounded self-contained SQLite snapshots with no-overwrite publication | Failure/crash and compact backup exact restore under hard resource caps pass; hardware power-loss deferred |
| [0014](0014-maintenance-admission.md) | Separate active/queued audit/checkpoint/backup work bound | Implemented; overload/RSS/disk qualification pending |
| [0015](0015-skew-and-offered-load-qualification.md) | Force hub repair and reconcile scheduled/rejected/missed/acknowledged load | Latest installed independently paced indexed-hub stage reaches 10,985/s; wider repeats active; older failing reports retained |
| [0016](0016-sparse-free-vertex-search.md) | Compact ordered free-vertex bitmaps accelerate nearly matched hub repair | Hub stage above 10k; broad qualification pending |
| [0017](0017-read-admission-reservation.md) | Reserve bounded read capacity without bypassing global admission | Measured zero query Busy under update saturation; full qualification pending |
| [0018](0018-checkpoint-history-validation-cost.md) | Inline strict retained-history predicates, not skip certificates | Tested/profiled; subsequent full-ring/growth/hub durable stages exceed 10k in the declared envelope |
| [0019](0019-independent-arrivals-and-bounded-ipc.md) | Separate producer GIL and bound transport/admission with explicit losses | Declared paced stages and Linux resource/recovery pass; current latency accepted; broader repeatability active |
| [0020](0020-resource-exhaustion-and-recovery.md) | Isolated hard address-space/filesystem exhaustion with exact recovery | Million-vertex growth/drain and compact backup recovery passed; deployment quotas pending; hardware power-loss deferred |
| [0021](0021-moderate-row-index-policy.md) | Bound moderate-row scans and retain indexed hubs | Fixed-trace memory/compute comparison and new-binary sustained degree-four stage pass; degree 64 fails throughput |
| [0022](0022-allocator-residency.md) | Distinguish freed allocator residency from live graph allocation | Explicit macOS launch policy measured through growth/drain; burst and Linux hard-resource stages pass separately; aggregate quotas deferred |
| [0023](0023-durable-paper-integration.md) | Bring basic/multilevel through the durable production service | Required active integration; not implemented or performance-qualified |
| [0024](0024-accounting-journal.md) | Bounded first-write paper accounting undo and explicit publication/rollback fail-stop | Accounting migrated in place; wider journal migration/durable paper integration remain active |
| [0025](0025-matching-view-journal.md) | Bounded matching-cell undo and retained edge/vertex/partner containers | Matching views migrated; global alias preflight, other snapshots and durable integration remain active |
| [0026](0026-color-class-journal.md) | Bounded class/seed membership undo and retained list/set aliases | Color classes migrated; shared-class admission, System/Hierarchy snapshots and durable integration remain active |
| [0027](0027-system-cache-deltas.md) | Shared endpoint-cache mutations and union-free point membership | Cache delta boundary implemented; System/Hierarchy journals and durable integration remain active |
| [0028](0028-system-undo-journal.md) | Bounded System-root, shared-row and matching-cut undo | System objects and touched rows migrated; Hierarchy/auxiliary snapshots and durable integration remain active |
| [0029](0029-hierarchy-root-journal.md) | Retain Hierarchy roots and journal deferred phase deletions | Hierarchy journal delivered; Matcher recursive copy subsequently removed; durable paper integration remains |
| [0030](0030-sparse-committed-partner-index.md) | Size committed-partner indexes to active batch touches, not graph universe | Sparse journal index implemented; 8.1% initial native-memory reduction in one-million-vertex diagnostic; durable repeats active |

The [engineering assessment](../engineering.md) remains the complete roadmap;
[current status](../status.md) distinguishes current retained evidence from each
record's chronological investigation notes. Native measurements do not qualify
the planned durable paper modes.
[storage contracts](../storage.md) describe the delivered container. Subsequent
changes must update the relevant record's implementation/evidence section rather
than silently changing an accepted contract or declaring an unfinished goal done.

## Migration inventory

| Previous cost/risk | Replacement and reason | Guarantee/limit and current status |
| --- | --- | --- |
| Per-vertex Python adjacency sets/objects | Native blocked adjacency and degree-sensitive indexes reduce object and allocation overhead (0002) | Shared native budget; Python reference storage remains available |
| Whole-state `deepcopy` before each edit | Shallow root references plus bounded owner journals for Matcher state (0003) | Exact tested rollback for enlisted state; some admission/certification work remains global; durable paper promotion remains |
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
| Treating native allocation bytes as whole-process memory | Live Python/allocator/VM measurements plus explicit operator launch policy (0022) | macOS large-cache spike reduced in scoped experiment; aggregate quotas and portable checkpoint allocation work remain separate |
| Dense committed-partner first-write slot per vertex | Inline plus budgeted sparse journal index sized to touched vertices (0030) | Same coupled publication read; 4 MB less initial native allocation at one million vertices in one fixed trace; high-water batch capacity is retained |

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
