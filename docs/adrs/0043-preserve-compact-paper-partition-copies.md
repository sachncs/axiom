# ADR 0043: Preserve compact partitions in paper snapshots

Date: 2026-10-03

## Context

ADR 0041 introduced `Vertices` for sufficiently dense `System.U`, but snapshot
helpers immediately used `set(system.U)`, expanding the compact partition into
boxed Python integers and a hash table. The multilevel builder repeated this
for hierarchy `R` regions, including a second expansion while refining the
next level. This erased much of the storage improvement at exactly the
phase/rebuild boundaries where transient peak memory matters.

## Decision

- `Vertices.copy()` returns an independent `Vertices` and clones the packed
  position/member arrays directly, preserving membership and iteration order.
- Rebuild snapshots use the partition's own `copy()` behavior. Plain sets
  continue to copy as plain sets.
- Hierarchy `R1` and `R_levels` may retain `Vertices`; `A` and `N` partitions
  remain plain sets. Refinement clones old/new U with the compact copy method,
  uses set-like membership/add/discard, and avoids an extra `all_u` set.
- Hierarchy transaction admission and its invariant/index code explicitly
  accept compact values only at the R-region slots.

## Alternatives considered

- Expand to sets at snapshot boundaries: rejected because a compact persistent
  representation would still cause set-sized transient peaks on phase rebuilds.
- Convert all hierarchy partitions: rejected for this change because `A/N`
  consumers have wider set-algebra and transaction contracts; they require a
  separate compatibility and memory audit.
- Share the same mutable `Vertices` object between old and candidate roots:
  rejected; each snapshot remains independent so failure rollback cannot leak
  candidate edits into the retained root.

## Evidence and limits

On the current CPython host, copying a full one-million-member `Vertices`
partition retained 8,000,224 traced bytes; converting it to a Python set
retained 65,546,488 bytes (87.8% higher for the set). The copy is independent,
preserves deterministic member order, and mutating it leaves the source intact.
System copy and hierarchy-region tests cover this, along with multilevel
rollback and Witness replay prefixes.

These are component measurements. Full Matcher snapshots still include graph
copies, A/B and other hierarchy sets, edge/matching state, phase colors and
indexes. Process peak memory and paper throughput remain unqualified; the
durable paper-service integration is still active work.

## Consequences

Dense U state remains compact through the covered phase and hierarchy roots,
reducing temporary allocation without sharing mutable candidate state. This
narrows, but does not complete, the paper snapshot migration. No billion-vertex
support or production durability guarantee is implied.
