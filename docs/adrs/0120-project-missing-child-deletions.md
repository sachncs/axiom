# ADR 0120: Project child-phase deletions without cloning the parent graph

Date: 2026-10-04
State: Implemented; full-rebuild snapshots remain open

## Context

During a Multilevel child-phase rebuild, deletion history may contain edges
absent from the inherited phase graph. The previous path cloned the entire
parent graph and reinserted every missing edge merely to satisfy refinement's
input validation. Refinement then projected a new working graph and removed
those deletions again unless the paper selected them for deferred retention.
This added O(V + E) copy work and memory before the already-required projection.

## Decision

Child rebuilds pass the immutable inherited graph directly to refinement. The
explicit `restore=True` path accepts missing deletion-history edges as metadata;
it inserts only missing edges that are also selected into the deferred-deletion
set while streaming the detached output graph. It probes only this selected
subset for missing topology instead of allocating and sorting every missing
deletion. Direct refinement keeps strict validation by default. The inherited
parent graph is never mutated.

## Consequences

The missing-deletion child path no longer allocates a full graph clone. It still
constructs the required projected output graph and selected result sets. Parent
phase-boundary rebuilds still snapshot the complete live graph, and custom graph
fallbacks may materialize edges; neither is addressed here.

## Verification

For both `Adjacency` and `Packed`, the regression removes all old matching
edges from the inherited graph, then compares the resulting graph, deferred
set, partitions, matching, cache lists, and hierarchy certificate with a
reference run that materializes/restores the old graph first. It verifies the
source graph remains unchanged and strict mode continues rejecting missing
edges. Matcher child-rebuild tests for both backends confirm the graph snapshot
helper is not called and inherited roots remain intact. These deterministic
correctness checks do not quantify end-to-end runtime or allocation savings. A
probe-count test verifies that the restore path checks only the edges selected
for deferred retention.
