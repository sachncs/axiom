# Current implementation and qualification status

Updated 2026-10-04. The product has exactly two matching methods: `basic`
(default) and `multilevel`. The former separate native matching Engine and its
API, checkpoints, tests, benchmarks, and compatibility path have been removed.
Historical ADRs and result artifacts remain for provenance only; they are not
current product behavior or qualification evidence for the paper methods.

| Path | Use | Durability and concurrency |
| --- | --- | --- |
| `Service` → `Durable` → `Matcher(mode="basic" or "multilevel")` | Local durable integration | Both modes use the same commit-before-ack path; bounded batch/replay tests pass; qualification remains active |
| `Packed` | Compact native graph storage | Stores adjacency only; it does not choose or implement a matching algorithm |
| `Matcher` alone | Direct Basic/Multilevel matching API | In-memory and caller-owned; updates are locally atomic, no persistence unless used through `Durable` |

The methods maintain proper maximal matching, not maximum matching. Durable
recovery replays the persisted operation stream through its recorded paper mode;
it does not restore or reinterpret the removed native matcher format. C++ is
limited to compact graph storage, while SQLite is the durable operation authority.
One-million-vertex Basic smoke qualification currently passes exact recovery,
but measured only about 506 real updates/s and about 1.54 GB process peak RSS.
That short run does not approach the 10k/s target or establish efficient
million-vertex memory use. A targeted Multilevel change replaced full
matching/seed scans on every update with a rollback-aware I3 crossing index.
On one 128k trace (128 durable updates, batch 32), measured throughput moved
from 49 to 3,057 updates/s. A one-million-vertex, batch-256 Multilevel smoke
measured 3,136 updates/s, 81 ms ack p99, and 1.80 GB peak RSS. A 4,096-update
single atomic group measured only 1,559 updates/s, 2.60 s ack p99, and 1.88 GB
peak RSS. These are single-run smoke measurements, not repeatable qualification;
the 10k/s target remains unmet and very large group latency is unacceptable.

`ProcUpdate` no longer scans all H-tilde edges to remove one source's outgoing
edges. A journaled sparse source index makes that cleanup proportional to the
source's own out-degree, with full rebuild audits and exact rollback retained.
A synthetic 100k-edge empty-source microprobe measured 4.27 ms for the old
whole-set filtering operation and 146 ns for indexed cleanup; this omits index
memory and is not an end-to-end performance claim. See
[ADR 0104](adrs/0104-source-indexed-tilde-edges.md).

Recursive Extend projection now indexes parent coloring assignments once by
color and queries the fan-type index for each disjoint group. The isolated
100k-assignment/10-group selection probe measured 2.69x faster selection with
about 852 KB of temporary traced Python allocation; whole Extend peak RSS and
connected adversarial performance remain unqualified. See
[ADR 0105](adrs/0105-index-extend-projection-by-color.md).

Multilevel's local hierarchy synchronization now avoids revalidating the whole
accumulated inserted-edge overlay before applying a single endpoint delta. The
fast path is explicit for Matcher-journaled state; direct calls and full rebuilds
still validate every excluded edge. This removes repeated O(|E_I|) validation,
with exact transaction rollback and boundary audits retained; no throughput gain
is claimed yet. See [ADR 0106](adrs/0106-trust-journaled-hierarchy-exclusions.md).

The Basic/Multilevel S-hat fallback now finds the same lowest-ID eligible
partner by traversing only the queried vertex's neighbors, avoiding a sorted
whole-S-hat snapshot. The change adds no persistent index or allocation; its
effect on dense/high-degree workload tails remains to be measured. See
[ADR 0107](adrs/0107-use-local-neighbors-for-s-hat-rematching.md).

Class-journal admission now separates retained roots from change volume in its
automatic ceiling: the limit covers every original class/seed membership, but
before-images remain write-set-only. This avoids a valid large coloring or
single delete failing solely at the former fixed 65,536-cell class cap. Other
paper component journals keep independent limits, so durable batch splitting
continues to address cumulative pressure there. See
[ADR 0108](adrs/0108-size-class-undo-to-retained-memberships.md).

Durable hot-hub churn now has repeatable intermediate-restart coverage in both
paper modes: every bounded prefix checks full graph/matching answers, the
complete paper Witness, verified history, maximality, and same-batch idempotent
retry against an independent run. This is correctness/recovery evidence at a
small deterministic scale, not skewed million-vertex performance qualification.

Deletion now visits only currently nonempty color classes instead of probing
every configured color slot. The sparse index is included in Witness state,
updated at partition/subphase boundaries, journaled on last-member removal, and
audited at root replacement; direct seed removal also maintains it. The
structural regression proves empty slots are skipped and rollback restores the
index. Dense active-color counts and remaining O(number-of-class-roots) journal
admission are not yet qualified. See
[ADR 0109](adrs/0109-index-nonempty-color-classes.md).

## Historical evidence from the removed native matcher

The following rates and resource drills were recorded against the former native
matching Engine. Keep the reports and provenance, but do not use them to claim
performance or production qualification for Basic or Multilevel.

| Stage | Delivered rate | Verification |
| --- | --- | --- |
| 30-minute million-vertex degree-four full-ring | 10,998/s | 19.8m real changes, 18m coherent queries, 603 checkpoints, exact recovery |
| 10-minute million-vertex growth/drain | 10,998/s | Six full cycles, 201 checkpoints, exact recovery; explicit macOS allocator profile |
| Three-minute million-vertex hub degree 65,536 | 10,985/s | 62 checkpoints, exact versioned queries and recovery; initial average degree 4.131064 |
| Three-minute burst windows, 44k active offers/s | 10,611/s | Bounded rejection, every loss accounted, exact recovery; not admission of every offer |
| Three-minute burst plus degree-65,536 hub | 10,431/s | 59 checkpoints, exact query/recovery; 56,554 rejections and 12 offered-ack tails beyond 1s retained |
| Linux changing-density hard-resource drill | Not a rate test | 1.04m real changes, actual memory/disk exhaustion, compact backup restore under unchanged caps |

The paper-coloring route now applies Vizing activation and fan-prefix rotation
with touched-edge index updates and local certificates, retaining full coloring
and fan audits at operation boundaries. Injected certificate failure restores
the exact prior partial-coloring maps. Deterministic profiling shows fewer
whole-state calls, but the 8,192-vertex degree-four hierarchy probe still takes
about 25 seconds; this does not establish production throughput or billion-node
support. Broader repeatability and remaining snapshot migration are active. See
[ADR 0059](adrs/0059-local-paper-coloring-transactions.md).

Whole-collection fan replacement in Sparsify-Types and Extend now swaps index
roots instead of sorting and discarding a full fan snapshot. Nested rollback
restores the exact original fan contents and index identities. This is a
component optimization, not an end-to-end paper-engine rate claim; see
[ADR 0101](adrs/0101-constant-time-paper-fan-clear.md).

A-level rematching now checks basic and hierarchical partition membership directly
instead of constructing a Python set copy or union for each repair. The isolated
500k-member probe fell from 35.2 MB/0.162 s for one set copy to 1.1 KB/0.021 s
for 100k direct membership checks. End-to-end paper update qualification remains
open; see [ADR 0060](adrs/0060-avoid-rematch-partition-copies.md).

Paper coloring now stores incidence sets only for endpoints with colored edges;
isolated vertices no longer allocate empty color sets during construction,
reindex, or full validation. The million-vertex/two-edge projection probe fell
from 878.3 MB to 224.5 MB peak traced allocation. The remaining footprint is
primarily the copied reference `Adjacency` vertex rows, so this is substantial
but incomplete storage work. See [ADR 0061](adrs/0061-sparse-paper-color-incidence.md)
and the [raw measurement](../benchmarks/results/paper/sparse-color-incidence.json).

Recursive color-group projections now create their isolated graph in `Packed`
storage when the caller uses reference `Adjacency`; existing `Packed` budgets
are preserved. On the same one-million-vertex/two-edge probe, projection
allocation fell from 224.5 MB Python traced to about 13.01 MB combined Python and
native allocation. This remains an isolated diagnostic; extension-level resource
qualification is open. See [ADR 0062](adrs/0062-compact-paper-projection-graphs.md)
and the [raw comparison](../benchmarks/results/paper/packed-projection.json).

Hierarchy refinement no longer builds a full live-edge set or a second full edge
set solely for inherited-System matching cuts. It checks selected-edge liveness
against the phase graph and restricts each System matching by graph membership;
the owner journal retains exact undo and rejects capacity failure before cuts.
One `working_edges` set and the isolated working graph still remain. See
[ADR 0063](adrs/0063-graph-backed-hierarchy-cuts.md).
For built-in graphs, the remaining working-edge set is now streamed directly into
the isolated Packed projection; inserted edges are merged in sorted order, and
unordered custom Graph implementations keep the deterministic materializing
fallback. One 100k-vertex/200k-edge projection reduced traced Python scratch from
36.4 MB to 448 bytes at equal native output size. Full refinement RSS remains
unqualified. See [ADR 0064](adrs/0064-stream-hierarchy-projections.md) and the
[raw result](../benchmarks/results/paper/stream-projection.json).

At child-to-parent hierarchy boundaries, reuse the already synchronized
detached graph as the next phase base instead of taking a second equivalent
O(n + m) snapshot. Failure-injection coverage checks graph/system root identity,
exact topology and matching restoration. This is a scoped snapshot reduction;
full refinement resource qualification remains open. See
[ADR 0102](adrs/0102-reuse-parent-boundary-graph.md).

Refinement also no longer materializes `previous.A | previous.B`: the initial
partition pass queries the inherited roots directly, and later promotion checks
use the already-built A/B destination partitions plus inherited A. On one
million-label/two-partition membership probe, direct checks avoided an 87.2 MB
union but were about 3.1× slower than union-plus-query in a one-million-check
microbenchmark. This is an explicit memory/compute tradeoff, not a speedup. A
targeted dense hierarchy regression rejects any `Vertices` union during
refinement while retaining the full hierarchy certificate. End-to-end refinement
qualification remains open. A 2,048-vertex full-refinement comparison across the
streaming and union changes kept identical state digests, reduced traced peak by
22%, and had time within sample resolution. This does not isolate union removal
or qualify million-scale behavior. See [ADR 0065](adrs/0065-avoid-saturated-partition-union.md) and the
[raw record](../benchmarks/results/paper/saturated-union-membership.json).

[Raw full-ring](../benchmarks/results/independent/candidate-soak-sweep-million.json),
[growth/drain](../benchmarks/results/independent/pulse-long-million.json),
[hub](../benchmarks/results/independent/hub-steady-million.json),
[burst](../benchmarks/results/independent/burst-million.json),
[burst hub](../benchmarks/results/independent/hub-burst-million.json),
[Linux recovery](../benchmarks/results/resource-growth-envelope.json).
These use declared source/wheel/runner hashes and machine/storage stacks. Producer
misses, IPC drops and Busy rejections do not count as real acknowledged changes.
Native byte caps do not bound total RSS/page cache or all filesystem companions.
Default macOS growth/drain reached 913 MB RSS; the explicitly selected allocator
profile reduced measured peaks to about 208 MB. It is not a portable quota.
Degree-64 throughput measured 6,640/s and fails the target for that denser envelope.

## Completed in this change set

- Basic and Multilevel both run through `Durable` and thread-safe `Service`;
  Basic is the default. Native matching-engine sources, package entry points,
  native checkpoint compatibility, and associated tests have been removed.
- A caller's Durable batch is one SQLite commit. Its paper updates use bounded
  private Matcher journal slices, with automatic smaller-slice replay on
  journal-capacity pressure; a failure before persistence restores the exact
  prior paper state. Both modes have failure-injection, exact-state,
  batch-partition, restart, retry, and backup coverage.
- The published million-vertex Basic smoke trace with 256-operation groups
  passed exact graph/matching recovery. It delivered about 506 acknowledged real
  updates/s, used about 1.54 GB process peak RSS, and had about 509 ms ack p99.
  This is a short local smoke test, far below 10k/s and not a performance or
  resource qualification.
- Multilevel maintains a journaled I3 crossing-edge index and removes dropped
  seed edges immediately, eliminating full matching scans from ordinary update
  work. Full I3 validation remains at rebuild boundaries. This is a scoped
  optimization, not qualification; see [ADR 0103](adrs/0103-incremental-multilevel-i3-index.md).
- Auxiliary H-tilde cleanup uses a rollback-aware source index instead of a
  global directed-edge scan; memory and broad skew/performance measurements
  remain open (ADR 0104).
- Recursive Extend uses one temporary sparse assignment-by-color index and
  indexed fan types to avoid repeating parent scans; the O(m) temporary index
  is included in the remaining peak-memory qualification (ADR 0105).
- Incremental hierarchy sync trusts only the journal-owned E_I set and validates
  its changed-edge delta; direct and full rebuild calls keep exhaustive checks
  (ADR 0106).
- Rematching fallback selects the exact same minimum S-hat neighbor from local
  adjacency rather than sorting/scanning all S-hat (ADR 0107).

## Still active

- Migrate the remaining graph-sized paper snapshots/allocations and global
  hierarchy work; current operation-log recovery is linear in retained history
  and has no compact paper-state checkpoint.
- Repeat throughput, memory, recovery-time, skew, adversarial and boundary
  qualification independently for both modes at the million-vertex target.
- Finish installed-artifact and service/deployment qualification, including
  enforced process/filesystem resource ceilings and full overload behavior.
- Remove stale references from remaining historical/product documentation and
  keep every claimed result tied to the implementation and exact test run.

## Deferred by explicit user direction

Physical power-loss qualification on disposable hardware and billion-vertex
qualification are future engineering. Their deferral is not evidence of device
durability under arbitrary power loss or billion-node feasibility.

Paper migration prerequisite: a bounded full-state comparison oracle now covers
both modes/storage backends, replay prefixes, post-rebuild rollback and fan
failure indexes. [State inventory](paper-state.md) records what is and is not
compared. This is not a durable codec or a completed journal migration.
Recent hierarchy work keeps these checks enabled while reducing redundant
state: child rebuilds reuse immutable parent graph/partition roots when safe,
defer cache indexing until refinement, borrow read-only update sets, and retain
a restore fallback for missing deleted edges. Phase synchronization streams
built-in graph edges and cuts matchings against the resulting graph; the P2
certificate now examines incident edges instead of rescanning the full matching
per A vertex. Recent work also uses sparse degree counts in hierarchy checks,
counts seed palette frequencies in one edge pass, and discovers Euler
components from live endpoints rather than scanning/materializing isolated
vertices, and now limits those degree certificates to active components
([ADRs 0090–0093](adrs/README.md)). These remain component-level changes;
an adaptive sparse maximum-degree path also avoids universe scans in Paper.color
and recursive seeding ([ADR 0094](adrs/0094-adaptive-paper-maximum-degree.md));
the standalone System.switch snapshot/recount path now uses local deltas and
failure rollback ([ADR 0095](adrs/0095-path-local-switch-undo.md)); sparse
refinement matching degrees avoid allocating n zero counters while preserving
the packed dense branch ([ADR 0096](adrs/0096-sparse-refinement-degrees.md));
refinement cycle detection uses a strict U-decrease guard instead of copying
U/A/M per pass ([ADR 0097](adrs/0097-monotone-refinement-progress.md)).
Full-suite verification currently passes 1,122 tests and one optional plotting
test is skipped because matplotlib is unavailable. The
component measurements are recorded in [ADRs 0066–0071](adrs/README.md); they
do not qualify durable paper modes or complete rebuild RSS.
Accounting is now migrated to bounded scalar undo with retained Ledger identity;
failed absent-edge deletions restore exact counters. Uncertain publication cleanup
or rollback fail-stops the Matcher rather than exposing uncertified query state.
[ADR 0024](adrs/0024-accounting-journal.md) records this partial migration.
Matching views now also use bounded first-write cells and retain external
container identity on failure, including failed rebuild candidates. Their full
copies are removed. GIL-enabled CPython skips global alias admission only when
reference counts prove the views unique; shared views and other runtimes retain
the walk. Other snapshots/certificates still cost global work.
[ADR 0025](adrs/0025-matching-view-journal.md) defines the boundary.
Color classes and seed removals are journaled too, retaining original
list/set identities and restoring seed/class aliases after failed subphase or
phase reconstruction. Class admission uses a GIL-enabled CPython uniqueness proof
when possible; aliases/other runtimes retain a global walk. System, Hierarchy
and auxiliary snapshots remain. [ADR 0026](adrs/0026-color-class-journal.md)
records the component-level undo design; it is not a performance qualification.
Basic/multilevel now share System endpoint-cache deltas and avoid temporary
partition unions for point membership. [ADR 0027](adrs/0027-system-cache-deltas.md)
defines the new mutation boundary; it is not yet System/Hierarchy undo.
System roots, touched endpoint rows and old matching-set cuts now use bounded
first-write undo with retained root identity. Shared hierarchy rows use one undo
record. Recursive Matcher copying has since been removed. [ADR 0028](adrs/0028-system-undo-journal.md)
records the System boundary; remaining snapshot migration and full mode
qualification remain active.

## Deferred by explicit user direction

Deployment aggregate quotas/monitoring/supervision/transport integration, tighter
latency/background maintenance, physical hardware power-loss qualification and
larger-scale/billion-vertex qualification are future engineering for this version.
The existing local hard-resource, crash, rollback and recovery checks remain in
scope. Deferral creates no guarantee: this is not turnkey network infrastructure,
hardware power-loss proof, arbitrary graph partitioning or billion-scale support.

Use [service](service.md), [durability](durable.md), [storage](storage.md),
[operations](operations.md), [engineering](engineering.md) and [ADRs](adrs/README.md)
for the retained contracts and migration rationale. Current local validation is
1,122 passing tests and one optional plotting skip; mypy and Ruff pass. CI and
benchmark results must be attributed to their exact revision, not assumed to
qualify every subsequent change.
