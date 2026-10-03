# ADR 0096: Store sparse refinement matching degrees sparsely

Date: 2026-10-04
State: Implemented; end-to-end allocation impact is not yet measurable

## Context

`refine_hierarchy` initialized a compact unsigned counter for every graph label,
then populated it only for endpoints in `chosen`. Most reads scan U and ask for
the degree of a vertex with no chosen edge; representing each such zero in an
array costs O(n) bytes despite zero being derivable. Sparse hierarchies can
therefore allocate a graph-sized degree array for a small selected matching.

## Decision

Use `SparseDegrees`, whose missing-key read returns zero without inserting a
key, when `36 * len(chosen) < n`. Retain the existing packed unsigned array
otherwise. The crossover is conservative and follows the hierarchy audit's
sparse/dense representation policy. All mutations continue through the same
`degree[vertex] +=/-= 1` contract, and the exact cycle key still derives degree
from the chosen matching rather than retaining a copy.

## Correctness evidence

A sparse 1,024-label star hierarchy with four selected base matching edges
refines from z=4 to z=2 while dense degree-array construction is patched to
fail. The resulting hierarchy certificate passes with the expected two
matching edges. Existing denser refinement cases continue to exercise the
packed-array branch. The full suite compares refinement state and rollback
through both graph backends.

## Measurement and limits

For an isolated one-million-label degree state with four touched endpoints,
traced peak was 4,000,164 bytes for `degrees(n)` versus 904 bytes for a
`SparseDegrees` map populated at those endpoints. This is a representation
microprobe, not a whole-refinement measurement.

Three alternating full refinements on a 20,000-label star graph had valid
certificates and two output matching edges in both implementations. Median
elapsed time was 1.165047 s before and 1.170478 s after (+0.47%); total traced
peak was 18,128,312 versus 18,128,296 bytes, effectively unchanged because
other hierarchy allocations dominate. No end-to-end speed or peak-memory gain
is claimed. The change removes the degree array itself, but full cycle-key,
partition, graph and System work remain.

## Alternatives

- Always allocate the packed array: rejected for sparse matching state because
  most counters are implicit zero.
- Always use a Python map: rejected for denser matchings due to per-entry object
  and hash-table overhead; packed counters remain the dense representation.
- Use `defaultdict(int)`: rejected because reading a zero degree would insert a
  hash entry and grow the supposedly sparse state across U scans.
- Remove exact cycle detection: rejected; repeat-state protection remains.

## Follow-up

Measure process RSS and full refinement on larger sparse and dense connected
families. Prioritize larger graph-sized cycle snapshots and child phase graph
copies, then integrate paper modes into typed durable recovery. This counter
change is not a performance qualification or a substitute for those migrations.
