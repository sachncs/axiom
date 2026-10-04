# ADR 0117: Reuse Paper completion's pending edge set

Date: 2026-10-04
State: Implemented; large-graph allocation impact not yet measured

## Context

`Paper.complete()` constructed the full set of uncolored edges to pass into fan
construction, then constructed a second full difference after construction and
extension to find edges still needing Vizing. Chain flips can expose previously
colored edges as uncolored, so the final candidates must be found by scanning
the original graph-edge universe, not only the initial pending set.

## Decision

Retain the initial pending-edge set and pass it to fan construction. After any
fan activation/extension, scan the original graph-edge universe, select edges
still uncolored, sort them, and pass them to the Vizing loop. This catches
edges newly uncolored by chain flips without materializing a second difference
set. Keep the loop's membership guard so a custom construction strategy that
colors an edge early cannot cause a duplicate activation.

## Consequences

The completion path avoids a second O(|E_uncolored|) difference set, but still
scans all graph edges and builds a sorted list of remaining edges because
deterministic activation order and chain-flip completeness are part of the
coloring behavior. This does not remove global coloring certificates or bound
fan construction work.

## Verification

A set subclass counts difference operations and asserts that completion forms
the initial pending set only once. It also verifies complete assignments; the
paper coloring family, fan-chain, rollback, and full suite remain required.
No large-graph throughput claim is made.
