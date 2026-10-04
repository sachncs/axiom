# Scalability and reliability: engineering assessment

This document retains the project's engineering history and qualification
evidence. **Current product boundary (2026-10-04): only paper-derived `basic` and
`multilevel` matching are supported; `basic` is the default. The former native
matching Engine has been removed.** `Packed` remains compact graph storage only.
Historical native-engine results in this document are not evidence for either
current matching mode.

The accepted performance target is **10,000 real edge updates/s at 1,000,000
vertices and average degree 4**, including durable acknowledgments and coherent
matching queries. Earlier native-engine rates were measured on a different
algorithm and do not qualify Basic or Multilevel. The paper-backed durable path
requires its own repeatable qualification. See the rationale, contracts,
alternatives, and current implementation status in [architecture decision
records](adrs/README.md).

## Current roadmap status

Current implementation (2026-10-04): **Basic and Multilevel are the only
supported matching modes; Basic is the default.** Both are available through
SQLite-backed `Durable` and the thread-safe local `Service`, including atomic
batch updates and bounded version-coherent read snapshots. The native matcher,
native checkpoint path, and compatibility reader have been removed. `Packed`
is graph storage, not a matcher. See [ADR
0023](adrs/0023-durable-paper-integration.md) and the complete
[product roadmap](product-roadmap.md).

**Active engineering:** remove remaining state-sized paper-engine allocations
and global work; qualify Basic and Multilevel independently for repeatability,
skew, adversarial updates, sustained performance, recovery cost, and service
resource limits. Durable recovery currently replays operation history; there
is no paper-state decoder/checkpoint. Typed immutable external IDs now have a
SQLite mapping and Service API within the fixed vertex universe; dynamic vertex
lifecycle remains unimplemented. **Deferred:** physical hardware power-loss
qualification is deferred for this version. Network transport and
billion-vertex support are not implemented or claimed.

Historical native-engine rates and deployment measurements preserved below are
provenance only, not qualification of current paper modes. Any older statement
in this engineering archive that native matching/checkpoints are implemented,
that paper modes are nondurable, or that their durable integration remains open
describes a superseded state. The authoritative current status is the summary
above and the product roadmap.

| Workstream | Delivered | Remaining evidence or engineering |
| --- | --- | --- |
| Compact storage and local transactions | 24-byte derived-occupancy blocks, sparse committed-partner journal index, bounded undo and local certificates | Wider degree/churn performance repeats and deployment sizing |
| Durable authority and recovery | SQLite FULL-WAL operation history, bounded admission/retries, and fail-stop recovery for both paper modes | Replay-at-scale/recovery objectives and deployment qualification; hardware power-loss is deferred |
| Concurrent clients and overload | Single-owner paper-backed Service, locked admission/publication, bounded receipts, and coherent reads | Broader sustained burst/skew/resource qualification and transport integration if required |
| Million-vertex 10k durable updates/s | **Not qualified for Basic or Multilevel.** Preserved 10.97k/11.00k/s hot/full-ring figures are historical native-matcher results only. The pre-optimization hosted Basic run acknowledged 200,192 of 1,040,000 planned changes in 240.985 s (~831/s including Service initialization), then timed out before audit/backup. A 10k-vertex degree-four Durable microbenchmark improved 46% Basic / 27% Multilevel at private slice 256; this is directional only. A second identified cost is global `U`/maximality work at unchanged Basic subphases; ADR 0137 skips that work only when M1 is provably unchanged. | Validate both changes under the constrained million-vertex run, including high-degree capacity fallback, both modes, exact rollback/replay, durable acknowledgments, coherent queries, and full resource accounting |
| Resource failure and backups | Historical native-path Linux growth/drain, exhaustion, and backup evidence is preserved; it does not qualify paper-backed Service. ADRs 0127–0133 reduce admission, build, replay, audit, and matching-index memory. ADR 0143 replaces the second vertex-indexed `Packed` matching index after its Multilevel startup raised `MemoryError` under the hosted 512 MiB gate; a local 500k-edge component probe accounts for 32,777,428 bytes in sparse keys, not whole-process RSS. Latest hosted run `e4824c9` (37199582633) is **not qualified**: Basic acknowledged 1,000,000 updates in 111.755 s (~8.9k/s, updates only), and passed backup plus exact memory-pressure recovery, but disk-pressure recovery failed while allocating a rebuilt `lambda_lists` array; Multilevel startup failed while copying `matcher.graph` into the initial `phase_base_graph`. | Remove/bound the initial Multilevel phase-base graph copy; make Basic recovery fit the unchanged process limit during disk pressure; then run both modes with concurrent durable partner queries and pass every backup, disk, and memory gate. Characterize process/page-cache use, quotas, and alerting |
| Latency | Existing latency acceptance is a version-level product decision, not paper-mode performance qualification | Measure repeatable paper-mode update/query tails; tighter SLA and background maintenance are deferred by user |
| Paper engine | Focused coloring/fan rollback, sparse coloring incidence, bounded journals, local refinement/pruning optimizations, and the sparse packed-integer matching-edge index (ADR 0143) have regression coverage | Broad repeatability/adversarial/resource qualification remains open; full Basic/Multilevel 512 MiB and mixed-query qualification is pending; remaining global repairs/snapshots are open; durable integration is implemented, not a remaining gate |
| Paper undo migration | Matcher recursive `deepcopy` removed; local journals and sparse/indexed paths cover multiple graph, coloring, fan, and hierarchy mutations; child rebuilds avoid cloning the parent graph for missing deletion history | Sparse A/B remain Python sets; opaque custom graphs retain materializing fallbacks; full parent-boundary rebases, multi-source A/N/R construction, other fan/pruning snapshots, some admission/certificate work and phase-boundary audits remain state-sized |
| Billion vertices | Storage arithmetic and architectural constraints documented | 10m/100m/1b qualification and any cross-partition algorithm; no support claim |

Hierarchy refinement's `ProcProcess` witness lookup no longer scans every
selected matching edge for each B-neighbor; it checks the candidate vertex's
incident edges against the existing selected-edge set, without retaining a
second matching index. A deterministic two-swap regression passes the full
hierarchy certificate and confirms the source graph is unchanged. Three traced
repeats over a disjoint-copy witness-heavy fixture show 1.6–7.1% lower median
refinement time at 512–4,096 vertices with identical hierarchy state and no
material allocation change. This is component-level, single-host evidence,
not broader paper-engine qualification. See [ADR 0066](adrs/0066-local-refinement-witness-search.md)
and its [raw record](../benchmarks/results/paper/refinement-witness-search.json).

Child multilevel rebuilds now use the detached working System's A/B/U roots
directly instead of materializing a second set of hierarchy roots. When all
deleted edges are in the immutable parent graph, refinement now reads that
root directly rather than cloning it; missing-edge recovery retains the
previous snapshot-and-restore fallback. Cache indexing is deferred until
refinement rebuilds rows for its output graph. An isolated one-million-label
partition probe reduced the duplicate-root traced peak from 65.5 MB to 80
bytes. This is not a complete rebuild or RSS result; the detached System and
projection allocations remain.
See [ADR 0067](adrs/0067-reuse-child-refinement-partition-roots.md) and its
[raw probe](../benchmarks/results/paper/child-refinement-roots.json).

The recursive rebuild loop now passes read-only insertion and deferred-delete
sets by reference instead of cloning them at each level; the one combined
deletion set is built with a direct union rather than cloning both inputs
first. Refinement regression coverage proves caller-owned edge sets are
unchanged. An isolated 180,000-edge union reduced traced peak from 21.0 MB to
12.6 MB with the same result. See [ADR 0068](adrs/0068-share-refinement-update-sets.md)
and its [raw probe](../benchmarks/results/paper/refinement-update-sets.json).

Multilevel full rebuilds also skip indexing the detached level-one System when
recursive refinement will immediately rebuild its cache rows on the projected
graph. One-level schedules retain eager indexing and their full certificate.
On a 50k-vertex/50k-edge `Packed` ring, the isolated copy stage fell from
94.7 ms to 0.55 ms; this shifts required indexing to refinement and is not an
end-to-end rebuild speed claim. See [ADR 0069](adrs/0069-defer-full-rebuild-cache-index.md)
and the [raw comparison](../benchmarks/results/paper/deferred-rebuild-index.json).

Hierarchy phase synchronization now streams built-in graph edges, merges
deferred edges deterministically, and passes the phase graph directly to
matching restriction rather than retaining a Python set of every phase edge.
A 50k-edge Packed cycle probe showed a 57.6% lower traced peak and 34.5% lower
sync time with identical state; custom graph fallback remains. The independent
hierarchy checker also no longer scans the full matching once per A vertex:
its P2 certificate checks only incident graph edges. A valid 50k-vertex
certificate completed in 142 ms; the prior nested scan exceeded a 90-second
diagnostic and was stopped. These are focused component measurements, not
whole-rebuild qualification. See [ADR 0070](adrs/0070-stream-hierarchy-phase-sync.md),
[ADR 0071](adrs/0071-localize-hierarchy-p2-audit.md), and the linked raw records.

The same local-adjacency principle now covers hierarchy refinement's B
classification, U promotion, and B-witness repair; the repair no longer copies
the full selected matching to a tuple. The now-unused full-set neighbor helper
was removed. Three uninstrumented runs over 256 disjoint two-swap witness
components (2,048 vertices) measured median refinement time of 0.413 s before
and 0.172 s after, with each result passing the complete hierarchy certificate.
This is component-level evidence only; allocation/RSS and broader graph-shape
repeats remain open. See [ADR 0072](adrs/0072-localize-refinement-matching-scans.md)
and its [raw record](../benchmarks/results/paper/refinement-local-matching.json).

The final refinement boundary normalization also used to scan every chosen
matching edge for each A/B vertex. Since every chosen edge belongs to the
working phase graph, the same test now checks only incident graph neighbors;
it retains the original A-to-B pass followed by B-to-A repair and only
materializes vertices that actually move. On five alternating runs of the same
2,048-vertex/4,096-edge fixture, canonical hierarchy state remained identical
and median traced refinement time fell from 395.95 ms to 257.50 ms (34.97%).
Peak traced allocation was unchanged within the median sample. This removes a
partition-times-matching scan on this measured shape but remains component
evidence, not broad or durable qualification. See
[ADR 0088](adrs/0088-localize-refinement-boundary-normalization.md) and its
[raw record](../benchmarks/results/paper/refinement-boundary-normalization.json).

The exact hierarchy cycle key now also omits `new_b`. At every point in this
refinement, `new_a`, `new_b`, and `new_u` are disjoint and partition the fixed
universe `previous.B ∪ old_u`; therefore U and A uniquely determine B. The
cycle check remains exact, with no probabilistic digest. On the same five-run
2,048-vertex fixture, canonical state remained identical and median peak traced
allocation fell from 1,654,111 to 1,621,095 bytes (2.00%); median time was
0.25873 s before and 0.25688 s after. This is a further storage reduction on
one disconnected fixture, not broad qualification. See
[ADR 0089](adrs/0089-derive-refinement-b-partition.md) and its
[raw comparison](../benchmarks/results/paper/refinement-b-partition.json).

Fan batch ownership validation now checks the existing `Fans.members` set rather
than rebuilding a set of every fan for every batch entry. The duplicate-fan
check likewise no longer allocates a temporary singleton set. A deterministic
400-fan Modify-Types batch measured median operation time of 45.95 ms before and
9.95 ms after (4.62×); the regression test bounds collection iteration count
while verifying the resulting fans and coloring. This is batch-level evidence,
not an end-to-end coloring or memory result. Whole-state fan/color rollback
snapshots and remaining fan-repair scans still need migration and qualification.
See [ADR 0073](adrs/0073-indexed-fan-membership-checks.md) and its
[raw record](../benchmarks/results/paper/fan-batch-membership.json).

`Spectrum.modify` now journals only alternating-path coloring cells and fans at
the selected fan vertices/path endpoints. A forced post-replacement failure
proves exact coloring and fan rollback while retaining unrelated fan state and
all public index roots. Three traced runs on a fixture with 10,000 unrelated
fans and 10,000 unrelated colored edges reduced temporary peak by 4.38%; median
elapsed time regressed 1.38%, so this is a memory result, not a throughput
claim. Full entry/exit audits and global stale-fan cleanup remain. See
[ADR 0079](adrs/0079-bounded-modify-types-rollback.md) and its
[raw comparison](../benchmarks/results/paper/modify-types-local-rollback.json).

Color-Small records pre-activation types and repairs compatibility only for
fans incident to the alternating path and activated spokes, using the existing
vertex-to-fan index. Its coloring rollback now journals first-write path edges
and activated spokes rather than copying every coloring assignment; exact
mid-batch failure rollback is covered. The before-image of all fans is still
retained for rollback. A counted-iteration regression prevents a full fan scan
per activation. On 400 independent fan gadgets (1,600 vertices), median Color-Small
time fell from 144.78 ms to 6.64 ms over three runs, with every edge extended
and full coloring/fan validation passing. A separate rollback-allocation probe
with 25,000 unrelated colored edges and 1,000 fans reduced traced peak by 5.67%
over five runs; elapsed time was not qualified. These component results do not
cover connected adversarial fans or whole Matcher throughput. Other fan repair
callsites and whole-fan rollback snapshots remain open. See
[ADR 0074](adrs/0074-local-color-small-fan-repair.md) and its
[raw record](../benchmarks/results/paper/color-small-local-repair.json).
See also [ADR 0080](adrs/0080-color-small-coloring-journal.md) and its
[rollback allocation record](../benchmarks/results/paper/color-small-rollback.json).

Global `Partial.relabel` now stages graph/properness-checked incident indexes
for mapped colors, then updates existing assignment values in place. This
removes its second full edge-to-color dictionary while keeping all fallible
staging ahead of publication. Five runs on a 200,000-vertex/100,000-edge
matching reduced traced peak by 56.17% and elapsed relabel time by 53.21%; this
disconnected component probe is not a `Spectrum.sparsify` or end-to-end claim.
Invalid permutations and an edge removed during staged certification leave all
coloring indexes and roots unchanged. See [ADR 0081](adrs/0081-in-place-color-relabel.md)
and its [raw comparison](../benchmarks/results/paper/in-place-color-relabel.json).

`Spectrum.sparsify` no longer copies all colored assignments or materializes a
second full set of colored edge keys for its transaction. It composes the
global color permutation with a first-write journal for later path edits;
failure rolls those edits back, applies the inverse permutation, and restores
the original coloring/fan index roots in constant additional root space. Fan
relabel staging now iterates the immutable source membership directly without
an extra sorted tuple. Five complete runs with 30,000 colored edges and 2,000
fans reduced traced peak 9.31%; median elapsed time regressed 3.33%, so this is
a memory improvement with a visible compute tradeoff. See [ADR 0082](adrs/0082-bounded-sparsify-transaction.md)
and its [raw comparison](../benchmarks/results/paper/bounded-sparsify-transaction.json).
Recursive `Extension.extend` also uses the O(1) coloring assignment count for
its progress guard rather than materializing all edge keys; the base-case
regression forbids that snapshot helper. This allocation removal is not covered
by the sparsification benchmark above.

`Extension.extend` also no longer accumulates a second edge set across every
recursive color-group scope. It validates groups are disjoint in color space;
the `project` contract and fan compatibility prove sibling edge scopes are
disjoint, avoiding an O(m) duplicate overlap ledger. Five full two-group runs
with 5,000 fans reduced traced peak by 4.85%; median time changed by +0.57%.
Tests cover both disjoint multi-group projection and rejection of overlapping
groups. See [ADR 0083](adrs/0083-disjoint-recursive-scopes.md) and its
[raw comparison](../benchmarks/results/paper/disjoint-extension-scopes.json).

`Extension.project` now scans the authoritative fan-member set directly when
selecting fans for a color group. This avoids invoking `Fans.__iter__`, which
sorts and materializes the full parent collection even when only a small
fraction belongs to the projected group. In five runs on 75,000 vertices and
25,000 fan gadgets, selecting 1,250 fans reduced median projection time from
46.97 ms to 34.41 ms (26.73%) and traced peak from 3,552,976 to 3,409,048 bytes
(4.05%). This is a one-color-group component probe with no colored edges; it is
not connected-graph, process-RSS, or product throughput qualification. See
[ADR 0084](adrs/0084-stream-parent-fan-selection.md) and its
[raw comparison](../benchmarks/results/paper/project-fan-selection.json).

The projection preflight also no longer keeps a Python degree dictionary or a
sorted copy of the complete edge scope. It constructs the isolated child graph
from the scope and reads the two endpoint degrees from that graph as each edge
is inserted. Five runs on a connected chain of 12,000 fan gadgets, with 600
selected fans, reduced median time from 123.41 ms to 88.17 ms (28.56%) and peak
traced allocation from 23,049,984 to 21,739,072 bytes (5.69%). The infeasible
degree check now occurs after local child-graph construction, but before any
parent mutation; an exact Witness regression covers that failure. This remains
a single-host projection probe, not an end-to-end hierarchy/service qualification.
See [ADR 0085](adrs/0085-reuse-projected-graph-for-degree-audit.md) and its
[raw comparison](../benchmarks/results/paper/project-degree-audit.json).

Recursive hierarchy refinement still uses exact cycle keys to detect an
actually repeated ProcProcess state; matching-repair branches can change M
without consuming the current U vertex, so cycle checks remain. U is monotone
decreasing and never repopulated during one refinement, so states from prior U
frontiers are discarded. The matching-degree array is also exactly derived
from the selected matching: it starts at zero and every selected-edge insertion
or removal updates both together. It is no longer copied into each cycle key.
On five alternating runs of the existing 2,048-vertex/4,096-edge witness-heavy
fixture, canonical hierarchy output remained identical to the pre-change
implementation. Peak traced allocation fell from 2,252,959 to 1,654,047 bytes
(26.59% total reduction across the two cycle-key changes); median time changed
from 419.95 to 396.46 ms (5.59% faster). Current-frontier set snapshots remain
O(state size), and stable-frontier repetitions can retain multiple exact keys.
See [ADR 0086](adrs/0086-bound-refinement-cycle-snapshots.md),
[ADR 0087](adrs/0087-derive-refinement-degree-state.md), and the linked raw
records.

Vizing chain-collision resolution now captures only path/spoke colors and fans
incident to the collision region, uses local compatibility checks, and restores
touched coloring cells without replacing container roots. A failure injected
after publishing the new fan restores exact contents and preserves an unrelated
fan. With 4,000 unrelated fans and 4,000 unrelated colored edges, seven runs
measured median collision resolution at 9.13 ms before and 0.076 ms after
(120.23×), followed by full independent checks. This is a synthetic local
operation result, not a full pruning or Matcher rate; other paper transaction
snapshots remain state-sized. See [ADR 0075](adrs/0075-bounded-vizing-collision-rollback.md)
and its [raw record](../benchmarks/results/paper/vizing-local-collision-transaction.json).

`Pruning.reduce` now resolves blocked fan colors through the existing per-vertex
fan index, repairs only fans incident to each activated chain, and runs local
coloring/fan certificates between complete entry/exit audits. A deterministic
100-edge activation workload with 4,000 unrelated fans measured median runtime
of 2.730 s before and 0.0480 s after (56.88×); all operations completed and full
end-state audits passed. The counted-iteration test confirms the inner loop does
not enumerate the whole fan collection. This disconnected stress fixture does
not establish connected/skewed or end-to-end performance. Other pruning callers
and state-sized rollback snapshots remain open. See [ADR 0076](adrs/0076-local-pruning-certificates.md)
and its [raw record](../benchmarks/results/paper/pruning-local-certificates.json).

`Pruning.prune` no longer copies the whole coloring assignment map or fan
collection for rollback. A reusable `ColorJournal` records first-write spoke
colors, while an invocation-local fan log tracks only newly added fans. An
injected post-add failure restores exact values, preserves both outer roots, and
retains an unrelated compatible fan. On a 50k-vertex/10k-fan component fixture,
traced transient peak fell 2.59%; elapsed time fell 3.45%, a small diagnostic
not claimed as a throughput improvement. Other fan/pruning operations still
have state-sized snapshots. See [ADR 0077](adrs/0077-bounded-prune-rollback.md)
and its [raw record](../benchmarks/results/paper/prune-bounded-rollback.json).

The outer `Pruning.construct` transaction now propagates first-write spoke and
chain before-images through nested prune/reduce work instead of copying every
existing coloring assignment. A failure injected after a completed inner
reduction restores the pre-operation coloring and all index roots. On a
100,200-vertex sparse fixture with 50,000 pre-colored edges and 100 pending
edges, traced transient peak fell 6.06%; elapsed time improved 1.18%, which is
within component-level noise and not claimed as a throughput gain. Full
boundary audits remain. Other paper operations still hold state-sized
snapshots. See [ADR 0078](adrs/0078-journal-construct-coloring-changes.md) and
its [raw record](../benchmarks/results/paper/construct-color-journal.json).

Do not count an accepted design, a passing small test, or an older binary's soak
as completion of a wider release gate. Naming/modularity conventions for new
work are recorded in ADR 0020; established APIs need compatibility planning
before renaming. Hardware testing is distinct from process crash and ENOSPC;
the user explicitly deferred hardware power-loss qualification on 2026-10-02.
It is future engineering, with no current hardware power-loss guarantee.

Candidate `6d5f3cd` bounds moderate-row scans instead of indexing every degree-64
adjacency. Installed fixed traces reduce degree-64 native allocation 81.4%, at
the cost of 38.8% lower core update throughput; graphs and matchings agree exactly.
All 815 original local tests and candidate CI pass. The new binary also completes
a 30-minute full-ring soak at 10,998 durable updates/s, with 17,996,758 coherent
queries, 603 checkpoints and exact recovery. Ack/query p99 upper bounds are
186.1/1.9 ms; peak owner RSS is 182,026,240 bytes. Producer misses and IPC drops
remain explicit; no Busy rejections occur. New-binary sustained full-ring
qualification passes; wider growth/drain/burst/skew qualification remains open.
The hot soak in the table still qualifies the previous binary only.
New-binary short stages pass at 10,975 durable updates/s for degree four and
16,622/s for forced indexed-hub repair, with exact queries/recovery. Degree 64
now fits its explicit 1 GiB native cap but reaches only 6,640/s with losses and
long tails; that denser envelope fails throughput qualification. Native budgets
do not bound SQLite/image copies or total RSS.
See [ADR 0021](adrs/0021-moderate-row-index-policy.md) for the explicit tradeoff.

The growth/drain and burst harness plus rounded-deadline corrections now pass
all CI gates (`a500ad4`): 843 tests and one platform skip on Linux Python 3.12,
including optimized Python, native sanitizers, resource recovery and packaging.
These harness gates do not substitute for their pending million-vertex measurements.

The first million-vertex growth/drain stage completes 1,319,810 real updates at
10,996.6/s, with 1,199,839 coherent queries, 40 checkpoints and exact recovery.
It traverses a full cycle from two to 2.5 million edges and back, then reaches
2,319,810 edges in the next growth phase. Native allocation remains bounded at
77,130,592 bytes under 128 MiB, but owner peak RSS reaches **913,391,616 bytes**.
This passes scoped throughput/correctness, not bounded total-memory qualification.
VM and traced-allocation diagnostics identify retained freed macOS large regions
as the dominant spike on this host. An explicit `MallocLargeCache=0` launch repeat
completes a full cycle at 10,979.2/s with exact recovery and 207,519,744-byte peak
RSS; native allocation is unchanged. This does not install aggregate quotas or
silently alter an embedding process. Longer/no-inspection repeats and Linux
changing-density hard limits remain open. [ADR 0022](adrs/0022-allocator-residency.md)
records evidence, operating policy and portable-checkpoint alternatives.

The no-inspection ten-minute repeat on the same installed `6d5f3cd` wheel and
explicit macOS allocator policy completes 6,599,093 real updates at 10,998.3/s,
5,999,193 coherent queries and 201 checkpoints. Six full growth/drain cycles
and the exact terminal partial cycle recover independently. Owner peak RSS is
208,289,792 bytes, native allocation 77,130,592 bytes; ack/query p99 upper bounds
are 192.7/4.2 ms. All producer misses and IPC drops reconcile; no Busy rejections
occur. This is sustained scoped growth evidence, not portable aggregate quotas,
nor qualification of the later backup correction.
[Raw long-growth evidence](../benchmarks/results/independent/pulse-long-million.json).

The Linux hard-limit drill now includes a full growth/drain cycle followed by
40,000 balanced updates under the same native/address-space/filesystem caps.
Local component/data-flow coverage passes (870 tests). The first extended installed
CI resource run failed at cloning the immutable backup for restore: three physical
SQLite images did not fit the fixed 192 MiB filesystem after growth/drain.
Correction `181f52f` compacts only the private backup; the new installed Linux
resource job passes at the unchanged limits, including exact immutable-backup
restore. Active-work peak RSS is 240,746,496 bytes; the compact backup is
26,054,656 bytes. This resolves that storage failure, not aggregate deployment
quota installation or hardware power-loss qualification.
The older 40,000-update hard-limit report
does not qualify changing density by itself. See [ADR 0020](adrs/0020-resource-exhaustion-and-recovery.md).

The first new-binary burst stage (three minutes, 44k/s active windows and 11k/s
average offers) delivers 10,611 real durable updates/s with 1,799,880 coherent
queries, 58 checkpoints and exact recovery. Its bounded queue rejects 37,240
update offers; producer misses are 32,574, no IPC drops or query Busy. Ack/query
p99 upper bounds are 240.1/2.3 ms. With the explicit macOS allocator profile,
peak owner RSS is 170,573,824 bytes. This is scoped overload behavior, not admission
of every offer or a new latency guarantee. [Raw burst evidence](../benchmarks/results/independent/burst-million.json).

Sparse overlay indexes (`48353b9`) remove eager empty per-vertex incident buckets,
zero counters, and coloring-validation buckets. Exact consistency checks remain.
Identical short 512-vertex basic traces improved median rate from 327.7 to 509.0
updates/s, with lower traced peaks and p99 samples. This does not eliminate
whole-matcher snapshots or qualify the production target; see [ADR 0004](adrs/0004-sparse-phase-indexes.md).

Dense paper `U` partitions now use fixed-universe indexed membership plus
packed ordered members, while sparse partitions keep ordinary sets. System
matching-degree counters use unsigned integer arrays. An isolated one-million
counter allocation is 4.0 MB versus 73.9 MB for the equivalent Python dict;
one-million-label dense `U` needs about 8 MB packed payload. These are
representation measurements only, not end-to-end Matcher memory or update-rate
qualification. The 1/12 density crossover and remaining `A/B` sets, phase
copies, certificates and durable paper integration still need broader evidence.
See [ADR 0041](adrs/0041-compact-paper-system-vertices.md).

The paper System builder now consumes the `Adjacency` and `Packed` edge
iterators directly because each yields rows and neighbors in deterministic
ascending order. Custom Graph implementations retain an explicit sorted
fallback. On one 200k-vertex path, measuring edge enumeration alone reduced
tracemalloc peak from 27.2 MB (global sort/materialization) to 432 bytes and
elapsed time from 0.276s to 0.019s. This excludes builder mutation/partition
costs and is not a rebuild SLA. See [ADR 0042](adrs/0042-stream-paper-builder-edges.md).

Phase System copies and hierarchy `R` regions now retain dense `Vertices`
instead of expanding to Python sets. A one-million-member copy measured 8.0 MB
for the compact representation versus 65.5 MB for a set copy (87.8% lower).
The hierarchy journal admits compact values only in `R1/R_levels`; `A/N`
partitions stay sets. This does not remove graph snapshots, and retained
System/hierarchy/root state still needs end-to-end peak-memory measurement.
See [ADR 0043](adrs/0043-preserve-compact-paper-partition-copies.md).

Multilevel refinement and validation now use packed per-vertex degree arrays;
color-incidence sets are created only for vertices touched by the current
matching. Refinement validates changed-edge membership with graph lookups and
constructs the live edge set in one pass instead of holding a full phase-edge
set plus a second derived copy. Hierarchy partition checks use the existing
System partition validator and cardinality/disjointness rather than building
whole-universe Python sets. These remove avoidable state-sized temporaries;
the surviving live-edge, graph-snapshot and algorithm state are still
state-sized and need peak-RSS benchmarking. See
[ADR 0044](adrs/0044-compact-hierarchy-refinement-state.md).

Multilevel updates no longer run the full hierarchy/cache/phase-graph comparison
after every edge change. `Hierarchy.certify()` checks changed endpoints' Lambda/L
rows, neighborhood bounds, phase edge and level graph bindings; the owner also
checks an O(1) phase-edge-count equation. Full hierarchy checks remain mandatory
at construction/rebuild boundaries, and injected certificate failure restores
exact Matcher/Witness state. An isolated 8,192-vertex, average-degree-four,
128-update trace improved from 19.70 to 148.65 updates/s (7.55×), with 48.6%
lower transient traced peak and 6.6% lower process-peak RSS on one host. This
five-repeat diagnostic is not durable or million-vertex qualification;
matching/auxiliary global checks remain visible costs. See
[ADR 0045](adrs/0045-incremental-paper-hierarchy-certificates.md) and the
[raw comparison JSON](../benchmarks/results/paper/hierarchy-certificates.json).

Incremental update maximality no longer rescans the whole live graph. The
transaction tracks both endpoints of every topology/matching delta and verifies
that each affected unmatched vertex has no unmatched neighbor; a matching-root
replacement still receives the complete audit. A forced missing-rematch test
proves this local certificate rejects and exactly rolls back an uncovered edge.
On the same 8,192-vertex trace, this reduced update rate's previous batch time
from 148.65 to 228.92 updates/s (1.54×) without changing the final certificate.
This does not reduce retained storage. A separate 512-vertex profile had
assigned 30.8% of cumulative update time to the global auxiliary-index audit.
That per-update reconstruction is now replaced with touched inserted-edge and
H/H̃/Ŝ row certificates; changed reverse rows are checked against their source
entries. Full independent audits remain for replacement roots and are asserted
after each generated test update. The same 8,192-vertex trace improved from
228.92 to 436.54 updates/s (1.91×), with final certificate and rebuild counters
unchanged. At 512 vertices profiled time fell 27.3%; sampled memory stayed level.
This is a bounded diagnostic, not production qualification. See [ADR 0047](adrs/0047-incremental-auxiliary-certificates.md)
and its [raw run record](../benchmarks/results/paper/auxiliary-certificates.json).

Stable Matcher-owned System caches no longer enumerate every `Lambda` and `L`
row during journal admission and commit. The fast path validates exact changed
rows and their sorted/nonempty shape; standalone journal admission remains
exhaustive, and new Systems or replaced cache maps receive a full row audit.
Generated tests run complete Lambda/L cache equality checks after each update.
On the same 8,192-vertex trace, rate improved from 436.54 to 610.30 updates/s
(1.40×), with matching certificate and repair counters unchanged; the
512-vertex profile fell from 0.1035 to 0.0733 seconds (29.2%). Sampled memory
stayed level. This remains a bounded in-memory component diagnostic, not an
end-to-end durable throughput result. The new profile's leading cost is deletion
cleanup's scan of the matching plus graph lookups; durable integration is
implemented, while paper-mode qualification and state-sized snapshot/admission
work remain open. See [ADR 0048](adrs/0048-incremental-system-row-validation.md)
and its [raw record](../benchmarks/results/paper/system-certificates.json).

Deletion no longer performs that global scan. Under the Matcher ownership rule,
one update mutates one graph edge, so deleting `(u, v)` can make only `(u, v)`
stale in the matching; it is dropped directly before local rematching. A
regression instruments graph membership calls while unrelated matching size
grows from 16 to 512 edges: the count remains four. On the same fixed
8,192-vertex seeded trace and runner, measured rate rose from 610.30 to
1,103.56 updates/s (1.81×), with an identical final matching certificate and
unchanged sampled memory. This is one-host diagnostic evidence, not a general
latency or durability guarantee. Durable paper integration and state-sized
snapshot/admission work remain open. See [ADR 0049](adrs/0049-local-matching-deletion.md)
and its [raw record](../benchmarks/results/paper/deletion-cleanup.json).

System traversal paths that only need to visit saturated vertices now use a
lazy `A`-then-`B` iterator instead of materializing `A | B`. The public `S`
set property remains unchanged for compatibility. In an isolated one-million-
member allocation probe, peak temporary traced allocation fell from 50,331,864
bytes for the union to 632–1,432 bytes for traversal. This measures temporary
allocation only: retained `A` and `B` are still Python sets, and the probe is
not end-to-end Matcher RSS or update-rate evidence. See [ADR 0050](adrs/0050-lazy-saturated-partition-scan.md)
and its [raw record](../benchmarks/results/paper/saturated-scan.json).

Dense `A` and `B` partitions now use the existing indexed `Vertices` storage at
an explicit 1/8 universe-density threshold; sparse partitions keep Python sets.
System building creates dense partitions directly from temporary member lists,
and phase copies preserve their compact representation instead of round-tripping
through sets. An isolated one-million-label representation probe measured
retained partition allocation of 12.2 MB versus 65.5 MB for two Python sets
(81.4% lower). Set-to-compact conversion itself has a higher transient peak due
to overlap, so the builder path avoids first constructing those dense sets. The
probe is not whole-Matcher RSS or billion-vertex qualification. See [ADR 0051](adrs/0051-compact-dense-system-partitions.md)
and its [raw record](../benchmarks/results/paper/partition-storage.json).

Built hierarchies no longer retain separate copies for `A1`/`N1` when those
values are exactly `A_levels[0]`/`N_levels[0]`. When only one upper A-level is
nonempty, `A2` references that root instead of copying its entire hash table;
multiple nonempty levels still produce the required independent union. In a
one-million-label isolated case, the 500,000-member duplicate `A2` set cost
16,778,056 traced bytes, while selecting the existing root allocated 904 bytes.
This is a partition-shape diagnostic, not an end-to-end hierarchy memory result.
See [ADR 0052](adrs/0052-share-derived-hierarchy-partitions.md) and its
[raw record](../benchmarks/results/paper/hierarchy-partition-aliases.json).

Recursive hierarchy refinement now shallow-carries immutable prior A-level
roots instead of expanding every level to a Python set. Dense A-level rows use
indexed `Vertices` storage at 1/4 universe density; sparse rows remain sets.
The first A/N/R rows share the base System's A/B/U roots, the finest N row
shares its System B root, and the final R row shares finest U. `A2` builds a
compact union when multiple dense upper rows contribute, while retaining the
single-root alias from ADR 0052. An isolated 500,000-member partition that the
old refinement copied to a Python set allocated 35,224,208 traced bytes; root
reuse allocated 64 bytes. This is partition-copy evidence, not end-to-end peak
RSS or multi-level throughput qualification. See [ADR 0053](adrs/0053-compact-hierarchy-levels.md)
and its [raw record](../benchmarks/results/paper/hierarchy-levels.json).

Full hierarchy validation no longer materializes dense A-level unions, cumulative
level-A sets, or `below − N` region sets. Exact dense comparisons use one
byte-per-vertex scratch bitmap; sparse comparisons use direct membership and
cardinality checks without a universe-sized allocation. The independent checker
still detects missing members, duplicates, out-of-range labels, and incorrect
exclusions. On a one-million-label union, peak scratch fell from 35,224,560 to
1,000,969 bytes at essentially the same median time (48.3→46.9 ms). For a
four-partition region difference, it fell from 57,935,496 to 1,000,977 bytes
and median time from 86.2 to 47.4 ms. These are isolated probes, not full
hierarchy rebuild or product qualification. See [ADR 0054](adrs/0054-bounded-hierarchy-audits.md)
and its [raw record](../benchmarks/results/paper/hierarchy-audits.json).

Multilevel rebuilds no longer make an additional full graph clone for
`Matcher.phase_graph`. That field now retains the hierarchy-owned graph root,
which is already transaction-journaled and is not otherwise read through the
separate alias. A one-million-vertex/one-million-edge native ring clone costs
37,000,264 bytes of additional native capacity (median 0.68 ms over seven
isolated copies); avoiding it removes that duplicate retained graph per rebuilt
multilevel Matcher. This does not remove required `phase_base_graph` snapshots
or establish whole-rebuild memory bounds. Identity and injected-failure rollback
tests cover the shared root. See [ADR 0055](adrs/0055-share-hierarchy-phase-graph-root.md).

Child multilevel rebuilds now retain the existing inherited `phase_base_graph`
and `phase_base_system` roots instead of cloning them for retention. Only the
detached graph and System passed into recursive refinement are copied. An
instrumented child-rebuild test observes exactly one graph snapshot and one
System copy, while proving the retained graph, partition roots, and matching
stay unchanged; a separate injected failure proves the Matcher rolls back to
those same roots. Parent-boundary snapshot and System construction remain
unchanged. See [ADR 0056](adrs/0056-reuse-inherited-phase-roots.md).

Full rebuilds now reuse the phase-base graph and level-one System captured at
the start of that same rebuild. Previously the parent-boundary epilogue cloned
the live graph and rebuilt level one a second time even though the full-rebuild
branch had already captured an equal, immutable root. A call-count regression
proves the branch takes one graph snapshot, and both the retained base System
and independently built hierarchy pass their complete checks. Incremental
child-to-parent rebases still take a new snapshot and build the System because
they must fold deferred updates into the new parent phase. See
[ADR 0057](adrs/0057-reuse-full-rebuild-phase-base.md).

Full rebuilds also use the already-constructed phase-base level-one System as
the source for a detached hierarchy level-one copy, rather than executing the
full greedy/promote System builder twice. On an 8,192-vertex degree-four ring,
the isolated base+level-one stage fell from a 44.7 ms median (two builds) to
28.8 ms (one build plus copy) across five repeats. A 512-vertex full hierarchy
measurement was 820 ms versus 816 ms across three repeats—within noise, with
refinement/coloring dominating. An 8,192-vertex full hierarchy timing exceeded
80 seconds and was stopped during coloring validation; it is not a result or
qualification. Thus this removes duplicate level-one work but does not claim
an end-to-end throughput improvement or address the current scale bottleneck.
The builder verifies graph/z/idle binding and the existing rebuild boundary
still checks both phase-base and hierarchy state. See
[ADR 0058](adrs/0058-reuse-level-one-system-build.md).

## Implemented foundation, not product qualification

The installed Linux resource drill now passes at one million vertices under a
hard 512 MiB address-space cap on a dedicated 192 MiB ext4 image. It performs
40,000 real updates, automatic maintenance, actual allocation and disk exhaustion,
fail-stop/reopen recovery and immutable-backup restore, with independently exact
edges, partners, versions and retries. [ADR 0020](adrs/0020-resource-exhaustion-and-recovery.md)
records evidence, class responsibilities and public single-word naming conventions
for new work. This is not a production RSS/page-cache quota, throughput test or
hardware power-loss validation; those deployment/release gates remain separate.

### Historical result: removed native matcher

The former `axiom.engine.Engine` implemented compact partner state and
deterministic local matching repair. Three short million-vertex average-degree-4
churn runs measured approximately 686k–720k in-memory updates/s with exact
independent audits and about 134.5–134.6 MB peak RSS. This implementation and its
standalone documentation have been removed. These artifacts are retained as
historical provenance only: they have no durable acknowledgments and do not
qualify the current Basic or Multilevel methods.

The former native-backed `axiom.durable.Durable` implementation published only
after SQLite FULL-WAL commit and verified deterministic replay. Three short
million-vertex runs with committed matching queries and SQLite WAL checkpoints measured
approximately 30.4k–30.9k real acknowledged changes/s, with independent exact
audits/recovery, acknowledgment p99 14.4–15.5 ms, and 132.7–133.1 MB peak RSS.
This uses 256-operation groups and only 1.29–1.32-second traces. Native graph
checkpoint/concurrent performance, full resource admission, broad/skewed workloads,
limits and sustained/soak qualification remained open. This is historical native
path evidence, not qualification of the current paper-backed Durable implementation.
See [durable contracts/results](durable.md) and [ADR 0009](adrs/0009-sqlite-wal-durable-owner.md).

Exact native checkpoint encoding/restoration is implemented separately. A
million-vertex image is 24,000,040 bytes; reusable row-audit scratch reduced
encoding from 163 ms to 20–21 ms and restore from 177 ms to about 28 ms on the
declared development machine, with identical image/matching hashes and independent
audits. The codec was removed with the native matcher; see the
[historical checkpoint reports](../benchmarks/results/checkpoint/README.md).
Opt-in durable v2 now atomically publishes exact images and retires history while
retaining a declared retry window; expired IDs explicitly reject. Crash, corruption
and disk-full tests exercise old/new generation recovery. Legacy v1 keeps its
lifetime history cap and is not silently migrated. Maintenance performance,
maintenance scheduling and sustained service qualification remain open; bounded
local client aggregation is now delivered separately below.
Three maintenance-inclusive million-vertex v2 traces now reach 27.6k–28.5k
acknowledged changes/s with six native checkpoints each, but checkpoint-bearing
groups reach 193–204 ms max latency. These approximately seven-second traces
query only after acknowledgment; concurrent query/queue tails and soak remain
unqualified. [V2 evidence and limits](durable.md#opt-in-checkpoint-v2-evidence).

The separate local `axiom.service.Service` now bounds active/queued/query/duplicate
work, aggregates individual requests, preserves pending-ID outcomes and schedules
coherent reads on the same owner. Three short million-vertex concurrent-client
runs reach 13.8k–14.0k durable changes/s with ~200k queued queries and six native
checkpoints each. Ack p99 upper bounds are 27.7–27.9 ms; query p99 13.8–14.2 ms,
with ~200 ms maxima. Exact audits/recovery pass. These ~14-second closed-loop
traces meet the throughput target only as a stage; proposed query latency,
sustained/overload/skew/resource/backup gates remain open. See
[service contracts/evidence](service.md) and [ADR 0011](adrs/0011-bounded-service-admission.md).

The earlier queued-read service has now completed a 30-minute million-vertex soak:
24,501,440 real durable updates at 13,611.8/s, 747 native checkpoints and exact
independent recovery. Peak RSS is 204.5 MB; query p99 is still 14.4 ms. This proves
the scoped sustained throughput stage, not overload/skew/resource/backup/power-loss
qualification. [Raw provenance](../benchmarks/results/service/README.md).
The published-partner read path avoids waiting for SQLite without exposing
private batches. Its original four-bytes-per-vertex index is now replaced by a
sparse journal index sized to distinct batch touches; a one-million-vertex
diagnostic saves 3,999,864 initial native bytes with a 1.4% lower single-run
in-memory rate. This is not durable-service qualification. [ADR 0012](adrs/0012-committed-partner-reads.md)
and [ADR 0030](adrs/0030-sparse-committed-partner-index.md) record the contract,
tradeoff and evidence; broader repeats remain active.

Bounded owner backups now capture committed WAL state, exact matching and retry
retirement without a native graph clone. Failure/process-crash tests require an
absent or complete published target and an unchanged source. Installed-package
32k/128k/million restore drills pass independent exact topology/partner audits;
the million backup is 25.62 MB, takes 122.6 ms, and opens/restores in 102.3 ms plus
a separate 3.336-second independent audit. These are single staged samples, not
device power-loss or recovery-SLA qualification. [Evidence](../benchmarks/results/backup/README.md)
and [ADR 0013](adrs/0013-bounded-owner-backups.md). Expensive explicit maintenance
also has a separate active/queued work cap ([ADR 0014](adrs/0014-maintenance-admission.md));
total RSS/WAL/disk, overload/skew and actual power-loss gates remain open.

Forced matched-edge hub repair now has explicit qualification traces. The
million-vertex degree-65536 hub stage measures only 9048 real durable changes/s
(average degree 4.131064), despite passing exact topology/matching/recovery audits.
This **does not meet** the throughput target for that skewed workload. Short
uniform results cannot establish broad scalability. A paced offered-load harness
also counts producer-missed slots and admission rejections separately from actual
durable delivery. [ADR 0015](adrs/0015-skew-and-offered-load-qualification.md) and
[raw skew evidence](../benchmarks/results/service/README.md) record the limits.

The budgeted sparse-free bitmap search now raises the same short million hub
trace to 15322 durable updates/s with identical trace/matching hashes. A longer
200000-update/200000-query stage reaches 16108/s, query p99 <=0.5 ms and ack p99
<=24.9 ms; max acknowledgment remains 207.0 ms. The index adds 127160 bytes,
not a whole-graph copy. [ADR 0016](adrs/0016-sparse-free-vertex-search.md).
Read admission reservation protects concurrent partner clients under update
saturation without bypassing the global cap: measured query Busy is zero at
10k/100k update offers/s. The paced 10k-offer test still delivers only 9508/s;
shared-GIL producer misses, checkpoint stalls, new-code soak, hard RSS/WAL/disk
and actual power-loss qualification remain open.
[ADR 0017](adrs/0017-read-admission-reservation.md).

Thread safety is delivered at the local `Service` boundary: explicit admission,
receipt, close and publication locks, one mutation owner, and coherent versioned
reads on GIL-enabled CPython. Concurrent client tests and native sanitizer stress
cover private batches and publication. This is not arbitrary concurrent access
to the standalone C++ engine, free-threaded CPython support or a cross-call graph
snapshot. SQLite stores complete recoverable checkpoint-plus-tail state; native
adjacency/matching remains the live compute layer, not a second durable authority.

Checkpoint diagnostics separate retained-history validation, audited native
encoding and SQLite persistence. Strict history predicates are now inline rather
than six Python helper calls per row; checksum/type/range/version checks remain.
Malformed-history injection requires fail-stop before publication. The 732-test
suite and installed-wheel smoke pass. A candidate 10k-offer run still delivers
only 9565/s, so this small dispatch reduction does not complete the target.
[ADR 0018](adrs/0018-checkpoint-history-validation-cost.md) records the evidence
and the consistent-snapshot design needed before attempting background maintenance.

Separate-process paced arrivals now distinguish producer misses, bounded IPC
drops and server admission rejections. With explicitly configured queue capacity
4096 and transport batches of 16, one 30-second million-vertex stage delivers
10930 real durable updates/s and 299261 matching queries, including ten checkpoints
and exact independent recovery. Query p99 <=2.2 ms; ack p99 <=184.8 ms.
These are local transport stages with losses, not a loss-free network or hard
resource claim. [ADR 0019](adrs/0019-independent-arrivals-and-bounded-ipc.md).
The user accepted present latency for this version and requested stricter latency
engineering be marked future work. Continue with hard resource failure behavior
and backup/recovery validation; do not invent a numeric RSS/latency SLA or treat
process-crash tests as physical power-loss proof.

The installed production path now completes a separate-process **30-minute**
hot-edge soak at **10,972.9 real durable updates/s**, with 19,751,386 acknowledged
changes, 17,956,015 coherent queries, 602 checkpoints and exact independent
recovery. Owner peak RSS is 183.1 MB. Update misses/drops are 48,470/144, with no
Service Busy; this is not loss-free delivery. Ack/query p99 upper bounds are
178 ms/1.8 ms, but maxima reach 1.88 s/1.74 s. Full-ring working-set qualification,
repeatability and deployment quotas remain separate work. Hardware power loss is
deferred for this version, with no delivered guarantee.
[Raw evidence and provenance](../benchmarks/results/independent/README.md#completed-30-minute-hot-edge-soak).

The separate 30-minute **full-ring sweep** also passes: 19,796,515 real durable
updates at 10,998.0/s, 17,997,025 exact version-referenced queries and 603
checkpoints. It traverses all matched ring edges nineteen times. The odd final
prefix leaves one edge absent, with exact independent topology/matching/restart
agreement. Owner peak RSS is 182.2 MB; native allocation remains 49.1 MB.
Update misses/drops are 3,421/64, no Busy. Ack/query p99 upper bounds are
183.4 ms/1.9 ms, maxima 238.0 ms/46.9 ms. This expands sustained working-set
evidence without claiming loss-free delivery or deployment quotas.
[Raw record](../benchmarks/results/independent/soak-sweep-million-4096-11000.json).

Denser diagnostics identify a storage-policy cliff rather than establishing wider
support. A 30-second degree-16 prefix delivers 10,751.1/s with exact recovery,
but 7,081 update Busy rejections, ack/query p99 422.7/125.4 ms and 420.7 MB peak
RSS. Degree-64 construction rejects under a 1 GiB native budget before producer
start. The degree-32 indexing threshold would index every degree-64 row; its
global directed-key table needs 2 GiB of slots alone, before adjacency/metadata.
Next investigate bounded moderate-degree scans while retaining indexed hubs, with
deterministic/rollback/certificate and compute regressions. Do not silently raise
resource ceilings or claim a rejected configuration supported.
[Dense diagnostics](../benchmarks/results/independent/README.md#degree-16-prefix-and-degree-64-admission-rejection).

`Packed` now provides compact native segmented adjacency, bounded native growth,
reusable blocks, high-degree edge lookup, and owner-bound inverse-edit journals.
Matcher transactions use those journals for native managed graphs; phase snapshots,
hierarchy projections, and coloring subgraphs retain the backend. Native edits
receive immediate local storage certificates; opaque custom graphs retain the full
edge-set mutation check. Base-phase graphs are included in rollback protection.

Regression tests cover differential graph operations, high-degree index transitions,
budget rejection, compaction, stale transaction tokens, foreign-thread access,
iterator invalidation after aborted mutations, and failed matcher updates across
phase rebuilds. A standalone C++ stress test exercises 200,000 mixed edits with
differential audits and rollback under address/undefined-behavior sanitizers.

Three fresh-process **storage-only** measurements on the same M3 Pro constructed
1,000,000 vertices and 2,000,000 ring edges (average degree 4), performed 20,000
delete/reinsert pairs with one committed journal per edit, and independently checked
every final neighbor row against the original ring:

- Native retained allocation after edits: 41,000,360 bytes (~41 MB).
- Process peak RSS, including Python, trace samples, and audit: 83.4–83.8 MB.
- Whole timed-trace rate: 3.31–3.56 million real storage edits/s.

These short, cache-friendly, fixed-degree traces are **historical storage-only
measurements**, not matcher throughput, durable acknowledged throughput,
long-running churn, or a billion-scale result.
The native byte budget excludes Python objects, allocator overhead, audit scratch,
and other containers. Each derived graph currently has its own budget, not a shared
service-level quota. The paper `Matcher` update path no longer uses recursive
`deepcopy`, but remaining paper operations still materialize graph-sized scopes,
indexes, or snapshots and some hierarchy checks/rebuilds perform global work.
The storage/journal figures and native matching/service results elsewhere in
this archive describe the removed native matcher. Current paper-backed
`Durable`/`Service` integration is implemented; paper-mode performance and
deployment qualification remain open.

See [native storage contracts and reproduction](storage.md) and the raw
[seed 599](../benchmarks/results/storage/million-599.json),
[seed 600](../benchmarks/results/storage/million-600.json), and
[seed 601](../benchmarks/results/storage/million-601.json) measurements.

## What the evidence says

On an Apple M3 Pro, 18 GiB RAM, Python 3.14.7, short degree-target-4 sparse churn
traces produced these median real-update rates:

| Vertices | Initial edges | Basic updates/s | Multilevel updates/s | Greedy recompute updates/s |
| ---: | ---: | ---: | ---: | ---: |
| 32 | 64 | 4,280 | 1,502 | 102,825 |
| 128 | 256 | 1,302 | 511 | 26,842 |
| 512 | 1,024 | 318 | 94 | 6,433 |
| 2,048 | 4,096 | 74 | whole-case timeout; no rate | 1,502 |

The 2,048-vertex multilevel cases exceeded a 20-second whole-case budget; no update
rate is inferred from that timeout. Across pilot, long-trace, and expansion runs,
888/990 cases completed successfully, with 102 whole-case timeouts and no recorded
correctness failures.

Each rate is the median of three seed-specific rates, each based on five timed
fresh-state repetitions of a 32-call trace after warmup. These traces do not
establish steady-state phase costs. The greedy baseline lacks Axiom's atomic
rollback and hierarchy guarantees; it is a comparison, not a drop-in replacement.

The pilot completed 852 of 945 cases; 93 reached an eight-second **whole-case**
limit. No completed case failed its graph/proper-matching/maximality checks.
The limit includes initialization, all repetitions, latency instrumentation,
and traced memory, so it does not establish an eight-second individual update.
Timeouts particularly affect denser or higher-degree multilevel configurations.

Separate function profiling of 256 sparse churn calls provides a concrete
optimization direction:

| Vertices | Mode | `deepcopy` inclusive time share | Hierarchy `check` inclusive time share |
| ---: | --- | ---: | ---: |
| 128 | basic | 77.8% | not active |
| 128 | multilevel | 60.0% | 23.6% |
| 512 | basic | 76.4% | not active |
| 512 | multilevel | 53.1% | 31.6% |

These percentages are instrumented diagnostic measurements, not unprofiled
throughput. Inclusive times overlap and must not be summed into a cost breakdown.
The transaction code enumerates managed graph edges and deep-copies almost all
matcher state before each accepted update. This observation, together with the
profile, makes transaction cost the first engineering investigation—not proof
that the underlying matching algorithm is the dominant bottleneck.

See [measurement methodology](performance.md), the generated
[full report](../benchmarks/results/report/report.md), and
[function-level evidence](../benchmarks/results/diagnosis.json).

## Target: one million vertices

The target is now **1,000,000 vertices**. Assume average degree 4 initially:
approximately 2,000,000 undirected edges and 4,000,000 adjacency entries. Vertex
count alone is insufficient: average degree 64 means 32,000,000 edges, and a
complete million-vertex graph would have roughly 500 billion edges. The service
needs an explicit edge-count and degree/workload envelope.

**Can we reliably maintain it?** Million-vertex native Service measurements
below are historical evidence for a removed matcher and do not establish the
current paper modes' envelope. Basic and Multilevel have durable acknowledgments,
coherent queries, and deterministic recovery by operation replay, but their
million-vertex performance, recovery-at-scale, and deployment limits are not
qualified. Remaining state-sized work and exception rollback alone do not
establish production scalability or durability.
Do not extrapolate either small-graph rates or short stages into an unconditional
million-vertex throughput/reliability promise.

### Start on one appropriately sized machine, not arbitrary graph shards

Use dense stable internal vertex IDs in `[0, 1_000_000)`, with a separately
accounted and persisted external-ID mapping if needed. The existing API has a
fixed vertex universe; its insertion/deletion methods mutate **edges**, not the
vertex universe. A vertex-lifecycle API would need its own invariants.

Keep `basic` and `multilevel` as the only matching algorithms. Continue using
`Packed` only for compact graph storage; do not add a separate native matching
backend. Optimize paper-mode hot paths only with differential tests and exact
rollback coverage. Compact adjacency alone does not eliminate Python snapshots
or full hierarchy scans; storage, transactional mutation, and validation must
be designed together.

For scale intuition, a static CSR backbone with 64-bit offsets and 32-bit
neighbors has these raw array sizes:

| Average degree | Undirected edges | Adjacency entries | Offsets + neighbor bytes |
| ---: | ---: | ---: | ---: |
| 4 | 2,000,000 | 4,000,000 | about 24 MB |
| 16 | 8,000,000 | 16,000,000 | about 72 MB |
| 64 | 32,000,000 | 64,000,000 | about 264 MB |

These are decimal MB arithmetic, **not measured resident-memory requirements**.
A 32-bit partner array adds about 4 MB, and a 32-bit degree array another 4 MB.
External-ID indexes, edge lookup, dynamic capacity, hierarchy/coloring/fan state,
allocator overhead, logs, overlays, query versions, and compaction/checkpoint
headroom are additional. Budget every layer explicitly before running at scale.

CSR is not itself an efficient arbitrary-update representation. Investigate
packed segmented adjacency with bounded spare capacity, or a compact backbone
with bounded insertion/tombstone overlays and controlled compaction. Stable
neighbor order must preserve deterministic behavior. Compaction must obey the
same publication/versioning contract as updates and must not require unbounded
extra memory. There is no basis yet for claiming a particular total RSS.

One connected graph should initially have one sequenced mutation owner. Native
local work, bounded journals, and incremental certificates are the primary
throughput opportunities. Independent graphs can have independent workers.
Sharding arbitrary edges of the same graph is unsafe without a distributed
matching algorithm that handles cross-partition constraints.

### Make accepted updates durable and graph/view versions coherent

The service boundary should be:

```text
bounded admission -> sequenced transaction -> validate -> durable commit
                                                         |
                                                         v
                                               publish graph + matching version
                                                         |
                                                         v
                                                    acknowledge
```

Assign monotonic sequence numbers and client operation IDs. Define duplicate
request semantics separately from duplicate edge insertion. Record a durable
transaction/WAL with an unambiguous commit marker and operation outcome;
checkpoint a verified committed version. Only acknowledge after the required
durability barrier and publication of a coherent committed version. Group commit
can trade latency for throughput, but its durability contract must be explicit.

A crash after durable commit but before acknowledgment must be recoverable via
operation-ID deduplication, not a second logical mutation. Replay only committed
transactions. Persist the algorithm/state-format version and all state needed
for the promised deterministic replay contract. If matching is reconstructed
from graph-only checkpoints instead, explicitly permit a different proper
maximal matching; do not claim identical historical matching decisions.

Queries must reference one committed graph/matching version. Use O(1) partner
and size lookups; expose large matching results through bounded, versioned pages
or streams rather than copying and serializing hundreds of thousands of edges
per request. Bound retained reader versions and checkpoint copy-on-write memory.
Do not publish a new graph with a stale matching view unless a separately defined
eventually consistent API explicitly permits it.

On disk-full/fsync failure, ambiguous durability, failed rollback, or a detected
certificate mismatch, stop accepting mutations and enter an explicit degraded
state. Do not acknowledge success or continue exposing questionable state. Recover
from a verified checkpoint plus the committed log. In-memory transaction rollback
alone does not cover these failure modes.

### Bound resource use and qualify reliability before claiming support

Reserve journal/undo capacity before mutation where possible; undo must not
depend on allocating a fresh whole graph during memory pressure. Bound admitted
queue depth, edge count, degrees where required by the target workload, journal
size, rebuild backlog, overlay size, retained query versions, and checkpoint
headroom. Reject or backpressure before exceeding limits; arbitrary overload is
not a reliability guarantee. Report queue waiting separately from execution
latency and end-to-end acknowledged latency.

Qualification should progress from the measured 2,048-vertex envelope through
32,000 and 128,000 vertices to 1,000,000, on a dedicated resource-limited runner.
Do not launch the current object-heavy million-vertex engine on a shared developer
workstation as an unbounded experiment. At each stage, measure constructor time,
real update rates, p99/max execution and acknowledgment latency, actual RSS,
transient peaks, checkpoint/replay times, and queue saturation under average
degrees 4, 16, and 64 plus skewed hubs/bursts. Set deployment-specific limits
before the million-vertex qualification run.

Run long-duration churn with compaction/checkpointing to catch memory growth.
Inject process termination at WAL/apply/commit/publish/acknowledgment boundaries,
duplicate/reordered client requests, disk-full and corrupt-checkpoint failures,
and algorithmic exceptions during chain/fan/phase transitions. After recovery,
require the committed graph, proper maximal matching, state-version consistency,
and deduplication outcomes to agree with the defined reference contract.

Keep mandatory incremental pre-commit checks and perform full audits against
consistent committed snapshots. A periodic audit is defense in depth, not a
substitute for immediate invariants. Alert on rollback failures, invariant
violations, queue/journal/backlog pressure, and checkpoint/replay lag. This is
the qualification needed to answer "reliable at a million vertices" with evidence,
not merely successful construction or a short throughput run.

## Assessment: one billion vertices

**No reliable billion-vertex claim is supported by the current implementation
or measurements.** Original paper diagnostics reached 2,048 vertices; newer
native production measurements reach one million, not one billion. The retained
Python paper representation and full-state copying are not efficient choices
for that target. Native local journals remove those particular production costs,
but do not establish billion-vertex resource, durability or throughput support.

Using the same sparse assumptions and uncompressed packed-array arithmetic:

| Average degree | Undirected edges | CSR offsets + neighbors | Plus 32-bit partner and degree arrays |
| ---: | ---: | ---: | ---: |
| 4 | 2 billion | about 24 GB | about 32 GB |
| 16 | 8 billion | about 72 GB | about 80 GB |
| 64 | 32 billion | about 264 GB | about 272 GB |

These decimal-GB figures are a **storage model**, not a measured total RSS or an
information-theoretic lower bound. They exclude dynamic edge lookup indexes,
external-ID mapping, hierarchy/coloring/fan state, allocator capacity, replicas,
WAL/checkpoints, retained versions, and rebuild/compaction headroom. Compression
may reduce some components but changes access/update costs and must be measured.
IDs below one billion fit in 32 bits; adjacency offsets need 64 bits at these
edge counts.

The current `Adjacency` eagerly creates one Python set per vertex. On the measured
CPython environment an empty set occupies 216 bytes and a list slot 8 bytes.
Multiplying those object sizes by a billion gives about **224 GB for one empty
adjacency layer alone**, before neighbors, integer objects, other graph layers,
matching state, snapshots, and allocator overhead. This is allocation arithmetic,
not an actual billion-vertex allocation or an extrapolated RSS measurement.
Full-state copying then repeatedly touches global state on accepted updates,
even when the logical edge mutation is local. More workers do not remove that
cost or establish correct concurrent updates to one graph.

The billion-vertex path needs a separate qualification program:

1. Replace object-heavy storage and snapshot work with a native, compact,
   locally transactional engine; establish bounded per-transition work and
   memory through correctness-certified experiments, not a language-port promise.
2. Define the edge/degree/skew envelope, required acknowledged update rate,
   query consistency, p99 budget, durability, and recovery-time objectives.
   One billion mostly isolated vertices is a different problem from billions
   of live edges; do not treat vertex count as the workload specification.
3. Qualify million-, ten-million-, and hundred-million-vertex candidates with
   explicit memory/time caps and long-run checkpoint/compaction/failure tests
   before a dedicated billion-vertex run. The million-vertex candidate is delivered;
   larger stages are not qualified here.
4. Choose a large-memory single owner or a distributed design based on measured
   total memory and required throughput. Billion vertices alone does not prove
   that distribution is necessary: an ideal sparse backbone is tens of GB,
   while the full mutable algorithm and its recovery headroom may be much larger.
5. If distributing one graph, design cross-partition matching repair and atomic
   publication explicitly. Partitioned graph storage alone does not preserve
   a globally proper maximal matching after every update. Communication,
   coordination, hotspots, and recovery become additional performance costs.

For a distributed service there is also a product choice: retain the current
strong graph/matching consistency contract and implement coordinated repair,
or expose durable graph ingestion with an explicitly versioned, lagging matching
view. The latter may be easier to scale but is a **different API contract**, not
a silent optimization of the present engine. Neither design has been built or
qualified by this benchmark.

Production transaction journaling and incremental certificates are implemented
for the paper-backed service. The next scale work is staged qualification and
remaining snapshot/hierarchy optimization. Measurements do not demonstrate that the current
algorithm, implementation, or proposed architecture will meet a billion-vertex
service's compute, memory, or reliability requirements.

## Reliability is part of the performance contract

An accepted update currently aims to be all-or-nothing across the caller's live
graph, matching views, recursive hierarchy, auxiliary indexes, and counters.
Managed graph objects are preserved by identity. A failed coloring or invariant
check must not leave these objects describing different states.

Therefore, "remove deepcopy" or "turn off checks" is not a complete solution.
Any replacement must preserve:

- Proper maximal matching and agreement between edges, matched vertices, and
  partner lookup after every accepted update.
- The same authoritative caller-supplied graph object and coherent managed
  graph objects after both success and failure.
- Hierarchy, coloring, fan compatibility, auxiliary forward/reverse indexes,
  and phase/accounting state after rollback where those structures participate
  in a transition.
- Determinism, explicit error behavior, and distinct real-update/no-op semantics.

The benchmark certificate independently checks canonical existing disjoint edges
before maximality. The existing maximality helper alone does not establish that
a candidate edge set is a proper matching.

## Prioritized solution plan

### 1. Establish a workload envelope and acceptance gates

Record the deployment's typical and maximum `n`, `m`, degree distribution,
insertion/deletion ratio, burst length, query/update ratio, and required p99 and
memory limits. Vertex/average-degree/acknowledged-rate targets are now accepted
(ADR 0001); deployment-specific p99, resource, query-mix, and recovery limits
remain to be recorded. This benchmark does not invent agreement on those SLOs.

Use the checked-in traces as repeatable engineering gates. A provisional first
optimization target is at least 2× basic sparse throughput at 512 vertices,
without increasing pooled p99 latency or memory peak by more than 10%, and with
all rollback/correctness checks passing. This is a proposed gate, not a measured
gain or a service guarantee. Compare on the same controlled machine, using
repeated baseline/candidate runs; widen the experiment if observed variation is
near the gate. Do not accept gains obtained by dropping validation or sampling
different traces.

### 2. Matcher recursive-copy removal: delivered; durable integration implemented

`Matcher.__atomic_update` now records shallow attribute roots and delegates
in-place edits to bounded owner journals for graph storage, views, classes,
Systems, hierarchy/deferred edges, auxiliary indexes, clocks and accounting.
The Matcher update path does not import or call `deepcopy`. Tests patch the
standard-library function to fail during successful updates and injected failure
rollback. This avoids recursively traversing and allocating the full object
graph; it is not a claim of constant-time transaction admission, since some
certificates and System admission passes remain state-sized.

Remaining engineering: continue auditing paper mutation sites; add adversarial
negative/boundary coverage for each owner; measure transient journal memory and
latency; and remove or bound the remaining state-sized admission, certificate,
snapshot, and hierarchy work. Both supported modes are already integrated into
durable service/recovery. Keep graph identity and exact failure rollback; a
rollback failure remains fail-stop, never a silent success.

### 3. Make invariant maintenance incremental, not optional

The multilevel profile identifies hierarchy checks as another substantial cost.
Explore cached local certificates and dirty-node propagation through affected
hierarchy paths. Validate changed structures on every update and retain full
independent audits at phase boundaries and in differential/stress tests.

Removing a full scan is safe only after proving that every mutation invalidates
the appropriate certificate and that the replacement check detects the same
relevant failures before commit. An unchecked "fast mode" is not the reliability
solution. A periodic audit alone is not equivalent to immediate invariant
enforcement; document any deliberately weaker contract as a separate API choice.

### 4. Bound rebuild latency without breaking atomic visibility

Use the long-trace boundary samples to decide whether ordinary work or rebuild
spikes dominate the target workload's p99. If rebuilds violate the chosen budget,
investigate a versioned candidate build with a mutation backlog and a validated
publication point. Reconcile updates received during construction before publish.
Bound backlog memory and reject or backpressure inputs when limits are exceeded.

This is a design investigation, not a proposal to execute the current mutable
matcher concurrently. The standalone mutation engine remains owner-bound;
concurrent clients use the thread-safe Service boundary, not simultaneous engine
mutation. Incremental/background rebuilding requires explicit consistency,
query visibility, cancellation, and recovery contracts, with adversarial tests
around the publication boundary.

### 5. Scale at the appropriate boundary

For a service, serialize mutations per graph behind a bounded queue; define
admission control, cancellation rules, and explicit completion/error
responses. Do not acknowledge an update before its transaction commits. Keep
queries coherent with committed versions.
The delivered local service rejects cancellation after sequenced acceptance:
cancelling an assigned ID would create a stream gap. Pre-admission rejection has
no mutation/ID consumption; wait timeout is explicit uncertainty, not cancellation.
[ADR 0011](adrs/0011-bounded-service-admission.md) records this tradeoff.

Independent graphs can be distributed across workers without changing matching
semantics. Arbitrarily sharding one connected graph is not equivalent: matching
edges and hierarchy dependencies can cross partitions, so that would require
another algorithm and correctness contract. The current benchmark says nothing
about network throughput, durability, recovery after process death, or multi-client
contention; evaluate those separately if they are product requirements.

## Regression and release gates

| Risk | Required evidence before merging an optimization |
| --- | --- |
| Silent partial update | Failure injection, exact state/identity restoration, subsequent update succeeds |
| Invalid matching or coloring | Independent proper/maximal matching and complete/proper coloring certificates |
| Fan/chain state corruption | Compatibility checks and exact fan/coloring rollback through forced collisions and flips |
| Stale incremental certificate | Deliberately corrupt each tracked dependency and require rejection before commit |
| Rebuild tail regression | Long traces crossing multiple boundaries; count each boundary category and report p99/max |
| Memory explosion | Separate constructor/update traced peaks, journal/backlog bounds, and isolated process RSS |
| Misleading rate improvement | Identical trace digests, real/no-op separation, fresh repeats, seed variation, no competing benchmark jobs |

Keep ordinary-update, rebuild-boundary, and failure-recovery benchmarks distinct.
In CI, run small correctness/calibration cases rather than asserting unstable
wall-clock numbers on shared runners. Run performance acceptance on controlled
hardware and preserve raw evidence. Track workload, commit/source hashes, mode,
phase counters, matching validity, and rollback failures with every result.

## Reproduce the diagnostic

```sh
.venv/bin/python benchmarks/diagnose.py \
  --sizes 128 512 --updates 256 --seed 7 \
  --output benchmarks/results/diagnosis.json
```

Run profiling separately from the throughput suites. The checked-in baseline
does not include a journal, incremental certificates, background rebuilds, or
service queues. Those are prioritized follow-up designs with explicit gates;
the current deliverable is reproducible evidence and the reliability envelope
needed to implement them safely.

Hierarchy validation now counts matching degrees sparsely when matching density
is low, rejects degree-cap violations during counting, and reuses the final
level's count state for its minimum-degree predicates. A 100k-vertex/one-edge
certificate reduced isolated traced peak by 87.4% in one before/after run, with
no demonstrated timing gain. This is component evidence only; repeatability,
connected/dense adversarial cases, full paper snapshots, and durable production
integration remain open. See [ADR 0090](adrs/0090-sparse-hierarchy-degree-audits.md).

Paper seed palette reduction also accumulates all color frequencies in one pass
over the combined coloring, replacing one full edge-color scan per palette
color. A deterministic K34 excess-palette fixture enters the reduction branch
and remains fully certified; three warmed before/after runs were timing-neutral
at this small scale. The asymptotic frequency work falls from O(E·C) to O(E),
with O(C log C) deterministic ordering. Large high-degree seed qualification
remains open; see [ADR 0091](adrs/0091-linear-seed-palette-counting.md).

Euler partition component discovery now starts from live edge endpoints instead
of a `set(range(n))`; this avoids allocating/scanning isolates that cannot occur
in the output. On 2,048 labels with three edges, three runs reduced partition
time 98.98% and traced peak 98.30%, with identical edge partitions. The
subsequent global degree-bound scans remain O(n), and connected/dense behavior
is not qualified. See [ADR 0092](adrs/0092-sparse-paper-partition-components.md).
The follow-up now evaluates the same maximum-degree and balanced-output
certificates only over active component vertices, eliminating those remaining
universe scans without dropping either check; see [ADR 0093](adrs/0093-local-paper-partition-degree-audits.md).
The public paper colorer and recursive seed use the same adaptive maximum-degree
probe: stream edge endpoints when `2m < n`, otherwise scan `n` vertices. On a
100k-label/3-edge component probe this cut median time 92% with 128 bytes more
traced scratch. Complete recursive seed qualification remains open; see
[ADR 0094](adrs/0094-adaptive-paper-maximum-degree.md).

The public `System.switch` primitive now records only path-edge membership and
endpoint-degree before-images, applies local degree deltas, and rolls back
injected partial writes without copying/recounting all of M. A 20k-vertex
failed-search probe reduced traced peak 99.925%; 1,000 random differential
cases matched the previous result/state. Repository search finds no internal
callers, so this component improvement is not end-to-end hierarchy evidence.
See [ADR 0095](adrs/0095-path-local-switch-undo.md).

Sparse `refine_hierarchy` matching degrees no longer allocate an n-sized array
when only a few selected edges touch vertices. A one-million-counter component
microprobe fell from 4,000,164 bytes to 904 bytes. On a 20k full-refinement
fixture, aggregate traced peak/time were neutral; snapshots and other hierarchy
allocations dominate, so this is not an end-to-end win. See
[ADR 0096](adrs/0096-sparse-refinement-degrees.md).

Refinement cycle detection now uses the exact monotone U-cardinality potential
instead of copying U, A and M into three frozensets per pass. The guard requires
strict U reduction whenever another pass is requested. Four baseline/candidate
Witness comparisons were identical; a 20k star refinement was 6.1% faster, but
aggregate peak stayed flat due to other state. See
[ADR 0097](adrs/0097-monotone-refinement-progress.md).

Recursive refinement also compares the coloring key view directly against the
selected matching rather than allocating two full edge sets for completeness
validation. A 100k-edge component probe measured 8,389,040 to 112 bytes of
traced comparison peak and 2.45 to 0.90 ms median; full-refinement performance
is not inferred. See [ADR 0098](adrs/0098-compare-refinement-coloring-keys.md).

Paper fan intake no longer materializes graph/colored-edge copies to validate a
small supplied uncolored set. Direct fan construction stores incidence and
palette state only for touched endpoints, and spectrum classification sorts
once rather than retaining a normalized edge-set duplicate. At 100k labels and
one edge, the old intake allocation shape used 44.06 MB traced peak versus
2,264 bytes for a full direct call; this component comparison does not establish
end-to-end pruning throughput. See [ADR 0099](adrs/0099-sparse-paper-fan-intake.md).

Color-Small now journals only changed fan memberships for failure rollback
instead of sorting and retaining every fan. On a 20k-fan/one-touched-fan
operation probe, traced peak fell from 1.78 MB to 1,872 bytes and median time
from 8.24 ms to 0.017 ms. Full coloring/fan audits at the operation boundary
remain global; this is a rollback-state reduction, not end-to-end throughput.
See [ADR 0100](adrs/0100-journal-color-small-fan-rollback.md).
