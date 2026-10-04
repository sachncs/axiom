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
respectively. This is a narrow one-batch smoke, not qualification. See the
[raw summary](../../benchmarks/results/repeatability/million-uniform-599.json).
