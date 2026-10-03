# ADR 0056: Reuse inherited phase roots across child rebuilds

Date: 2026-10-03

## Context

When a multilevel child phase rebuilt, it copied the retained
`phase_base_graph`, copied the retained `phase_base_system` onto that graph,
then copied the resulting System again to retain it. Recursive refinement
needs an isolated working graph/System, but the inherited parent roots are
read-only during that operation. Recopying them for retention added graph-wide
and partition/cache-sized transient allocations on every child rebuild.

## Decision

Reuse `Matcher.phase_base_graph` and `Matcher.phase_base_system` directly as the
inherited roots for a child rebuild. Validate the retained System, then create
only the detached `refine_graph` and `working_base_system` that recursive
refinement will mutate. Keep the inherited roots assigned to the Matcher after
the child rebuild.

The Matcher transaction already retains graph and System root identities and
opens owner journals for them. The child path does not mutate either inherited
root, so rollback preserves their identity without reconstructing their
contents. Parent-boundary rebuilds still capture a new phase-base graph and
build a fresh level-one System; this decision does not alter that lifecycle.

## Alternatives considered

- Clone inherited roots for defensive isolation: rejected because recursive
  refinement mutates detached working copies, not the inherited roots.
- Share the inherited System with the working hierarchy: rejected because
  refinement mutates partitions, matching, graph bindings, and cache rows.
- Remove full phase-base snapshots: deferred; parent-boundary isolation and
  correctness need separate design and qualification.

## Verification

`test_recursive_rebuild_inherits_level_one_without_rebuilding` instruments
snapshot and System-copy calls and proves a child rebuild makes one working
graph snapshot and one working-System copy. It also verifies retained graph and
System identities, graph contents, matching and `System.check()` afterward.
`test_failed_child_rebuild_restores_inherited_phase_roots` injects a coloring
failure during a real Matcher delete/rebuild and verifies exact live-graph,
hierarchy, inherited-root, and partition restoration. The full test suite and
static checks gate this change.

## Consequences

Child rebuilds avoid one full clone of the inherited graph and two redundant
copies of the inherited base System. They retain one graph/System copy for the
mutable refinement input. Parent-boundary graph/System snapshots, other
state-sized hierarchy construction/audits, and durable paper integration
remain open.
