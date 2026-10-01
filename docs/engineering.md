# Scalability and reliability: engineering assessment

This is a measured improvement plan with an initial native-storage implementation,
not a claim that the full scalability or durability roadmap has been delivered.
Production matching semantics remain unchanged. The default backend is still the
Python reference; native graphs are explicitly selected by callers.

The accepted production target is now **10,000 real edge updates/s at 1,000,000
vertices and average degree 4**, including durable acknowledgments and coherent
matching queries. The user approved a separate native incremental maximal-matching
production backend; the paper/coloring/hierarchy engine remains available and is
not silently replaced. The target is **not achieved**. See the explicit rationale,
contracts, alternatives, and implementation status in [architecture decision
records](adrs/README.md).

Sparse overlay indexes (`48353b9`) remove eager empty per-vertex incident buckets,
zero counters, and coloring-validation buckets. Exact consistency checks remain.
Identical short 512-vertex basic traces improved median rate from 327.7 to 509.0
updates/s, with lower traced peaks and p99 samples. This does not eliminate
whole-matcher snapshots or qualify the production target; see [ADR 0004](adrs/0004-sparse-phase-indexes.md).

## Implemented foundation, not product qualification

The explicit native production core `axiom.engine.Engine` now implements compact
partner state and certified deterministic local matching repair without global
snapshots. Three short million-vertex average-degree-4 churn runs with partner
queries measured approximately 686k–720k in-memory real updates/s, with exact
independent graph/proper-maximal matching audits and about 134.5–134.6 MB peak RSS.
These runs have **no durable acknowledgments** and do not qualify sustained
maintenance/recovery/service behavior. See [native core contracts/results](engine.md).

The separate `axiom.durable.Durable` layer now publishes only after SQLite FULL-WAL
commit, preserves original retry outcomes, verifies bounded deterministic replay,
and fails closed on persistence/publication uncertainty. Three short million-vertex
runs with committed matching queries and SQLite WAL checkpoints measured
approximately 30.4k–30.9k real acknowledged changes/s, with independent exact
audits/recovery, acknowledgment p99 14.4–15.5 ms, and 132.7–133.1 MB peak RSS.
This uses 256-operation groups and only 1.29–1.32-second traces. Native graph
checkpoint compaction, aggregate admission, broad/skewed workloads, full resource
limits and sustained/soak qualification remain open; this is **not** goal completion.
See [durable contracts/results](durable.md) and [ADR 0009](adrs/0009-sqlite-wal-durable-owner.md).

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

These short, cache-friendly, fixed-degree traces are **not matcher throughput,
durable acknowledged throughput, long-running churn, or a billion-scale result**.
The native byte budget excludes Python objects, allocator overhead, audit scratch,
and other containers. Each derived graph currently has its own budget, not a shared
service-level quota. Full matcher state is still deep-copied; hierarchy checks and
rebuilds still perform global work. WAL/recovery, admission control, incremental
algorithm-state journals/certificates, and full-engine qualification remain open.

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

**Can we reliably maintain it?** A bounded sparse graph is a plausible engineering
target with compact storage and a carefully qualified incremental engine. This
repository has not demonstrated reliable million-vertex operation. The current
Python full-state snapshot/scan path is not a production scaling solution, and
exception rollback is not durability or recovery after process death. Do not
extrapolate the small-graph rates into a million-vertex throughput promise.

### Start on one appropriately sized machine, not arbitrary graph shards

Use dense stable internal vertex IDs in `[0, 1_000_000)`, with a separately
accounted and persisted external-ID mapping if needed. The existing API has a
fixed vertex universe; its insertion/deletion methods mutate **edges**, not the
vertex universe. A vertex-lifecycle API would need its own invariants.

Introduce a native compact storage/algorithm backend, keeping Python as the
control, reference, testing, and experiment layer. Port or optimize the measured
hot paths only with differential tests against the reference engine. A native
adjacency container alone does not eliminate Python snapshots or full hierarchy
scans; storage, transactional mutation, and validation must be designed together.

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
or measurements.** We have measured up to 2,048 vertices, not one million or one
billion. The current representation and successful-update full-state copying
are not compute- or memory-efficient engineering choices for that target.

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
   before a dedicated billion-vertex run. No such candidate is implemented here.
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

The immediate justified work remains transaction journaling and incremental
certificates, followed by a native backend and staged qualification. The present
benchmarks diagnose avoidable costs; they do not demonstrate that the current
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

### 2. Replace successful-update full snapshots with bounded mutation journals

Investigate an inverse-operation journal for local updates: record a prior value
before each mutation, commit only after repair and invariant checks, and unwind
in reverse order on failure. Preserve object identity. Journal sets, maps,
matching/partner views, index buckets, hierarchy metadata, graph edits, and
accounting—not just the live graph edge.

For phase transitions, build candidate replacement structures separately, verify
them, and publish at one commit point where the existing API permits it. Preserve
caller graph identity rather than swapping the caller's graph for a private copy.
Keep the existing snapshot path available as a differential reference while the
journal implementation is being certified. Ensure nested repair/chain/fan
transitions cannot commit independently of their enclosing update.

Acceptance tests must inject failures after each meaningful mutation stage,
including a phase rebuild and coloring/chain-flip failure. Compare graph contents,
object identities, matching views, indexes, hierarchy/coloring/fan state, and
counters with the pre-call state. Repeat a valid update after rollback to prove
the object is still usable. A failure in the rollback mechanism itself must be
explicit; never silently claim success on potentially corrupted state.

This is the largest likely ordinary-update opportunity based on the profile.
Measure journal size and transient memory, not just throughput, before accepting
it. Do not predict the speedup from profiled percentages alone.

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
matcher concurrently. The present single-owner engine is not established as
thread-safe. Incremental/background rebuilding requires explicit consistency,
query visibility, cancellation, and recovery contracts, with adversarial tests
around the publication boundary.

### 5. Scale at the appropriate boundary

For a service, serialize mutations per graph behind a bounded queue; define
admission control, cancellation-before-start, and explicit completion/error
responses. Do not acknowledge an update before its transaction commits. Keep
queries coherent with committed versions.

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
