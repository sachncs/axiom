# ADR 0122: Measure Durable repeatability in fresh processes

- Status: implemented
- Date: 2026-10-04

## Context

The Durable benchmark emitted one-run diagnostics and left seed repetition to
manual commands. In-process repeats would share interpreter state and make
`ru_maxrss` cumulative, weakening run-to-run memory comparisons. The durable
workload already produces deterministic trace/matching digests and independently
checks topology, proper maximality, idempotent retry, and exact reopen recovery.

## Decision

Add a sequential repeatability runner that launches the existing Durable
benchmark in a fresh interpreter with a fresh SQLite database for every
mode/seed/repetition. Preserve every child JSON result and database. Refuse any
output collision before starting. Verify that equal seeds produce identical
trace and matching digests within each mode, and summarize median/minimum/
maximum for throughput, acknowledgment and commit quantiles, partner-query
quantiles, peak process RSS, and recovery time. Benchmark latency summaries
include p50/p95/p99 and p999 when the sample count supports p999.

## Consequences

- Repeatability and skew experiments are scripted instead of depending on
  manually coordinated processes and paths.
- Each RSS high-water mark belongs to a distinct child process; samples still
  share one host and are run sequentially to avoid concurrent CPU contention.
- Raw DBs and JSON are intentionally retained, so large matrices need explicit
  disk-space planning and fresh output directories.
- The runner reports observed spread only. It does not set performance gates,
  calculate confidence intervals, or establish overload/power-loss/deployment
  qualification.

## Verification

Tests execute both modes with two seeds and two fresh-process repeats, verify
same-seed digests and different-seed traces, inspect retained raw/database
outputs, and exercise output collision, malformed child output, and child
failure behavior. A separate benchmark test drives 1,024 acknowledgments and
checks p50/p95/p99/p999 ordering. An initial one-million-vertex average-degree-
four run repeated seed 599 twice per mode; all four independent audits/recovery
checks passed and both modes reproduced exact digests. Rates were 2,270/s Basic
and 7,507/s Multilevel; per-mode throughput spread was about 0.4% and 2.8%,
respectively. A second two-repeat million-vertex run with a degree-4,096 hot
hub measured 2,152/s Basic and 3,327/s Multilevel; exact digests/recovery again
passed. Both are one-seed, one-batch diagnostics, not qualification. See the
[uniform result](../../benchmarks/results/repeatability/million-uniform-599.json)
and [skew result](../../benchmarks/results/repeatability/million-hub4096-599.json).

## Power-law endpoint stress

The durable trace runner now also supports `power-law-churn`: it creates a
bounded pool of unique non-ring chords from independent integer ranks sampled
from a fixed, truncated Pareto tail (exponent 2.5), preloads half, and alternates
deletions/insertions by seeded pool index. Every run reports the exponent,
rank convention, hottest-vertex incidence and top-decile endpoint share; the
existing independent topology/maximality checks, durable retry, reopen replay,
matching digest, and fresh-process same-seed digest comparison still apply.

A one-million-vertex, two-million-edge run used 128 churn pairs, batch limit
256, seeds 599/601, two fresh-process repeats per seed and mode (eight samples).
All eight independent audits, durable retry checks, exact reopen recoveries and
same-seed trace/matching digest comparisons passed. Endpoint incidence was
extremely concentrated: the hottest vertex received 15,870–15,871 of 32,768
generated endpoint incidences and the top decile received all incidences. Median
throughput was 2,145/s Basic (2,101–2,174/s) and 2,209/s Multilevel
(2,116–2,219/s). Median acknowledgment p99 was 117.5 ms Basic and 113.9 ms
Multilevel; median recovery was 17.0 s and 24.9 s, respectively. Median process
peak RSS was 1.55 GB Basic and 2.39 GB Multilevel. These are single-host,
small-update-count stress diagnostics, not a broad power-law graph suite,
10k/s qualification, or deployment qualification. The retained summary and all
eight sample JSON files are in
[`million-powerlaw-599-601`](../../benchmarks/results/repeatability/million-powerlaw-599-601/summary.json).

## Deterministic hotspot-burst extension

The durable workload matrix now includes `power-law-burst-churn`. It preserves
the seeded Pareto-ranked edge pool and exact recovery checks, while selecting
from the one-percent churn-cell pool with the highest combined endpoint
incidence for 12 of every 16 edge-toggle pairs; ties are resolved by cell index.
The remaining four pairs sample the full pool. This creates repeatable temporal
concentration and repeated toggling of the same small set of high-incidence
edges. The trace records the schedule and pool size in workload metadata, so
repeated runs verify both workload identity and state digests.

Small fresh-process tests exercise this schedule in both paper modes and verify
the independent graph/maximality certificate and exact recovery. This adds
adversarial schedule coverage, not queue-overload, sustained duration, large-
scale performance, or deployment qualification. Those require separately
bounded offered-load and long-duration experiments.
