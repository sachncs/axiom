# Axiom Documentation

Axiom has a native SQLite-backed local matching service and separate Python
paper/research modes. Start with [current status](status.md): implementation,
measured evidence, active repeatability/skew and paper-engine integration, and explicitly
deferred work. The production engine does not inherit the paper theorem.

## Contents

- [Brand assets](brand.md): logo, favicon, palette and verified product walkthrough.

- **[Current status](status.md)** — authoritative current scope and evidence.
- **[Build and CI](ci.md)** — Astro-only publishing and package/resource gates.
- **[Service](service.md)** — thread-safe bounded admission, receipts and queries.
- **[Durability](durable.md)** — SQLite authority, checkpoints, retries and backups.
- **[Native engine](engine.md)** and **[storage](storage.md)** — compact compute state and budgets.
- **[Engineering](engineering.md)**, **[operations](operations.md)** and **[ADRs](adrs/README.md)** — qualification, migration rationale and deferrals.

- **[Getting started](getting-started.md)** &mdash; install Axiom and run your first maximal matching.
- **[Architecture](architecture.md)** &mdash; module boundaries, data flow, and state ownership.
- **[Modes](modes.md)** &mdash; the `basic` (single-level) and `multilevel` (recursive multi-level) operating modes.
- **[API](api.md)** &mdash; the public surface, organised by category.
- **[FAQ](faq.md)** &mdash; common questions about installation, modes, and limitations.
- **[Paper restatement](paper_restatement.md)** &mdash; the paper's notation, invariants, and known-deferred mechanics.

## Modules

Axiom is split into single-responsibility modules, each with a clear
purpose:

- `axiom.service` — concurrent clients and bounded single-owner scheduling.
- `axiom.durable` — FULL-WAL commits, exact recovery and checkpoint/history policy.
- `axiom.engine` / `axiom.native` — compact incremental matching and storage.
- `axiom.backup` — private compaction and immutable no-overwrite publication.

- `axiom.core` &mdash; `Matcher`, the orchestrator (graph, matching, z-system, augment, rebuild dispatch).
- `axiom.graph` &mdash; `Adjacency`: dynamic undirected graph.
- `axiom.system` &mdash; `System`: the single-level z-subgraph system plus `build`, `promote`, `switch`.
- `axiom.hierarchy` &mdash; `Hierarchy`: the k-level system plus `build_hierarchy`, `check_i3`, `maintain_i3`.
- `axiom.color` &mdash; `Colorer` Protocol, `Greedy`, `Vizing`, and alternating-path helpers.
- `axiom.matching` &mdash; `greedy`, `partner`, `partners`, `canonical`.
- `axiom.core` &mdash; `Matcher`: insertion/deletion local handling and rematch dispatch (private `__handle_insertion`, `__handle_deletion`, `__rematch_*`).
- `axiom.rebuild` &mdash; internal `Basic` and `Multilevel` rebuild strategies.
- `axiom.augment` &mdash; alternating-path search over a matching.
- `axiom.ledger` &mdash; `Ledger`: explicit counters for amortised-cost diagnostics.
- `axiom.simulation` &mdash; `random_updates`, `replay`, `Update`.
- `axiom.parallel` &mdash; `Benchmark`, `worker`, `run_parallel`, `compare`.
- `axiom.visualize` &mdash; `visualize_system`, `visualize_matching`, `visualize_adjacency`.
- `axiom.types` &mdash; type aliases and protocols.
- `axiom.cli` &mdash; command-line entry point.

## Citation

```
Chuzhoy, J., Khanna, S., Song, J. (2026).
A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching.
arXiv:2605.00797v1.
```
