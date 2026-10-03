# ADR 0045: Incremental paper hierarchy certificates

Date: 2026-10-03

## Context

Every successful multilevel Matcher update ended by running `Hierarchy.check()`
and comparing complete live and phase edge sets. The audit recomputed every
level's partition, matching degrees, Lambda/L rows, neighborhood bounds and
hierarchy indexes across the graph. A cProfile run of a seeded 8,192-vertex
trace attributed 3.23 seconds of 4.25 profiled seconds to `Hierarchy.check()`
alone. Disabling these checks would violate the paper-engine correctness
contract and ADR 0005.

## Decision

- Keep the complete `Hierarchy.check()` at construction and recursive rebuild
  boundaries, where a new hierarchy is admitted. Keep explicit full audits
  available to tests and callers.
- For incremental graph changes, certify the changed edge immediately in
  `Hierarchy.sync_graph()`: verify phase-edge presence, shared graph ownership,
  affected endpoints' exact System Lambda/L rows, neighborhood bounds on the
  finest/current level (the same scope as the full check), and hierarchy
  `L_levels` rows at every level. Static partitions and matching sets
  remain unchanged during `sync_graph`; full certificates cover them at rebuild.
- In the Matcher owner, replace full live/phase edge-set construction and
  subtraction with the inductive O(1) count equation
  `phase_edges = live_edges - inserted_edges + deferred_deletions`.
  `sync_graph` certifies each changed edge and owns the only in-phase phase-graph
  mutator. Full set equality is still checked by the complete rebuild audits.
- If the endpoint certificate or phase-edge count fails, raise inside the
  existing all-or-nothing transaction so graph, hierarchy caches, matching,
  and journals roll back together. A regression injects certificate failure
  and compares the entire Witness state before retry.

## Alternatives considered

- Keep full hierarchy audits after each update: rejected for normal path cost;
  the measured call scales with graph size instead of the update write set.
- Remove or sample all correctness checks: rejected. This implementation keeps
  local checks for every mutation and the complete independent rebuild audit.
- Trust only the edge-count equation: rejected because it cannot identify a
  wrong edge or stale endpoint cache; the changed edge's exact membership and
  all affected rows are checked locally.
- Retain exact full edge-set comparison on every update: rejected because it
  allocates and traverses O(m) Python edge tuples after a single mutation.

## Evidence

The comparison is archived in
[`hierarchy-certificates.json`](../../benchmarks/results/paper/hierarchy-certificates.json).
Baseline `764f652` and the candidate use the same 8,192-vertex sparse graph,
average-degree target four, multilevel mode, seed 42, and 128 real churn updates.
Both run one subphase rebuild and no full phase rebuild; final matching
certificate hashes and repair counters match.

Five timed batches improve from 19.70 to 148.65 updates/s (7.55×). One traced
memory pass falls from 4,648,872 to 2,391,072 transient bytes (48.56%). Peak RSS
falls from 109,756,416 to 102,498,304 bytes (6.61%) in one isolated sample.
The raw record includes benchmark/source SHA-256 hashes, all durations, the
machine, and limitations. This is one host, one trace and a small graph; it is
not million-vertex, durable, cross-host, or release qualification.

## Consequences

Ordinary multilevel updates certify graph-dependent invariants proportional to
the affected endpoint neighborhoods and hierarchy depth instead of scanning
all edges/vertices for the global audit. Full hierarchy audits remain at
construction and rebuild boundaries. Other costs still profile prominently,
including matching/auxiliary validation and cleanup; this ADR does not claim
constant-time or paper-theorem update complexity.
