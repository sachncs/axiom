# ADR 0063: Prune hierarchy matchings against graph snapshots

Date: 2026-10-03  
State: Implemented; full snapshot migration remains open

## Context

Recursive hierarchy refinement constructed a set of every live edge, combined
that set with deferred edges into a second working-edge set, projected the
working graph, and then built another complete edge set from that graph only to
restrict each retained System matching. `live_edges` was used only for
membership on selected matching/color-class edges. The final set was used only
for membership on each System's `M`, which is itself at most a matching-sized
subset of the graph.

## Decision

Determine selected-edge liveness directly from the phase graph plus the
`deleted`, `inserted`, and `deferred_deleted` sets. This avoids materializing the
full `live_edges` set. Keep the one `working_edges` set required by the current
deterministic graph projection. After projection, pass the graph itself to
`System.restrict`; it uses `has_edge` membership to cut matching edges instead
of materializing `set(working_graph.edges())`. The Systems journal uses the same
graph membership predicate while retaining all required matching-edge undo
before applying any deletion.

## Guarantees and limits

Selected matching/color-class edges use the same liveness predicate as before:
inserted edges are live; graph edges are live unless deleted; and the bounded
deferred subset remains in the phase graph. System matching restriction is
semantically unchanged. Graph-backed journal admission reserves every removed
matching edge before mutating the matching, so capacity failure leaves the
matching unchanged and rollback restores exact roots/cells.

This removes the `live_edges` and `working_edge_set` O(|E|) Python
materializations. The remaining `working_edges` set was subsequently removed
for built-in graph backends by [ADR 0064](0064-stream-hierarchy-projections.md);
opaque custom graphs retain the compatibility fallback. The isolated working
graph and state-sized refinement data remain. Graph membership now runs over
each retained matching, whose size is bounded by the vertex universe. No
update-rate or billion-vertex claim follows.

## Evidence

- System tests cover successful graph-backed cuts with and without a journal,
  exact rollback, and journal-capacity failure before matching mutation.
- Existing hierarchy tests validate inherited levels, phase graph bindings,
  matching constraints, and update rollback through full refinement paths.
- Ruff, mypy, and the full repository suite are required before publication.

## Alternatives

- Keep a full working-graph edge set for membership: rejected as redundant when
  the graph already provides constant-time `has_edge`.
- Retain `live_edges` for selected-edge checks: rejected because those checks
  cover only chosen colored edges and graph membership is sufficient.
- Remove the remaining `working_edges` set in this change: deferred because
  opaque graph iterators may not be ordered, while `project` currently promises
  deterministic projection by sorting an edge collection.

## Follow-up

Continue migrating child graph/System copies under exact rollback tests and
qualify full refinement memory under adversarial workloads.
