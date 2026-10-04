# Phase 03 — Repeatability, skew, and adversarial qualification

**Roadmap coverage:** objective 3.  
**Status:** Partial evidence exists; broad matrix and reproducibility gates are open.

## Goal

Establish repeatable algorithm and service evidence across realistic and hostile graph/update distributions for each mode independently.

## Work

- Cover empty-to-growing graphs, large preloads, uniform and power-law degree distributions, hubs, insert-heavy, delete-heavy, balanced churn, bursts, repeated edge toggles, and adversarial repair cascades.
- Exercise phase/hierarchy boundaries, fan/pruning cases, queue saturation, overload rejection, restart during mutation, crash/recovery loops, and sustained duration.
- Repeat identical seeded workloads in fresh processes and compare graph, matching, and durable-state hashes.
- Record throughput and p50/p95/p99/p999 update and commit latency, query latency, rejection rate, queue depth, memory, SQLite/WAL size, recovery time, rollback/audit failures, and matching size.
- Publish separate correctness, durability, performance, and deployment conclusions; never transfer evidence between modes.

## Exit evidence

- Version-controlled workload matrix and deterministic generators with tests for their distributions and expected edge counts.
- Multiple independent repeats per mode with variance bounds and retained machine-readable results.
- All hostile cases preserve maximality, durability, and exact recovery or fail closed with classified errors.

## Dependencies

Phases 01–02; batch/overload semantics from phase 07.
