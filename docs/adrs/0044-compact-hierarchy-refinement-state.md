# ADR 0044: Compact multilevel refinement and validation state

Date: 2026-10-03

## Context

After compacting the U/R partitions, multilevel refinement and its invariant
checker still created several universe-sized Python structures:

- per-vertex degree dictionaries, including in each retained level audit;
- an empty set for every possible vertex in the incident-color validator;
- one or more `set(range(n))` values to validate labels and partition coverage;
- a materialized phase-edge set followed by another derived live-edge set.

These were temporary allocations, but phase reconstruction and validation occur
at precisely the points where peak resident memory and failure recovery are
already sensitive.

## Decision

- Share `system.degrees(n)` as the bounded unsigned-array allocator for matching
  degree counts. Use it in the initial System builder, multilevel refinement,
  and hierarchy degree audits. Colorful state detection enumerates the indexed
  array directly rather than sorting dictionary items.
- Allocate incident-color sets lazily for the endpoints present in the
  colored matching. An untouched vertex has no incident colors by definition.
- Use `range(n)` for changed-edge endpoint validation and `Graph.has_edge()`
  for changed-edge presence checks; do not allocate a vertex-universe or
  full-phase-edge set solely for those predicates.
- Build the one required live-edge set by seeding inserted edges and streaming
  the phase graph once while excluding pending deletions.
- Validate each System partition with its existing exact partition checker;
  validate hierarchy-wide disjointness and coverage with intersections and
  cardinality instead of materializing `set(range(n))`.

## Alternatives considered

- Keep independent Python dictionaries and empty color sets: simple but costly
  at large universes and repeated hierarchy levels.
- Remove all full edge sets: not in this decision. Coloring, subgraph
  projection, matching selection, and certain journal operations currently
  require materialized edge membership; removing those needs separate
  algorithms and rollback proofs.
- Weaken hierarchy validation: rejected. Existing structural/index checks,
  degree bounds, partition disjointness/coverage, endpoint constraints, and
  differential replay remain active.

## Evidence and limits

The array allocator is the same one-million-counter representation measured
in ADR 0041: about 4 MB versus 73.9 MB for a Python dictionary on this host.
Existing hierarchy corruption, bound, adversarial, rollback, Witness replay,
and both-backend tests exercise the changed routes. The full suite is the gate
for this change.

No end-to-end process RSS or multilevel rebuild-rate comparison has yet been
run for this exact revision. Live edge sets, phase graph snapshots, coloring,
other partitions, and selected matching state can still scale with n or m.

## Consequences

The hierarchy no longer creates several avoidable full-universe Python
containers during validation and refinement. Graph lookup work for explicitly
changed edges scales with the change batch, while a single live-edge collection
remains. This is a local representation/peak improvement, not a durability,
algorithmic-bound, product qualification, or billion-vertex claim.
