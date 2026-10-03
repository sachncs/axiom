# 17-point product objective: status and proof gates

Updated 2026-10-04. This is the active user-provided product scope, not a claim
that the work is complete. “Partial” means only the cited evidence exists; each
item needs its own release gate. Native-engine evidence never qualifies a paper
mode. The hardware power-loss test remains explicitly deferred for this version.

| # | Requirement | Current status | What remains before calling it done |
| ---: | --- | --- | --- |
| 1 | Paper-engine performance hardening | **Partial** — recursive `deepcopy` is gone; graph, coloring, fan and hierarchy journals/sparse paths exist. Recent fan-root and parent-boundary snapshot reductions are scoped changes. | Finish remaining graph-sized snapshots/rebases, detached child Systems, multi-source hierarchy construction and hot-path global work; publish repeated time/allocation/RSS budgets without weakening rollback or audits. See [paper state](paper-state.md). |
| 2 | Durable `native`, `basic` and `multilevel` production modes | **Not implemented** — `Service`/`Durable` persist only the native engine; paper modes remain nondurable and externally serialized. | Mode-specific journals/codecs, persisted identity/configuration, exact hierarchy/color/fan recovery, incompatible/corrupt-state refusal, and independent installed/recovery/overload qualification. See [ADR 0023](adrs/0023-durable-paper-integration.md). |
| 3 | Repeatability, skew and adversarial qualification | **Partial** — repeated deterministic paper hot-hub traces and four 1M-vertex power-law source-checkout samples now exist; exact final recovery passed. 10k offers delivered 9.54k/s; 12k offers delivered 11.15k/s in short runs. | Fresh installed-wheel repeats, longer duration, exact per-version query replay, uniform/power-law/hub and insert/delete/churn matrix, repair cascades, overload boundaries, restart loops and resource characterization. See [recorded power-law evidence](../benchmarks/results/overload/power-law-million.json). |
| 4 | Native Service deployment qualification | **Partial** — scoped 30-minute, recovery and hard-resource evidence plus operating guidance exist. | Broader sustained skew/burst repeatability, disk/page-cache/WAL quota guidance, corruption/error drills, alert thresholds, sizing, idempotency and service-ready deployment examples. Hardware power-loss remains deferred. See [operations](operations.md). |
| 5 | Arbitrary durable external IDs | **Not implemented** — public graph APIs use dense integer labels. | Stable string/UUID/database-key codec and mapping persistence, no-reuse lifecycle, efficient lookup, migration and crash/rollback tests. |
| 6 | Dynamic vertex lifecycle | **Not implemented** — graph universe is fixed at construction. | Atomic add/remove vertex semantics, incident-edge/match cleanup, durable recovery, ID lifecycle, and coherent concurrent-read behavior. |
| 7 | Atomic batch updates | **Implemented in the local native Service API; qualification pending.** `submit_batch()` enforces bounded contiguous sequences and one `Durable.apply` transaction, with exact retry rules and rollback/reopen tests. | Hosted CI/release execution and service-shaped throughput/latency/resource qualification. It does not batch paper modes. See [service contract](service.md#atomic-explicit-batches). |
| 8 | Atomic multi-query read snapshots | **Not implemented** — individual reads expose committed versions; combining calls is not a snapshot. | Bounded snapshot lifetime/retention, one-version topology and matching reads, and mutation/concurrency semantics. |
| 9 | First-class bipartite API | **Not implemented.** | Left/right partitions, same-side edge rejection, external IDs and production durability/API tests. |
| 10 | Event/change subscriptions | **Not implemented.** | Versioned deterministic events, delivery/duplicate semantics, bounded subscriber queues and lag/backpressure tests. |
| 11 | Supported observability surface | **Partial** — `Service.metrics()` exposes bounded admission/group counters; benchmark outputs provide latency histograms. | Stable metrics/exporter contract covering rates, queries, commit/update percentiles, graph/mode state, storage, recovery, errors and subscriber lag; structured logs/alerts and bounded overhead. |
| 12 | Deterministic replay and historical debugging | **Partial** — durable operation history/checkpoints, checksums and exact recovery/retry exist. | Public mutation-log export/replay/hash verification and configurable version checkpoints; bounded historical queries where practical. |
| 13 | Match explanations | **Not implemented.** | Version-linked previous/current partner, trigger and truthful algorithm repair evidence for each mode. |
| 14 | Reproducible cross-platform packaging | **Partial** — CI and tag-release workflows now define/test 20 CPython 3.10–3.13 wheels across Linux x86_64/ARM64, macOS x86_64/ARM64 and Windows x86_64; hosted matrix has not yet run on this change. | Hosted CI/tag evidence, Windows ARM64/musllinux decision, reproducible native wheel builds, ABI policy, container and readiness examples, and PyPI trusted-publishing configuration verification. See [CI contract](ci.md). |
| 15 | Stable network transport | **Not implemented** — Service is local/threaded, not an HTTP/gRPC server. | Transport authentication integration, bounded payloads, idempotency/retry/version/backpressure semantics and end-to-end qualification. |
| 16 | Weighted/maximum/constrained/capacity matching | **Explicitly separate future engines**, not an extension of current maximal-matching semantics. | Define independent algorithms, contracts, complexity and release gates only when that future scope is selected. |
| 17 | Qualification/release gates | **Partial** — research, durability, performance and deployment gates are documented, but no per-paper-mode gate passes. | Tie each feature/mode to machine-verifiable gates and publish status only from actual evidence; keep deferred hardware power-loss and unsupported scale visible. See [engineering assessment](engineering.md) and [ADRs](adrs/README.md). |

## Current interpretation

The work is not complete. The newly implemented batch API, cross-platform
workflow and short power-law samples advance items 7, 14 and 3, respectively;
they do not close adjacent requirements. In particular, basic/multilevel are
not durable, arbitrary IDs and dynamic vertices are absent, and the paper engine
is not a production-qualified billion-node system. See [current measured status](status.md)
for the native operating envelope and historical evidence boundaries.
