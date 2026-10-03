# ADR 0042: Stream ordered edges into the paper System builder

Date: 2026-10-03

## Context

The greedy initializer for a paper `System` used `sorted(graph.edges())` for all
graph implementations. This retained one Python tuple per edge and performed
a global `O(m log m)` sort before scanning. Both built-in implementations
already enumerate vertices in ascending order and each row's neighbors in
ascending order, so their canonical edge streams are globally lexicographic.
This extra list and sort were redundant for the default `Packed` backend and
the built-in `Adjacency` reference.

## Decision

- Consume `edges()` directly for exact `Adjacency` and `Packed` instances.
- Keep the sorted materialization fallback for custom `Graph` implementations,
  whose protocol promises canonical edges but does not promise an order.
- Use exact-type selection so a subclass that overrides iteration does not
  accidentally inherit the built-in ordering assumption.
- Preserve the edge order and greedy matching decisions for built-in graphs;
  preserve sorted deterministic behavior for custom graphs.

## Alternatives considered

- Globally sort every iterator: correct and generic, but redundant peak memory
  and sorting work for owned graph types.
- Assume every `Graph.edges()` is sorted: invalid under the current protocol
  and could silently change custom graph behavior.
- Add a new ordered-edge method to the protocol: larger API expansion than
  needed for two known implementations; may be revisited if more backends need
  a streaming guarantee.

## Evidence and limits

On this host, an isolated edge-enumeration comparison used a `Packed` path
with 200,000 vertices and 199,999 edges. `sorted(graph.edges())` took 0.276s
and reached 27,202,176 traced bytes. Counting the direct iterator took 0.019s
and reached 432 traced bytes. Counts matched. This is one component sample;
it excludes `System.build()`'s matching/partition work, native allocations,
rebuild snapshots, and process RSS. It does not qualify graph rebuild rate.

Focused builder tests require identical partitions/matching on ordered and
reversed custom edge iterators. The full suite remains the required check for
both paper modes and both built-in graph backends.

## Consequences

The built-in builder avoids an `O(m)` Python edge-tuple retention and a global
sort. Per-row ordering work in the graph iterators remains, and later builder
state such as matching edges, partitions, and phase snapshots may still be
state-sized. Custom Graph implementations retain the prior behavior. No
durability, asymptotic theorem, or billion-vertex guarantee is implied.
