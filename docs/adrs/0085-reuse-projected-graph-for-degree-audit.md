# ADR 0085: Reuse the projected graph for degree feasibility

Date: 2026-10-04
State: Implemented; broader hierarchy qualification remains

## Context

`Extension.project` used an O(V_scope) Python dictionary to count degrees,
then sorted the O(E_scope) edge set into another list to build the isolated
child graph. Both structures duplicated information already represented by
the child graph. The graph container maintains endpoint degrees as edges are
inserted.

## Decision

Build the isolated child graph by iterating the edge-scope set directly. Track
the maximum degree using the two endpoint degree queries after each insertion;
degrees only increase during this construction, so the running maximum is the
final maximum. Remove the Python degree dictionary and sorted edge-list copy.
The child graph remains private and isolated, and the returned edge scope and
local color mapping are unchanged.

This moves the infeasible-degree rejection until after construction of the
local child graph. It still occurs before any parent coloring or fan mutation.
The tradeoff is acceptable for this projection boundary because the child graph
is required for every feasible projection; the exact failure regression guards
the parent state. If projection errors become an expected operational path, a
bounded preflight policy should be measured separately.

## Correctness evidence

Projection tests continue to verify the exact scope, child graph isolation,
packed budget preservation, local colors, child validity, and selected fan
compatibility. A new infeasible-degree regression captures exact `Partial` and
`Fans` state with `Witness`, requires rejection, then verifies the same exact
state and independent invariants after failure.

## Measurement and limits

Five alternating baseline/candidate runs use a connected chain of 12,000
three-vertex fan gadgets (36,000 vertices), with 11,999 colored connector edges,
600 selected fans (5%), and 1,200 selected spokes. The selected projection scope
contains 13,199 edges; palette size is six and the group has three colors.
Median projection time changed from 123.413 ms to 88.174 ms (28.56% faster).
Peak traced Python allocation changed from 23,049,984 to 21,739,072 bytes
(5.69% lower). Fixture setup is excluded. This is a connected component probe,
not RSS, whole rebuild, durable paper mode, or service qualification.

See the [raw comparison](../../benchmarks/results/paper/project-degree-audit.json).

## Alternatives

- Retain the degree dictionary and sorted scope list: rejected because both
  duplicate child graph state and materially increase temporary allocation.
- Retain only an endpoint set, then query child degrees: rejected because the
  measured connected probe added about 2.6 MB in endpoint-set scratch and was
  slower than direct degree checks during graph construction.
- Reject after child construction: accepted; failure remains isolated from
  parent state and the projected graph is needed on success.

## Follow-up

Continue migrating remaining state-sized work in hierarchy refinement and
phase-boundary reconstruction, especially multi-source partition construction
and parent-boundary rebases. This optimization does not make paper modes durable
and does not establish service-level performance.
