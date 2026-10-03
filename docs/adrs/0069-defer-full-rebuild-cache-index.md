# ADR 0069: Defer cache indexing for multilevel full rebuilds

Date: 2026-10-03  
State: Implemented; complete rebuild qualification remains open

## Context

A full multilevel rebuild constructs and indexes the retained level-one
`phase_base_system`, then copies it into a working System and indexed that
copy's full-graph Lambda/L rows. When the schedule has another z-level,
`build_hierarchy` immediately refines the working System onto a selected
projected graph and recomputes the retained level's indexes there. The
pre-refinement copy indexes are never consumed.

## Decision

For a multilevel full rebuild with at least one refinement step, copy the
working System without indexing it. `refine_hierarchy` constructs its required
graph-dependent indexes before the new hierarchy is checked or published. Keep
the copied System indexed for a one-level schedule, where the builder has no
refinement step and may return it directly.

## Correctness and lifecycle

The retained `phase_base_system` remains fully indexed and is checked before
publication as before. The unindexed System is private to the local rebuild
path; `build_hierarchy` consumes it synchronously. Every multi-level path
performs at least one refinement, whose retained-level pass calls `System.index`
on the projected graph. The one-level regression continues through the eager
index branch and complete hierarchy certificate. No incomplete System is
published.

## Evidence and limits

On a 50,000-vertex, 50,000-edge `Packed` ring, five traced `copy()` repeats
measured median copy-only time of 94.7 ms with eager indexing and 0.55 ms when
indexing was deferred. Maximum traced peaks were 2,499,848 and 2,498,696 bytes.
Both copies were independently indexed as needed and passed `System.check()`;
this isolates the pre-refinement copy stage and does not claim a similar total
rebuild speedup, because refinement performs its required indexing on a
different graph. The full rebuild regression proves the multi-level copy is
unindexed and the completed hierarchy passes its certificate. See the
[raw comparison](../benchmarks/results/paper/deferred-rebuild-index.json).

## Alternatives

- Keep eager indexing on every working copy: rejected because multi-level
  refinement immediately discards those full-graph rows.
- Always skip indexing: rejected because a one-level build can return the
  working System without a refinement to construct its indexes.
- Publish before refinement indexes are ready: rejected; the final hierarchy
  and system checks remain required before rebuild succeeds.

## Follow-up

Measure end-to-end rebuild time and RSS across one-level, sparse and dense
multi-level schedules. Refinement/coloring costs and the required retained
phase-base indexes remain in scope.
