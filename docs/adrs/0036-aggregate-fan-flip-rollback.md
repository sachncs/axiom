# 0036: Roll back endpoint fan edits with the alternating-path flip

Date: 2026-10-03. Status: implemented; two-endpoint failure injection passes.

## Context

`Fans.flip()` mutates `Partial` first and then visits fans at the path endpoints.
Even when each single-fan update is failure-atomic, an exception at the second
endpoint could leave the first endpoint changed and the coloring flipped. A
whole-collection snapshot would close the failure window but scale with every
fan for a transition that touches at most two endpoint neighborhoods.

## Decision

Preallocate an undo journal sized to the fans reachable from the two ordered
path endpoints. After the local coloring flip, record only fans actually
replaced or dropped while applying the existing endpoint update policy. On any
unexpected exception, replay those fan deltas in reverse and flip the coloring
back using the precomputed reverse path and endpoint colors. Normal execution
cost and undo storage scale with the fan incidences at those endpoints, not the
entire fan collection. Rollback failure raises an explicit fail-stop error.

The endpoint order follows path order, making the selected deterministic update
trajectory explicit rather than relying on set iteration order. Empty/one-vertex
path behavior is retained.

## Verification and limits

The regression builds compatible fans at both endpoints, injects an exception
on the second update after the first update commits, and compares the exact
`Witness` bytes for both coloring and all fan indexes before/after. It then runs
coloring, fan-index, and compatibility audits. This closes the local two-endpoint
rollback boundary; it does not integrate Matcher state with a durable paper
service, and inverse-operation rollback remains fail-stop if rollback itself
fails.
