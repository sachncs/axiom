# ADR 0072: Localize hierarchy refinement matching scans

Date: 2026-10-03  
State: Implemented; broader refinement qualification remains open

## Context

`refine_hierarchy` repeatedly filtered the complete selected matching to find
incident edges while classifying prior B vertices, promoting U vertices, and
repairing B vertices after a promotion. One repair path also copied the entire
matching to a tuple before filtering it. These operations make local refinement
work scale with the total matching size and create avoidable temporary memory.

## Decision

Enumerate the current projected graph's neighbors for each affected vertex and
test each canonical incident edge against the existing `chosen` set. This
retains matching membership semantics while limiting candidate traversal to
the local graph degree. Remove the now-unused set-scanning neighbor helper.

## Correctness

Every selected matching edge retained in `chosen` is either present in the
working phase graph, an inserted edge included in its projection, or a deferred
deleted edge explicitly retained in that projection. Thus the projection's
neighbor iterator contains every edge relevant to these matching predicates.
The implementation only changes how incident selected edges are discovered;
the partition predicates and matching updates are unchanged. The deterministic
two-swap witness regression checks the exact refined matching, full hierarchy
certificate, and immutability of the source graph.

## Evidence and limits

On 256 disjoint copies of the existing 8-vertex ProcProcess witness fixture
(2,048 vertices, 4,096 edges; z=8 to z'=4), three uninstrumented refinement
runs measured a 0.4127-second baseline median and 0.1715-second candidate
median (2.41x). Every output passed `Hierarchy.check()`. This is an isolated,
single-host component benchmark; it excludes graph/base-hierarchy construction,
does not measure allocation peaks, and is not broader repeatability or
end-to-end rebuild qualification. See the
[raw comparison](../../benchmarks/results/paper/refinement-local-matching.json).

## Alternatives

- Keep scanning all selected edges for each vertex: rejected because sparse
  local work then scales with the full matching.
- Build and retain a matching-partner index: rejected because graph adjacency
  supplies local candidates without a second matching-sized index.
- Remove hierarchy validation: rejected; full hierarchy certificates remain.

## Follow-up

Repeat this comparison across degree distributions and refinement levels, and
measure allocation/RSS as part of the active paper-engine repeatability work.
