# ADR 0060: Avoid partition copies during A-level rematching

Date: 2026-10-03  
State: Implemented; broader paper-engine qualification remains open

## Context

`Matcher.__rematch_a_level` only needs to ask whether a matched partner `p`
belongs to the active A region. The basic path copied all of `System.A` with
`set(system.A)` for every invocation. The hierarchy path materialized the union
of all A-levels with `set().union(...)`. Those copies scaled with the number of
vertices in the partitions, even though the algorithm needed a single membership
test per scanned candidate.

## Decision

Use the existing partition membership operation directly. In basic mode, query
`p in system.A`; in multilevel mode, query each level from zero through the
current level and stop at the first match. `set` and compact `Vertices` both
provide constant-time membership. The hierarchy path uses O(level) membership
checks and O(1) auxiliary memory instead of copying the accumulated partition.

## Guarantees and limits

The selected region is exactly the same union as before, so matching choices
and rematching semantics are unchanged. This removes per-call memory proportional
to A-region size. It does not eliminate candidate-list scans, paper-phase
snapshots, or other state-sized rebuild work. The Matcher remains externally
serialized in paper modes, and no production throughput or billion-vertex claim
follows from this local improvement.

## Evidence

- Added basic and multilevel regressions whose A partitions support membership
  but deliberately reject iteration. Both rematching routes complete without
  copying/iterating the partition and preserve the expected matching state.
- An isolated 1,000,000-label, 500,000-member `Vertices` probe measured a Python
  set copy at 35,225,760 bytes peak traced allocation and 0.1615 s. Direct
  membership for 100,000 lookups used 1,096 bytes peak and 0.0210 s. This isolates
  representation cost and does not represent full update throughput.

## Alternatives

- Cache a materialized union: retains a second large partition and requires
  invalidation across hierarchy mutations; rejected.
- Build an indexed union structure: unnecessary for a small number of level
  membership checks and adds lifecycle/invalidation complexity.
- Keep the set copy: simple but repeats O(|A|) time and memory per rematch.

## Follow-up

Profile paper-mode traces to identify remaining repeated state-sized temporary
allocations. Preserve independent full hierarchy checks and qualify each
optimization with exact output and rollback tests.
