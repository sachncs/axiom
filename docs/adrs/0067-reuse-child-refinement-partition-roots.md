# ADR 0067: Reuse detached roots during child hierarchy refinement

Date: 2026-10-03  
State: Implemented; full child-rebuild qualification remains open

## Context

A multilevel child rebuild correctly detached the retained phase-base System
for mutation. It then copied that working System's A, B and U partitions a
second time into the initial `Hierarchy` roots, and copied its L-cache mapping.
It also indexed the detached System in `copy()` immediately before
`refine_hierarchy()` replaced those cache rows by indexing the same level on
its new working graph. None of those initial hierarchy roots or cache rows is
read by refinement before it replaces them.

## Decision

Keep the one detached working-System copy, but use its A/B/U roots directly as
the initial hierarchy A/N/R roots. Start the temporary hierarchy with no
derived L-level maps; each refinement constructs those maps from the resulting
graph and regions. Allow the System-copy helper to defer indexing for this
child path. Full rebuilds retain the default indexed copy because
`build_hierarchy` may return a one-level hierarchy without entering refinement.

## Correctness and ownership

The phase-base System remains independent: the existing copy still clones its
partitions and matching before any graph/cache mutation. Within the child
candidate, the hierarchy roots alias only that detached copy. Refinement
replaces graph-dependent caches before returning; complete `Hierarchy.check()`
and the child rebuild's published certificate run afterward. An injected
coloring failure still rolls back the retained phase roots through the owner
journal. The regression checks exact root identity and proves deferred copy
does not call `System.index` before the first refinement.

## Evidence and limits

An isolated one-million-label probe uses compact A/B/U partitions with sizes
375,000 / 375,000 / 250,000. Materializing the former extra roots as
`set(A)`, `set(B)` and `U.copy()` peaks at 65,547,224 traced bytes. Retaining
references to the already-detached working roots peaks at 80 bytes. This is
the avoidable second layer of roots only: the required detached System's
partition storage, matching, graph snapshot, hierarchy refinement, and
process RSS are excluded. The measurement is not an end-to-end child rebuild
result. See the [raw probe](../benchmarks/results/paper/child-refinement-roots.json).

## Alternatives

- Share the phase-base roots directly: rejected because later refinement and
  updates would couple retained parent state to the mutable child hierarchy.
- Keep duplicate hierarchy roots as defensive copies: rejected because they
  are not mutated independently before refinement replaces/retains the
  detached System partitions.
- Remove cache construction from all copies: rejected because a one-level
  full rebuild can publish without a refinement pass; that caller still
  requires indexed state.

## Follow-up

Measure complete child rebuilds at dense and sparse partition shapes, including
process RSS and repeated phase transitions. The detached graph/System copy and
other state-sized snapshots remain active migration work.
