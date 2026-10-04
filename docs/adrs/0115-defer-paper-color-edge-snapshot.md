# ADR 0115: Defer and reuse Paper color edge certificates

Date: 2026-10-04
State: Implemented; large-graph allocation impact not yet measured

## Context

`Paper.color()` retained a complete edge set before choosing its recursive seed
path. The high-degree recursive seed can create another complete edge set for
its fallback while the caller's certificate set remains live. The final
independent completeness check also converted the coloring mapping to a new set
of keys before comparing it with the caller's edge set.

## Decision

For the recursive seed path, use the graph's edge count to select the
nonempty-seed branch, run the seed first, then materialize the edge set needed
by the independent result certificate. The low-degree direct-completion path
continues to materialize one set and pass it through completion and
certification. Compare `coloring.keys()` directly with the certified edge set
instead of copying all mapping keys into another set.

## Consequences

The recursive result certificate no longer overlaps its full edge-set snapshot
with recursive seed temporaries, and key completeness no longer requires an
additional O(|E|) hash set. This assumes the graph's `num_edges()` contract is
consistent with its reusable `edges()` view, as already required by graph
certificates. Coloring and full edge certification still perform global work.

## Verification

A tracking graph test proves the edge snapshot is requested only after the
recursive seed returns. A mapping that rejects direct key iteration proves the
completeness comparison uses its key view. Paper coloring family and full
invariant tests remain required; no large-graph performance claim is made.
