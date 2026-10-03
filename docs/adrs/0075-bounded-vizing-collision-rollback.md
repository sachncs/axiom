# ADR 0075: Bound Vizing collision transaction state to touched paths

Date: 2026-10-03  
State: Implemented; other paper snapshots remain

## Context

`Vizing.resolve` copied every coloring assignment and every fan before resolving
two colliding chains. The resolver mutates only chain path edges and center-to-
leaf spokes; its successful same-direction fan check also revalidated the
entire fan collection. This made a local collision pay O(m + F) extra copying
and validation when the graph had m colored edges and F unrelated fans.

## Decision

Form the transaction edge region from both chain paths and all spokes in the
two materialized fans. Save only the prior color values for those edges. Derive
the corresponding vertices, and snapshot only fans present in the existing
vertex-to-fan index at those vertices. Same-direction success uses the scoped
vertex set for fan compatibility validation. On failure, `Partial.replace`
restores touched color cells without replacing the coloring's assignment/index
roots; fan restore discards current fans in the touched region and restores its
before-image, leaving disjoint fan state and all outer index roots intact.
Callers without an explicit region retain the global restore behavior.

## Correctness

Both `Vizing.activate` calls receive prefixes of the captured chains and rotate
only spokes of those chains. The same-direction branch additionally unassigns
predecessor edges and may add a fan at the shared path vertex. Every potentially
changed edge is therefore in the captured path/spoke union, and every fan that
can be removed, recolored, or made incompatible contains an endpoint in the
derived vertex set. Regression coverage injects failure after a new fan has
been indexed, verifies exact coloring/fan values, preserves container-root
identity, and confirms an unrelated sentinel fan remains compatible. Existing
collision routing and failure tests cover early and mid-chain failures.

## Evidence and limits

On a deterministic same-direction collision with 4,000 unrelated fans and
4,000 unrelated colored edges (20,008 vertices), seven alternating-order runs
measured median `Vizing.resolve` time of 9.13 ms before and 0.076 ms after
(120.23x). Every output passed independent coloring, fan-index, and full
compatibility validation. This is an isolated synthetic collision; it excludes
full Pruning/Matcher work and memory-peak measurement, and does not qualify
connected adversarial graphs. See the
[raw comparison](../../benchmarks/results/paper/vizing-local-collision-transaction.json).

## Alternatives

- Keep copying the entire coloring and fan collection: rejected for a bounded
  chain collision because the touched path region is explicit.
- Rebuild all coloring indexes on rollback: rejected; touched-cell replacement
  retains root identity and runs the existing local certificate.
- Assume every fan is compatible after mutation: rejected; local compatibility
  checks still cover every fan that can be affected by the captured region.

## Follow-up

Apply the same bounded-before-image design to other fan/coloring operations
only after deriving complete mutation regions; Pruning and Sparsify snapshots
remain state-sized and require separate failure-injection coverage.
