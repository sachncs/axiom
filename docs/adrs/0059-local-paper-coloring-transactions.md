# ADR 0059: Apply paper coloring changes through local transactions

Date: 2026-10-03  
State: Implemented; broader paper-engine qualification remains open

## Context

Vizing activation and fan-prefix rotation changed a small set of edge colors but
rebuilt all coloring indexes and repeatedly audited the full partial coloring.
Paper completion also audited after every newly colored edge. This made work
scale with the entire graph for operations whose mutation footprint is bounded
by one alternating path and fan. Removing those audits without replacement would
weaken failure detection and risk publishing stale endpoint indexes.

## Decision

`Partial.replace` performs an atomic color replacement for a bounded edge set. It
preflights graph membership, palette bounds, conflicts, and old index ownership;
updates assignment, incident-color, and edge-by-color indexes locally; and
certifies every touched edge and endpoint against the graph. If local
certification fails, it restores the exact pre-call assignment and index state.
Vizing activation and prefix rotation use this transaction. Batched completion
retains the local certificate on each mutation and runs the independent complete
coloring audit once at the phase boundary. Non-batched Vizing calls retain the
full audit. Fan pruning keeps its full compatibility and coloring audits at the
end of the operation, rather than after every intermediate fan mutation.

## Guarantees and limits

This changes the cost of the coloring mutation/certificate from whole-state
reindexing to the touched path/fan plus their incident rows. It does not claim
that every high-level paper phase is local: `Construction.small` still has
state-sized fan bookkeeping, and paper hierarchy snapshot migration, durable
integration, and broader adversarial qualification remain active. The
independent full coloring/fan audits remain in place at operation or phase
boundaries. The production native matcher and its throughput evidence are
unrelated to this paper-engine change.

## Evidence

- A deterministic 256-vertex degree-four hierarchy-build profile decreased from
  3.1 million calls / 0.530 s to 619 thousand calls / 0.119 s after local color
  updates and removal of repeated whole-coloring audits. These are profiler
  diagnostics, not a stable throughput claim.
- At 1,024 vertices, a subsequent profile measured 0.639 s versus 1.149 s in the
  prior profile after eliminating repeated full fan audits. The fan-repair scan
  remained a dominant cost.
- A deterministic 8,192-vertex degree-four ring hierarchy built in 24.90 s and
  passed `hierarchy.check()`; the independent hierarchy audit took 0.94 s. This
  is a correctness/scale probe, not an accepted latency target.
- Regression tests cover multiple fan collisions, chain flips, complete proper
  colorings, fan compatibility, local color-cycle replacement, injected local
  certificate failure with exact rollback, and failed routing rollback.

## Alternatives

- Keep `reindex()` and all full audits after every edit: simplest, but repeatedly
  scans unrelated state.
- Remove validation and trust mutation code: faster but loses immediate local
  failure detection and makes stale indexes harder to contain.
- Maintain only periodic global audits: insufficient for atomic operation
  guarantees; rejected.

## Follow-up

Run repeated unprofiled workloads across sizes and adversarial fan shapes, retain
raw inputs/results, and profile fan-repair candidate selection. Keep full audits
as independent oracles. Do not generalize this paper-engine measurement to the
durable production service or to billion-vertex support.
