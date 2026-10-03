# ADR 0067: Reuse detached roots during child hierarchy refinement

Date: 2026-10-03  
State: Implemented; full child-rebuild qualification remains open

## Context

A multilevel child rebuild correctly detached the retained phase-base System
for mutation. It then copied that working System's A, B and U partitions a
second time into the initial `Hierarchy` roots, copied its L-cache mapping, and
indexed the detached System in `copy()` immediately before `refine_hierarchy()`
replaced those rows on its projected graph. It also cloned the immutable
phase-base graph, although refinement reads that source and constructs a
separate projected graph; it only rebinds the detached System objects.

## Decision

Keep the one detached working-System copy, but use its A/B/U roots directly as
the initial hierarchy A/N/R roots. Start the temporary hierarchy with no
derived L-level maps; each refinement constructs those maps from the resulting
graph and regions. Allow the System-copy helper to defer indexing for this
child path. Full rebuilds retain the default indexed copy because
`build_hierarchy` may return a one-level hierarchy without entering refinement.

Use the retained phase-base graph directly as the refinement source when every
deleted edge is present. `refine_hierarchy` reads this graph and emits a new
projected graph; it does not mutate the source graph. Keep the existing copied
and restored path as a fallback if any deleted edge is absent, preserving the
prior recovery behavior for that boundary case.

## Correctness and ownership

The phase-base System remains independent: the existing copy still clones its
partitions and matching before any graph/cache mutation. Within the child
candidate, the hierarchy roots alias only that detached copy. Refinement
replaces graph-dependent caches before returning; complete `Hierarchy.check()`
and the child rebuild's published certificate run afterward. An injected
coloring failure still rolls back the retained phase roots through the owner
journal. The normal-path regression proves no graph snapshot is taken and the
inherited graph contents remain unchanged. A complementary missing-deleted-edge
test proves the fallback still snapshots and restores the edge before
refinement. The deferred-index regression proves `System.index` is not called
before the first refinement.

## Evidence and limits

An isolated one-million-label probe uses compact A/B/U partitions with sizes
375,000 / 375,000 / 250,000. Materializing the former extra roots as
`set(A)`, `set(B)` and `U.copy()` peaks at 65,547,224 traced bytes. Retaining
references to the already-detached working roots peaks at 80 bytes. This is
the avoidable second layer of roots only: the required detached System's
partition storage, matching, hierarchy refinement, and process RSS are
excluded. For the default million-vertex `Packed` ring, skipping the normal
child graph clone also avoids the 37,000,264-byte native capacity measured in
[ADR 0055](0055-share-hierarchy-phase-graph-root.md); that capacity result is
from an isolated graph-copy probe, not this complete child path. The combined
change has no end-to-end child-rebuild peak/RSS benchmark. See the
[partition-root probe](../benchmarks/results/paper/child-refinement-roots.json).

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
