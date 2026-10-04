# ADR 0118: Byte-indexed Paper partition bookkeeping

Date: 2026-10-04
State: Implemented; large-graph allocation impact not yet measured

## Context

`Paper.partition()` assigned each Euler-tour edge to a side using a dictionary
keyed by original edge index and tracked consumed augmented-edge indexes in a
set. Both keys are dense zero-based indexes, so hash tables add avoidable
per-entry overhead. The Euler walk's edge ordering and parity are part of the
deterministic partition behavior.

## Decision

Represent consumed augmented-edge IDs and original-edge side assignments with
byte arrays sized to their respective edge lists. Keep the same traversal,
incident-list ordering, and parity assignment. Track the number of original
edges assigned separately, because a zero-filled array alone cannot
distinguish side zero from an unvisited entry.

## Consequences

The two bookkeeping tables use one byte per edge index rather than Python hash
table entries. This does not remove the sorted original edge list, augmented
edge tuples, incident lists, or Euler traversal storage; no billion-edge
scalability claim follows from this local reduction.

## Verification

Tests exercise empty input, odd-degree components, disconnected components,
auxiliary-loop parity, deterministic repeated output, exact edge coverage, and
the documented per-subgraph degree bound. Large-graph peak-memory and
throughput measurements remain open.
