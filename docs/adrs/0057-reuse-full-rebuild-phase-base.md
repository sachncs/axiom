# ADR 0057: Reuse the phase base captured by a full rebuild

Date: 2026-10-03

## Context

The non-incremental multilevel rebuild branch already snapshots the current
live graph and builds the next inherited level-one `System` on that snapshot.
It then builds the hierarchy and validates/publishes it. At the end of the
same rebuild, the parent-boundary epilogue cloned the unchanged live graph a
second time and rebuilt an equivalent level-one System, discarding the roots
already prepared at the beginning.

## Decision

Track whether a rebuild used the child/incremental path. At a parent boundary,
retain the roots created by the full-rebuild path. Only an incremental child
rebuild that folds deferred edges into the current parent phase snapshots the
live graph and builds a fresh level-one System in the epilogue.

The full-rebuild snapshot and System are independent from the hierarchy graph
and are not mutated by hierarchy synchronization, matching refresh, or
validation. This keeps the isolation boundary while avoiding a duplicate graph
clone and a duplicate level-one System build.

## Alternatives considered

- Always take a final snapshot/build: rejected because the full rebuild already
  prepared equivalent roots on unchanged live topology.
- Reuse the inherited old phase base after an incremental child rebuild reaches
  a parent boundary: rejected because deferred insertions/deletions must be
  folded into a new parent-phase graph.
- Alias phase base to the mutable hierarchy graph: rejected because later child
  synchronization would mutate the supposedly immutable parent snapshot.

## Verification

`test_full_rebuild_reuses_its_phase_base_snapshot` forces the full rebuild path,
counts `snapshot()` calls, and proves exactly one graph snapshot is taken. It
checks the retained System is bound to that snapshot and passes `System.check()`;
the independently built hierarchy passes `Hierarchy.check()`. Existing child
rebuild and failure-injection tests continue to verify that incremental
parent-boundary rebases remain separate and rollback-safe.

## Consequences

Full rebuilds no longer retain a redundant phase-base graph clone or pay for a
second level-one System build. Incremental child-to-parent rebases still perform
that work when required by phase semantics. No full Matcher RSS or throughput
claim is made; durable paper integration and other state-sized construction
and audit paths remain open.
