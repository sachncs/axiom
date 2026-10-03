# ADR 0088: Localize refinement boundary normalization

Date: 2026-10-04
State: Implemented; broader hierarchy qualification remains

## Context

After ProcProcess, `refine_hierarchy` normalized each vertex in `new_a` by
scanning every edge in `chosen` to find a selected matching edge into `new_u`.
It repeated the same full matching scan for each vertex in `new_b`. This is
O((|A|+|B|)|M|) work even though the answer for a vertex depends only on its
incident selected edges.

Every edge in `chosen` belongs to the projected `working_graph`: retained
matching edges are selected only when present in the phase graph or explicitly
deferred, and inserted edges are merged into that graph. Therefore filtering
the vertex's graph neighbors by `new_u` and chosen-edge membership is equivalent.

## Decision

For the A-to-B pass, collect only A vertices with a chosen edge to U by scanning
their incident working-graph neighbors, then move those vertices. For the
subsequent B-to-A pass, collect only B vertices without a chosen edge to U using
the same local predicate, then move them. Preserve pass order because the first
pass changes the input to the second. The temporary lists contain only vertices
that move, rather than unconditional tuples of every partition member.

## Correctness evidence

Existing deterministic hierarchy tests cover exact refinement matching,
partitions, deferred deletions and the complete hierarchy certificate. Five
baseline/candidate runs also compared canonical output across every level,
partition, matching and cache row; states were identical and both versions
passed `Hierarchy.check()`.

## Measurement and limits

Five alternating runs use 256 disjoint copies of the 8-vertex/16-edge
witness-heavy fixture (2,048 vertices, 4,096 edges), refining z=8 to z=4.
Hierarchy construction is outside the timed/traced region. Median time changed
from 395.951 ms to 257.496 ms (34.97% faster). Median traced peak was
1,654,079 bytes before and after; this change is a compute improvement, not a
storage result. The fixture is disconnected and single-host; it does not qualify
connected, skewed, durable-mode, full Matcher or product performance.

See the [raw comparison](../../benchmarks/results/paper/refinement-boundary-normalization.json).

## Alternatives

- Keep the per-partition scan of all selected matching edges: rejected because
  matching edges are present in the working graph and local adjacency gives the
  same predicate in work proportional to incident edges.
- Build a vertex-to-matching-partner index: rejected because it adds O(n) or
  O(|M|) temporary storage for data already available in graph adjacency.
- Reorder A/B normalization passes: rejected because B-to-A decisions observe
  the result of the preceding A-to-B movement.

## Follow-up

Repeat on connected and hub-skewed graphs; continue removing state-sized
phase-boundary and stable-frontier snapshots. This does not complete durable
paper integration or service/deployment qualification.
