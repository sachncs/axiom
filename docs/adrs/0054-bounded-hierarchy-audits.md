# ADR 0054: Bounded-memory hierarchy audits

Date: 2026-10-03

## Context

After compacting and sharing hierarchy partitions, the exhaustive
`Hierarchy.check()` still reconstructed `A2`, every cumulative A union, all A
vertices, and each `below − N` region as Python sets. These allocations scale
with the vertex universe and can be larger than the compact source partitions.
The checks are important independent rebuild-boundary certificates and must not
be disabled.

## Decision

- Compare dense unions with an exact one-byte-per-vertex bitmap. Mark every
  partition member, compare total population with the target, then prove every
  target member was marked. This detects duplicate, missing and foreign values.
- Compare dense regions by marking the union of included roots, clearing excluded
  members, checking the bitmap population against the target size, and verifying
  every target member. This preserves exact `union(included) - excluded`
  semantics, including overlapping source roots.
- For sparse targets, retain direct membership/cardinality certificates rather
  than allocating a universe-sized bitmap. Validate labels before indexing the
  bitmap.
- Apply the same checks to A2, cumulative level A, each R region, and N-level
  containment. Keep all remaining hierarchy invariants and rebuild-boundary
  checks enabled.

## Alternatives considered

- Remove or sample full hierarchy checks: rejected because rebuild candidates
  need an independent certificate.
- Materialize Python set unions: rejected for dense partitions due to large
  hash-table and boxed-integer scratch allocation.
- Always allocate a bitmap: rejected for sparse targets, where direct
  membership is cheaper and uses less memory.
- Trust disjointness alone: rejected; tests cover overlaps and missing members,
  and the bitmap comparison remains exact even if source partitions overlap.

## Evidence

[`hierarchy-audits.json`](../../benchmarks/results/paper/hierarchy-audits.json)
contains five timed repeats and separate traced-allocation probes on one
one-million-label host. Dense union comparison fell from 35,224,560 to 1,000,969
peak traced bytes while median time was similar (48.3 ms to 46.9 ms). A region
union/difference comparison fell from 57,935,496 to 1,000,977 peak bytes and
from 86.2 ms to 47.4 ms median. These isolate the certificate operations; they
do not qualify complete hierarchy construction, updates, durability, or RSS.
Tests cover dense bitmap and sparse membership branches, overlap, missing
members, excluded members, and complete `Hierarchy.check()` on multilevel graphs.

## Consequences

The exhaustive hierarchy audit retains exactness with scratch bounded to one
byte per universe vertex for dense cases, rather than full Python hash sets.
Sparse cases avoid universe-sized scratch. Rebuild construction still forms
some unions, and graph snapshots, paper durability, and end-to-end large-scale
qualification remain open.
