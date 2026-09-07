# Axiom Documentation

Axiom is a pure-Python reproduction of *A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching* by Chuzhoy, Khanna, and Song (STOC 2026, [arXiv:2605.00797v1](https://arxiv.org/abs/2605.00797v1)).

## Contents

- **[Getting started](getting-started.md)** &mdash; install Axiom and run your first maximal matching.
- **[Architecture](architecture.md)** &mdash; module boundaries, data flow, and state ownership.
- **[Modes](modes.md)** &mdash; the `basic` (single-level) and `tiered` (multi-level) operating modes.
- **[API](api.md)** &mdash; the public surface, organised by category.
- **[FAQ](faq.md)** &mdash; common questions about installation, modes, and limitations.
- **[Paper restatement](paper_restatement.md)** &mdash; the paper's notation, invariants, and known-deferred mechanics.

## Modules

Axiom is split into single-responsibility modules, each with a clear
purpose:

- `axiom.core` &mdash; `Matcher`, the orchestrator (graph, matching, z-system, augment, rebuild dispatch).
- `axiom.graph` &mdash; `Adjacency`: dynamic undirected graph.
- `axiom.system` &mdash; `System`: the single-level z-subgraph system plus `build`, `promote`, `switch`.
- `axiom.hierarchy` &mdash; `Hierarchy`: the k-level system plus `build_hierarchy`, `check_i3`, `maintain_i3`.
- `axiom.color` &mdash; `Colorer` Protocol, `Greedy`, `Vizing`, and alternating-path helpers.
- `axiom.matching` &mdash; `greedy`, `partner`, `partners`, `canonical`.
- `axiom.repair` &mdash; `Repair`: local insertion/deletion handler.
- `axiom.rebuild` &mdash; `Rebuild` Protocol, `Basic`, `Tiered`.
- `axiom.augment` &mdash; alternating-path search over a matching.
- `axiom.ledger` &mdash; `Ledger`: explicit counters for amortised-cost diagnostics.
- `axiom.invariant` &mdash; invariant checkers.
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