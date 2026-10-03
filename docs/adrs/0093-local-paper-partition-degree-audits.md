# ADR 0093: Restrict Euler partition degree audits to active vertices

Date: 2026-10-04
State: Implemented; high-degree connected qualification remains

## Context

After component discovery stopped walking isolates, `Paper.partition` still
scanned `range(graph.n)` twice: once to find the input maximum degree and once
per output graph to check the balanced-degree bound. An isolated vertex has
degree zero in the input and in both outputs. It cannot affect the maximum, nor
can it violate the positive bound `(maximum + 2) // 2`.

## Decision

Run both exact checks over the connected components containing input edges.
Those component vertex sets cover every vertex with nonzero input degree, and
every vertex whose output degree could be nonzero. Retain the maximum-degree
and both output-bound checks; only their candidate domains change. For an empty
graph the candidate set is empty, `maximum` defaults to zero, and no output
edge can violate the bound.

## Correctness evidence

The sparse partition regression instruments the module's `range` and requires
zero full-universe scans. It verifies disjoint output edge sets with a union
equal to the input. The K34 parity-partition and complete-coloring regression
continues to exercise nontrivial connected components. The full hierarchy and
paper coloring suites remain active.

## Measurement and limits

Three alternating runs compare this change to ADR 0092's implementation on the
same 2,048-label/three-edge `Packed` graph. All output partitions were equal.
Baseline elapsed times were 0.340, 0.293, and 0.291 ms; candidate times were
0.187, 0.171, and 0.171 ms. Median time fell from 0.293 to 0.171 ms (41.6%).
Median traced peak was 3,264 bytes before and 3,384 after; there is no claimed
allocation reduction for this incremental change. This sparse fixture does not
qualify high-degree connected graphs, full recursive seed behavior, RSS, or
service throughput.

## Alternatives

- Retain the scans over all n labels: rejected because isolated vertices are
  provably incapable of changing either certificate.
- Drop the degree-bound checks entirely: rejected because the balanced Euler
  partition invariant must still be independently checked.
- Construct another endpoint set for validation: rejected because the
  component vertex sets already represent exactly the active validation domain.

## Follow-up

Seed recursion still scans the full child universe to compute each child's
maximum degree. Reuse or expose active-vertex degree bounds without weakening
the partition guarantee, then qualify connected, dense, and high-degree shapes.
