# ADR 0084: Select projected fans without sorting the parent collection

Date: 2026-10-04
State: Implemented; connected and full-engine qualification remains

## Context

`Extension.project` selected fans with `for fan in fans`. `Fans.__iter__`
provides deterministic sorted iteration by materializing and sorting all
members. Projection then separately retained only fans whose two-color type is
inside the requested color group. For skewed groups, this paid sorting cost for
many fan objects that the projection immediately discarded.

## Decision

Iterate `fans.members`, the authoritative member set, directly for filtering;
retain the selected fans once and reuse that list for edge-scope collection and
child-fan construction. These consumers do not depend on iteration order: edge
scope is a set and the child `Fans` collection maintains its own membership
invariants and deterministic public iteration. Keep sorted `Fans.__iter__` for
callers that require its established behavior.

## Correctness evidence

A regression wraps `Fans` and counts calls to its sorted iterator, proving that
projection does not sort/materialize the parent collection. It also verifies
the selected child fan count, projected edge scope, packed child representation,
and child coloring/fan invariants. The broader paper-coloring suite remains the
gate for projection semantics.

## Measurement and limits

Five runs on a 75,000-vertex graph with 25,000 independent fan gadgets selected
1,250 fans (5%) for one projection, with no colored edges and palette size four.
Median elapsed time changed from 46.9652 ms to 34.4138 ms (26.73% faster); peak
traced allocation changed from 3,552,976 to 3,409,048 bytes (4.05% lower).
This is a component-level Python allocation/timing probe, not RSS, connected
graph, full paper-engine, durable-service, or billion-vertex qualification.

See the [raw comparison](../../benchmarks/results/paper/project-fan-selection.json).

## Alternatives

- Keep sorted iteration: rejected for this internal filter because ordering is
  unnecessary and the complete sort penalizes skewed projections.
- Scan `fans.members` twice without retaining matches: rejected because it
  repeats the fan-type predicate; the selected list is reused by both consumers.
- Change the public ordering contract of `Fans`: rejected; sorted iteration
  remains intact for other callers.

## Follow-up

Measure connected and high-degree projections and continue profiling the
materialized edge scope, degree preflight, and child graph construction. This
change does not address remaining state-sized paper snapshots or durable paper
integration.
