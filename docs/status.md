# Current implementation and qualification status

Updated 2026-10-03. This page describes current components; historical experiment
sections retain their source/workload provenance and do not override this status.

| Path | Use | Durability and concurrency |
| --- | --- | --- |
| `Service` → `Durable` → native `Engine` | Local production engineering | FULL-WAL commit before acknowledgment; thread-safe clients, one mutation owner |
| Native `Engine` alone | In-memory deterministic maximal matching | Owner-bound, bounded rollback; no persistence on its own |
| `Matcher(mode="basic" or "multilevel")` | Paper/research implementation | Nondurable, externally serialized; snapshot migration active |

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
| Linux changing-density hard-resource drill | Not a rate test | 1.04m real changes, actual memory/disk exhaustion, compact backup restore under unchanged caps |

[Raw full-ring](../benchmarks/results/independent/candidate-soak-sweep-million.json),
[growth/drain](../benchmarks/results/independent/pulse-long-million.json),
[hub](../benchmarks/results/independent/hub-steady-million.json),
[burst](../benchmarks/results/independent/burst-million.json),
[Linux recovery](../benchmarks/results/resource-growth-envelope.json).
These use declared source/wheel/runner hashes and machine/storage stacks. Producer
misses, IPC drops and Busy rejections do not count as real acknowledged changes.
Native byte caps do not bound total RSS/page cache or all filesystem companions.
Default macOS growth/drain reached 913 MB RSS; the explicitly selected allocator
profile reduced measured peaks to about 208 MB. It is not a portable quota.
Degree-64 throughput measured 6,640/s and fails the target for that denser envelope.

## Active scope

1. Broader repeated skew/arrival qualification on fresh installed-wheel runs,
   with exact-prefix queries, independent recovery and all losses retained.
2. Replace successful paper-engine whole-state snapshots with validated mutation
   journals, preserving graph/object identity, coloring/fans/hierarchy, accounting
   and exact failure rollback. Do not call partial migration complete.
   Integrate basic/multilevel through the durable production service with explicit
   algorithm selection and persisted identity. The user requires this on 2026-10-03;
   it is no longer a permanent nondurable research-only destination. Current
   persistence remains native-only until exact rollback/recovery tests pass.
3. Keep website, README, changelog, API guidance and decision records consistent
   with current implementation and measured boundaries.

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
886 passing tests; CI and benchmark results must be attributed to their exact
revision, not assumed to qualify every subsequent change.
