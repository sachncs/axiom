# ADR 0090: Keep hierarchy matching-degree audits sparse

Date: 2026-10-04
State: Implemented; broader hierarchy qualification remains

## Context

`Hierarchy.check()` built a dense degree array for every level's selected
matching, scanned the array to enforce its degree ceiling, then allocated and
filled another dense array for the final level's minimum-degree checks. Sparse
matching levels therefore paid O(n) Python/native-array initialization and
retained duplicate degree state despite having only a few selected edges.

## Decision

Count selected-edge degrees in a dictionary when `36 * |M| < n`; otherwise use
the existing compact unsigned array. Both paths reject a cap violation during
counting, so no full degree-array scan is needed. Reuse the final level's count
result for the final A/B minimum-degree predicates instead of recounting its
matching into another array. Missing sparse entries represent degree zero.

The crossover is a conservative storage heuristic, not a universal timing
optimum. It compares Python dictionary entry overhead against the compact
counter array; both representations preserve the same exact counts.

## Correctness evidence

The sparse certificate regression patches dense degree-array construction to
fail and confirms a one-edge hierarchy still passes. A dense-count regression
checks exact endpoint/zero counts. The hierarchy suite and full test suite are
required; existing level-cap and final minimum-degree checks remain active.

## Measurement and limits

On a 100,000-vertex graph with one edge, building the graph and hierarchy was
excluded. A single before/after `Hierarchy.check()` run retained identical
`True` certificates. Traced peak fell from 801,512 to 101,329 bytes (87.4%);
elapsed time was 1.9146 s before and 1.9238 s after, within single-run noise
and not claimed as a speedup. This measures one sparse shape and one process;
tracemalloc does not include process RSS or native capacity. Dense/connected
and adversarial hierarchy shapes still need repeatability qualification.

## Alternatives

- Always allocate dense arrays: rejected for sparse large universes because
  zero counters dominate useful state.
- Always use dictionaries: rejected because dense matchings have higher Python
  object overhead than compact counters.
- Reuse the prior level's counts without checking its actual matching: rejected;
  every level is counted independently, and only the final level result is
  reused for predicates over that same level.

## Follow-up

Continue removing graph-sized paper snapshots and global hierarchy work, then
repeat sparse, connected, dense, and adversarial certificates with process-RSS
and end-to-end update evidence. Durable paper-mode integration is still a
separate unfinished milestone.
