# Measuring dynamic-update performance

The controlled harness answers insertion/deletion rates, mixed-update throughput,
individual call latency, rebuild boundaries, query costs, and memory usage. It
benchmarks the public `Matcher` API, including its transactional snapshots and
invariant checks. It does not disable safety checks to report a faster rate.

Install the measurement environment and optional chart dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,benchmark]'
.venv/bin/pytest -q tests/test_performance.py tests/test_performance_report.py
```

## Workloads and algorithms

`Shape` defines sparse, dense, star, or bipartite edge domains. `Workload` subclasses
prepare deterministic traces before timing, independently of the matching chosen
by an algorithm. `Engine` implementations replay those traces through basic or
multilevel Axiom, or recompute a greedy maximal matching after each real update.

| Workload | What the reported rate measures |
| --- | --- |
| growth | Real insertions of absent edges; stops at domain capacity |
| drain | Real deletions of present edges; stops when empty |
| churn | Alternating deletion/insertion, retaining density after each pair |
| burst | Alternating batches of sixteen deletions and insertions |
| hotspot | Churn concentrated at vertex zero when possible |
| duplicate | Duplicate insert calls, **not** successful updates |
| absent | Absent-edge delete calls, **not** successful updates |

Initial edges target average degree 4 or 16 for sparse graphs, `n/2` for dense
graphs, 2 for stars, and 16 for bipartite graphs. Every initial graph is capped at
half its domain capacity, reserving space for insertions. The actual initial edge
count and maximum degree are recorded; degree target is not maximum degree.
Hotspot generation falls back to another valid edge when its local domain is
full, or has no edge available to delete.

## Reproduce the pilot and longer measurements

```sh
.venv/bin/python benchmarks/performance.py \
  --output benchmarks/results/pilot --updates 32 --timeout 8

.venv/bin/python benchmarks/performance.py \
  --output benchmarks/results/tails --sizes 32 --profiles sparse4 \
  --workloads churn --updates 8192 --timeout 180

.venv/bin/python benchmarks/performance.py \
  --output benchmarks/results/phases --sizes 128 --profiles sparse4 \
  --workloads churn --updates 2048 --timeout 120

.venv/bin/python benchmarks/performance.py \
  --output benchmarks/results/expansion --sizes 2048 --profiles sparse4 \
  --workloads growth drain churn --updates 32 --timeout 20

.venv/bin/python benchmarks/report.py \
  benchmarks/results/pilot benchmarks/results/tails \
  benchmarks/results/phases benchmarks/results/expansion \
  --output benchmarks/results/report
```

Cases run **sequentially**, each in an isolated process. Do not run different
suites concurrently or run CPU-heavy jobs during measurements. Each case starts
with one warmup, then five fresh-state throughput repetitions. Three seeds are
used by default. `--timeout` bounds an entire case, not one operation, and
includes all measurement passes. A large or expensive configuration can therefore
time out during traced memory measurement even if its throughput pass finished.
Timeouts and correctness failures are retained, not assigned zero throughput.

The short pilot is a coverage/calibration sweep, not a dependable tail estimate.
The longer 32-vertex traces supply at least 10,000 pooled samples per operation
across three seeds if all cases complete. Longer 128-vertex traces cross multiple
phase boundaries. The 2,048-vertex sweep deliberately measures short batches and
does not establish steady-state rebuild costs at that size. Increase lengths and
case limits for deployment-specific experiments.

## Measurement boundaries

Graph materialization and trace generation happen outside update timers. Matcher
initialization is measured separately. Batch throughput has no per-call timers
or counter reads. A separate latency pass times each public call, then correlates
counter deltas with phase/subphase rebuilds and scan counts. Matched/unmatched
deletions are classified against the pre-call matching, not by modifying traces
for a particular algorithm. Query timings use the resulting graph, separately
from updates.

Memory is measured in another fresh-state pass using `tracemalloc`; construction
peak and update peak are recorded separately. RSS is the isolated process's
lifetime high-water mark, including imports and earlier measurement passes.
It is not current graph-only memory.

Each pass checks the expected final graph and a proper maximal matching. Repeated
passes of one algorithm must produce the same final matching. Algorithms must
replay identical trace digests, but need not choose the same maximal matching.
The greedy baseline lacks Axiom's rollback and hierarchy guarantees; its speed
is useful context, not an equivalent feature comparison.

## Artifacts and interpretation

Each run directory contains:

- `metadata.json`: commit, dirty status, source hashes, Python, hardware, clock,
  seed/configuration choices, and start time.
- `results.jsonl`: every case, its status, raw batch durations and latency samples,
  query quantiles, counters, memory, and matching certificate.
- `summary.csv`: per-case throughput and graph statistics, including failures.
- `latency.csv`: individual calls, real/no-op status, matched status, boundary,
  and rematching scan deltas.

Published baseline directories are versioned. Choose fresh output directories
for new experiments: the harness replaces files in the selected output directory.
Local calibration and interrupted scratch runs are not part of the published data.

The report writes `aggregate.csv`, `report.md`, and three PNG charts. Rates are
median seed-specific batch rates; seed min–max is observed variation, not a
confidence interval. Latency uses nearest-rank empirical quantiles. Report p99
with its sample count: short traces cannot establish a reliable tail bound.
Raw JSON timing summaries and individual samples use nanoseconds; the aggregate
CSV's insertion/deletion latency quantiles use milliseconds, and counts are
unitless. Throughput columns use calls per second.
No-op rates are separate from real-update rates. Growth and drain change density,
so their finite-batch rates should not be described as steady-state throughput.

Reproduce on the same Python version and hardware before drawing comparisons.
On a developer workstation, thermal state, background processes, and CPU
frequency are not controlled. These results do not establish asymptotic bounds.

For separate function profiling and a prioritized optimization plan that
preserves rollback guarantees, see the [engineering assessment](engineering.md).

## Durable hot-hub profile

`benchmarks/durable.py` also supports a deterministic `hub-churn` profile for
the paper-backed Durable path. It preloads spokes from vertex zero in bounded
durable groups, then churns a disjoint spoke pool at that same vertex while
retaining FULL-WAL commits, partner reads, independent final topology/maximality
checks, idempotent retry, and exact reopen verification. Preload time and count
are reported separately from measured churn. Use a fresh database for every
run, and repeat the same seed to compare trace/state digests and variance.

```sh
uv run python benchmarks/durable.py \
  --database /private/tmp/axiom-basic-hub-599.db \
  --vertices 1000000 --pairs 20000 --batch 256 --seed 599 \
  --mode basic --workload hub-churn --hub-degree 65536
```

Repeat with another fresh path for `--mode multilevel`, and with seeds 599, 600,
and 601 for repeatability. This profile isolates sustained hot-hub churn over a
preloaded hub; it does not exercise burst admission, concurrent network load,
hard quotas, or long-duration deployment behavior. Treat it as workload
qualification evidence only after publishing all raw runs and independently
reviewing throughput, tail latency, memory, SQLite growth, and recovery.
An initial two-repeat, one-million-vertex average-degree-four diagnostic is
recorded in the [repeatability result](../benchmarks/results/repeatability/million-uniform-599.json):
digests and exact recovery agree, but Basic measured about 2.27k updates/s and
Multilevel about 7.51k/s. It uses one seed and one 256-update batch per run, so
it is not broad or sustained qualification.
The same two-repeat matrix at a 4,096-degree hot hub measured about 2.15k/s
Basic and 3.33k/s Multilevel, with matching digests and exact recovery. That
moderate-skew trace is short and one-seed; it does not qualify the more extreme
65,536-degree hub or a production workload mix. See the
[hub repeatability result](../benchmarks/results/repeatability/million-hub4096-599.json).

After the large all-U Lambda cache change, two fresh-process one-million-vertex
startup and Durable recovery samples per mode are retained in the
[Phase 01 local diagnostic](../benchmarks/results/repeatability/million-implicit-all-u-macos/summary.json).
A separate two-repeat, 256-update run is in the
[longer trace](../benchmarks/results/repeatability/million-implicit-all-u-128-macos/summary.json):
Multilevel reached 11.31–11.42k/s and Basic 8.32–9.94k/s on this macOS host.
These short single-seed diagnostics verify exact replay and record resources;
they do not qualify the 512 MiB Linux pressure phases or a sustained workload.

For controlled fresh-process repeats, use `benchmarks/repeatability.py`. It runs
samples sequentially, gives every sample a separate database and interpreter,
stores each raw benchmark result, verifies exact trace/matching digests across
repeats of the same seed, and reports median/minimum/maximum throughput,
acknowledgment and commit quantiles, partner-query quantiles, peak RSS, and
recovery time. It refuses to overwrite existing result or database paths. Choose
an output directory with sufficient space: database images are retained for
inspection, and a million-vertex/high-skew matrix can take a long time.

```sh
uv run python benchmarks/repeatability.py \
  --output /private/tmp/axiom-repeats \
  --vertices 1000000 --pairs 128 --batch 256 \
  --seeds 599 600 --repeats 2 --mode both \
  --workload hub-churn --hub-degree 65536
```

Every child result independently audits topology, matching maximality, retries,
and exact recovery. The aggregate is descriptive—not a confidence interval, a
release threshold, or evidence for overload, power-loss, or deployment
qualification. The same-seed digest check detects nondeterminism; it does not
imply that different seeds must select different maximal matchings.
The current one-run-per-mode records are in the
[durable diagnostics](../benchmarks/results/durable/README.md). Both runs
recovered exactly after the former journal boundary, but neither approached
the earlier 100k updates/s aspiration. Bounded-slice operation-log replay later
reduced recovery on the same retained databases from 280 s to 47.6 s for Basic
and from 951 s to 152.8 s for Multilevel. These are single reopen timings, not
repeatability evidence; both recovery times remain substantial.

## Phase 01 resource and operation budgets

The latest startup trace is a three-repeat Linux ARM64 diagnostic at one
million vertices and two million edges, with `tracemalloc` enabled. Basic peak
RSS was 96.4–96.8 MB (Python peak 32.1 MB); Multilevel peak RSS was 102.1 MB
(Python peak 39.1 MB). System indexing remained below 0.2 ms in these samples;
matching construction took 9.15–9.28 s under tracing. The full constructor
rebuild took 28.1–28.2 s for Basic and 57.0–57.1 s for Multilevel. The one-
million-entry proper matching uses a four-byte partner array (4 MB payload),
while non-matching or overlapping edge sets retain the sparse-set fallback.
See the [Linux three-repeat profile](../benchmarks/results/paper/linux-arm64-2026-10-04/summary.json)
and per-stage JSONL records beside it. The earlier macOS profile remains in
the [macOS three-repeat profile](../benchmarks/results/paper/memory-profile-macos-2026-10-04-summary.json).

| Operation | Work bound | Additional retained or transient state |
| --- | --- | --- |
| Insert/delete | Endpoint graph operations plus paper repair, coloring, and hierarchy maintenance; worst case may scan a touched high-degree row | Four-byte matching partner entry per vertex when matching edges are disjoint; incidence counter array adds 4 bytes per vertex; deltas and undo scale with touched edges/endpoints |
| Batch of `k` updates | Sum of individual update work plus one batch publication/validation; Durable admission is capped at 256 in qualification | `O(k)` requests/receipts and journal before-images proportional to touched cells; no whole-Matcher snapshot |
| Rebuild | `O(n + m)` construction and certificates plus hierarchy refinement work | Packed graph storage plus mode state; all-U cache rows are implicit, Multilevel type-1 phase-base reads the stable graph through an overlay view |
| Rollback | Proportional to journaled mutations | Before-images proportional to touched cells; array counter cells and native graph changes use first-write journals; high-degree repair can enlarge the touched set |
| Recovery | Operation-log history times update cost, replayed in bounded batches | Reconstructs complete graph/paper state; does not retain all operation rows; final full-backup recovery is performed in a fresh process under the cap |

Multilevel phase incidence buckets use immutable tuples through degree four and
promote to sets for higher-degree rows. This avoids a mutable list allocation
and spare capacity for the common singleton endpoint while keeping lookup
proportional to the local row. Cumulative inserted-incidence counts use a
four-byte-per-vertex array (4 MB at one million vertices); an active update
journal stores only the first before-image of each touched counter. A clear at
a phase boundary records the original nonzero cells before zeroing them, so
rollback remains exact. These are retained-state bounds; Python dictionary
entries and journal cells still add workload-dependent overhead.

The update and batch rows are structural budgets, not universal byte limits;
high-degree rows and recursive rebuild boundaries dominate their transient
cost. Two Linux ARM64 one-million-update growth/drain runs per mode completed
startup, all updates, backup, memory-pressure rollback, disk-pressure recovery,
and exact fresh-process backup recovery at `RLIMIT_AS=512 MiB`. Basic measured
39.3–39.6k updates/s with 442.4–442.6 MB process peak RSS; Multilevel measured
20.2–20.3k/s with 454.0–454.2 MB peak RSS. All four runs produced the same
matching digest. Full results and repeat distributions are in the
[`resource-envelope-linux-arm64-local` report](../benchmarks/results/resource-envelope-linux-arm64-local/summary.json).
Both modes exceed the existing 10k/s durable-throughput target and pass the
memory/recovery gate. The 100k/s aspiration remains future optimization work,
not a Phase 01 acceptance criterion.
An instrumented 4,096-update Matcher profile points to a repeated class-root
admission scan as a major Basic-mode cost (about 10,000 class-root checks per
update in this trace, versus about 1,000 for Multilevel). Its timings are
instrumented diagnostics, not throughput evidence. See the
[profile call table](../benchmarks/results/paper/update-costs-macos-2026-10-04.json)
for the complete function breakdown.
