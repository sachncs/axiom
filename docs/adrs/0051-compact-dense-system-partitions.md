# ADR 0051: Compact dense System partitions

Date: 2026-10-03

## Context

Dense `System.A` and `System.B` were retained as Python hash tables even though
vertex labels are dense integers in a fixed universe. `Vertices` already stores
membership in a fixed-width position array and members in a packed array; it is
used for dense `U` and hierarchy regions. Phase-copy code nevertheless expanded
all three partitions into Python sets before constructing a new System.

## Decision

- Keep sparse `A` and `B` as built-in sets. Compact either partition when its
  population reaches one eighth of the fixed universe. `U` retains its existing
  one-twelfth crossover.
- Build `A` and `B` from temporary member lists and choose compact storage before
  creating hash sets for dense partitions.
- Copy `Vertices` roots with their compact `copy()` method; do not round-trip
  dense `A`/`B` through Python sets in phase snapshots.
- Teach System admission to accept plain sets or exact `Vertices` containers.
  Check compact universe size cheaply on stable roots; fully validate compact
  contents for standalone audits and new/replaced candidates.
- Preserve set-like mutation, membership, iteration and equality semantics.
  `System.S` remains a set-producing public API; internal traversal uses the
  lazy iterator recorded in ADR 0050.

## Alternatives considered

- Convert every partition to indexed arrays: rejected because each `Vertices`
  reserves a universe-sized position array, which costs more for sparse A/B.
- Keep A/B as Python sets: rejected for dense partitions due to hash-table and
  boxed-integer retention.
- Always convert arbitrary caller-provided sets: the constructor currently
  applies the same density policy, but set-to-array overlap increases transient
  construction peak. The canonical builder therefore avoids creating those
  intermediate sets; callers under a strict peak-memory cap should construct
  compact values directly.

## Evidence

[`partition-storage.json`](../../benchmarks/results/paper/partition-storage.json)
records an isolated one-million-label, half-A/half-B representation comparison.
Two Python sets retain 65,543,888 traced bytes; compact `Vertices` roots retain
12,201,952 bytes (81.4% lower). The builder-style list-to-array path peaks at
52,189,904 bytes versus 67,998,672 for set construction in this probe. Direct
conversion from already-created sets peaks at 77,749,712 bytes due to overlap;
this transient cost is why the builder now selects compact storage directly.
These are partition-only traced allocations, not whole-Matcher RSS or update
qualification. Tests cover sparse/dense selection, set operations, build/copy,
System validation and the full update/property suite.

## Consequences

Dense retained A/B memory is substantially lower, while sparse partitions retain
the lower-overhead representation. Rebuild copies preserve the savings. The
universe-sized position arrays and temporary candidate graph/system state still
matter at large scales; whole-process million/billion-vertex support is not
established by this isolated result.
