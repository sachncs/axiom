# ADR 0053: Compact and reuse hierarchy level partitions

Date: 2026-10-03

## Context

Each recursive refinement copied every retained `A_levels` row into a Python
set, even though those prior level partitions are immutable during refinement.
The base hierarchy also copied System A/B/U into `A_levels[0]`, `N_levels[0]`
and `R_levels[0]`, and the finest R row copied finest U. Dense A-levels were
hash-based despite the indexed representation introduced for System partitions.

## Decision

- Reuse prior `A_levels` objects through a shallow list copy. The refinement
  reads those rows but does not mutate them; candidate rows are independently
  created and the System/hierarchy journals still retain their own root state.
- Store an A-level in `Vertices` when it has at least one quarter of the vertex
  universe; sparse level rows remain Python sets. Construct `A2` compactly when
  multiple dense upper levels contribute. `N_levels` retain their existing
  representation policy.
- Share initial `A_levels[0]`, `N_levels[0]`, and `R_levels[0]` with the base
  System's A/B/U. Share the finest N row with the finest System B, and the
  finest R row with finest U. `A1/N1/R1` continue to reference the appropriate
  hierarchy level roots.
- Admit exact `Vertices` rows in hierarchy transactions and validate their
  universe in constant time. Full hierarchy checks remain at build/refinement
  boundaries; partition objects are not edited during ordinary edge updates.

## Alternatives considered

- Copy every level to preserve isolated row identity: rejected because no
  refinement step mutates inherited rows; keeping these copies was pure retained
  memory overhead.
- Convert every level representation to `Vertices`: rejected because the
  universe-sized position array is wasteful for sparse rows and many levels.
- Remove the hierarchy compatibility fields: rejected; root sharing preserves
  the current fields while keeping their values coherent.

## Evidence

[`hierarchy-levels.json`](../../benchmarks/results/paper/hierarchy-levels.json)
records a 500,000-member dense partition in a one-million-label universe. The
old `set(Vertices)` refinement copy peaks at 35,224,208 traced bytes; carrying
the immutable root costs 64 bytes. Deterministic tests verify System/hierarchy
root sharing, dense/sparse A-level storage, single- and multi-source A2 values,
and complete `Hierarchy.check()` for both shapes. This is isolated partition
allocation evidence, not end-to-end Matcher memory or throughput qualification.

## Consequences

Recursive refinement avoids copying inherited A levels and redundant base or
finest partition roots. A2 still allocates when several upper partitions
contribute, N-level density remains unoptimized, and full hierarchy audits and
phase graph snapshots remain state-sized. Durable paper integration and
million/billion-vertex paper qualification remain open.
