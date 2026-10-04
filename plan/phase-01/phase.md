# Phase 01 — Paper-engine memory and update-cost hardening

**Roadmap coverage:** objective 1; blocking evidence for objectives 2–4 and 17.  
**Status:** In progress. The latest hosted 512 MiB Multilevel run fails while building the startup matching; Basic passes startup and sustained updates but fails a recovery replay under the same cap.

## Goal

Make Basic and Multilevel update/rebuild paths bounded in memory and work at the documented million-vertex operating point, preserving deterministic results and exact rollback.

## Work

- Trace and remove graph-sized duplicate roots and avoidable allocations at initialization, rebuild boundaries, recovery, and batch rollback.
- Reduce `System.index()` and matching construction peaks; record actual RSS, Python allocation, graph/cache sizes, and stage timings separately.
- Continue eliminating parent-boundary rebases, detached child Systems, multi-source hierarchy construction overhead, fan/pruning snapshots, and unnecessary global audits.
- Set and document per-operation complexity/allocation budgets for insert, delete, batch, rebuild, rollback, and recovery.
- Keep journals, invariants, determinism, high-degree behavior, and fail-stop semantics intact.

## Exit evidence

- Repeated Linux runs for both modes at 1M vertices, average degree 4, under the declared address-space cap complete startup, updates, backup, pressure phases, and recovery.
- Adversarial high-degree and hierarchy-boundary tests prove exact state restoration after injected failures.
- Retained reports include stage RSS/peak allocation and repeatability distributions; no unexplained state-sized copies remain in profiled hot paths.

## Dependencies

Foundational. Must precede final paper-mode performance and deployment qualification (phases 02–04 and 13).
