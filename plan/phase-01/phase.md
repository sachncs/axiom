# Phase 01 — Paper-engine memory and update-cost hardening

**Roadmap coverage:** objective 1; blocking evidence for objectives 2–4 and 17.  
**Status:** Qualification complete. Two Linux ARM64 runs per mode complete the one-million-update cycle, backup, memory and disk pressure phases, and exact fresh-process recovery under the 512 MiB address-space cap. Repeated runs exceed the existing 10,000 durable updates/s target for both modes.

**Local progress (2026-10-04):** Large all-U `Packed` Systems now read Lambda
neighbors directly from the graph, and Multilevel immutable phase-base Systems
omit duplicate cache rows. Multilevel incidence buckets use compact tuples at
low degree and promote for high degree; cumulative incidence counts use a
four-byte-per-vertex array with journaled cell rollback and phase-root swaps.
The resource harness verifies full backup recovery in a fresh subprocess under
the inherited cap after pressure drills. Three Linux ARM64 startup/rebuild
profiles and two full resource runs per mode are retained. Native class-root
admission and packed-graph certificates reduce Python overhead in the hot
update path. A dense `Vertices.copy()` no longer allocates an empty
state-sized table before copying its contents; this addressed Multilevel
recovery under disk pressure. Instrumented profiles remain diagnostic and are
not throughput measurements. The call table is retained in
[`update-costs-native-isolation-macos-2026-10-04.json`](../../benchmarks/results/paper/update-costs-native-isolation-macos-2026-10-04.json).

Raw 4,096-request repeatability reports are retained in
[`million-batch4096-macos`](../../benchmarks/results/repeatability/million-batch4096-macos/summary.json);
updated traced startup stage profiles are summarized in
[`memory-profile-macos-2026-10-04-summary.json`](../../benchmarks/results/paper/memory-profile-macos-2026-10-04-summary.json).
Linux ARM64 startup allocations/timings are summarized in
[`paper/linux-arm64-2026-10-04/summary.json`](../../benchmarks/results/paper/linux-arm64-2026-10-04/summary.json),
and constrained resource repeats are summarized in
[`resource-envelope-linux-arm64-local/summary.json`](../../benchmarks/results/resource-envelope-linux-arm64-local/summary.json).

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
- Both modes sustain at least the existing 10,000 real durable updates/s target at the million-vertex degree-four operating point without bypassing durability, queries, or invariants.

## Dependencies

Foundational. Must precede final paper-mode performance and deployment qualification (phases 02–04 and 13).
