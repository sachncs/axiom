# Current implementation and qualification status

Updated 2026-10-04. This page describes current components; historical experiment
sections retain their source/workload provenance and do not override this status.

| Path | Use | Durability and concurrency |
| --- | --- | --- |
| `Service` → `Durable` → native `Engine` | Local production engineering | FULL-WAL commit before acknowledgment; thread-safe clients, one mutation owner |
| Native `Engine` alone | In-memory deterministic maximal matching | Owner-bound, bounded rollback; no persistence on its own |
| `Matcher(mode="basic" or "multilevel")` | Paper/research implementation | Nondurable, externally serialized; recursive `deepcopy` removed, mutation journals active |

All paths maintain proper maximal matching, not maximum matching. The production
algorithm is explicitly different from the paper/coloring/hierarchy machinery;
no paper asymptotic theorem is transferred. C++ holds compact compute state;
SQLite checkpoint plus committed tail is the complete durable authority.

## Completed scoped evidence

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
support. Broader repeatability, snapshot migration, and durable integration
remain active. See [ADR 0059](adrs/0059-local-paper-coloring-transactions.md).

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

## Active scope

1. Paper qualification now includes a deterministic 360-update hot-hub churn
   trace replayed twice with full Witness equality after every operation plus
   matching/index/hierarchy certificates. Broader repeated skew/arrival
   qualification on fresh installed-wheel runs,
   with exact-prefix queries, independent recovery and all losses retained.
   A new seeded power-law offered-load profile now has four one-million-vertex,
   ten-second source-checkout samples: 10k offers/s delivered 9,538–9,549 real
   updates/s (miss); 12k offers/s delivered 11,146–11,151/s. All four recovered
   and certified exactly, but they are not installed-wheel, sustained or
   historical-query replay qualification. See [raw results](../benchmarks/results/overload/power-law-million.json).
   One 60-second 12k-offer probe completed 11,348 real updates/s while serving
   59,451 queries, with exact recovery. The colocated producer missed 5.4% of
   scheduled update slots; ack p99 was 181.4 ms. This is not an independent
   producer or installed-wheel soak. See [60-second summary](../benchmarks/results/overload/power-law-million-60s.json).
2. Continue paper-engine adversarial qualification and finish integrating
   coloring/fan/hierarchy operations into the durable production service.
   Endpoint-local hierarchy, maximality, auxiliary-index and System-row
   certificates have bounded diagnostic evidence; remaining global
   snapshots/admission work and durable integration are unfinished. Recursive Matcher
   `deepcopy` has been removed; do not confuse this with durable paper integration
   or full billion-vertex support.
   Integrate basic/multilevel through the durable production service with explicit
   algorithm selection and persisted identity. The user requires this on 2026-10-03;
   it is no longer a permanent nondurable research-only destination. Current
   persistence remains native-only until exact rollback/recovery tests pass.
3. Keep website, README, changelog, API guidance and decision records consistent
   with current implementation and measured boundaries.

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
Full-suite verification currently passes 1,314 tests. The
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
Color classes and seed removals are now journaled too, retaining original
list/set identities and restoring seed/class aliases after failed subphase or
phase reconstruction. Class admission uses a GIL-enabled CPython uniqueness proof
when possible; aliases/other runtimes retain a global walk. System, Hierarchy
and auxiliary snapshots remain. [ADR 0026](adrs/0026-color-class-journal.md)
records this partial migration, not durable paper integration.
Basic/multilevel now share System endpoint-cache deltas and avoid temporary
partition unions for point membership. [ADR 0027](adrs/0027-system-cache-deltas.md)
defines the new mutation boundary; it is not yet System/Hierarchy undo.
System roots, touched endpoint rows and old matching-set cuts now use bounded
first-write undo with retained root identity. Shared hierarchy rows use one undo
record. Recursive Matcher copying has since been removed; typed durable recovery
remains. [ADR 0028](adrs/0028-system-undo-journal.md) records the System boundary.

## Deferred by explicit user direction

Deployment aggregate quotas/monitoring/supervision/transport integration, tighter
latency/background maintenance, physical hardware power-loss qualification and
larger-scale/billion-vertex qualification are future engineering for this version.
The existing local hard-resource, crash, rollback and recovery checks remain in
scope. Deferral creates no guarantee: this is not turnkey network infrastructure,
hardware power-loss proof, arbitrary graph partitioning or billion-scale support.

Use [service](service.md), [durability](durable.md), [storage](storage.md),
[operations](operations.md), [engineering](engineering.md) and [ADRs](adrs/README.md)
for the retained contracts and migration rationale. Current local coverage is
1,314 passing tests; CI and benchmark results must be attributed to their exact
revision, not assumed to qualify every subsequent change.
