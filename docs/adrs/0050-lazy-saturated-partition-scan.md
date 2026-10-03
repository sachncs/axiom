# ADR 0050: Lazy saturated-partition traversal

Date: 2026-10-03

## Context

`System.S` intentionally exposes `A | B` as a regular set. Several internal
paths used it only to iterate, nevertheless allocating a second hash table
proportional to the saturated partition size. This is avoidable transient
memory during rebuild, seed synchronization and independent auxiliary checks.

## Decision

Keep the public `S` property and its detached-set semantics. Add
`System.saturated()` as a lazy iterator over `A` followed by `B`, and use it in
internal traversal-only paths. For point membership, query `A` and `B` directly.
Paths that require sorting still sort the iterator's values, preserving their
deterministic order; set construction is retained only where it is the actual
destination (for example, `S_hat`).

## Alternatives considered

- Change `S` to a view or iterator: rejected because callers may rely on a
  detached mutable set and membership semantics.
- Maintain a third cached `S` set: rejected because it duplicates retained
  state and introduces another journal invariant.
- Compact the retained `A`/`B` sets immediately: deferred to a separate
  representation migration because mutations currently bypass partition-owner
  journals and exact rollback must be added first.

## Evidence

[`saturated-scan.json`](../../benchmarks/results/paper/saturated-scan.json)
records five isolated traversals of one million vertices split evenly across
`A` and `B`. The original set union peaks at 50,331,864 traced bytes; lazy
iteration peaks at 632–1,432 bytes. Source sets are allocated before tracing.
This proves temporary allocation savings for the isolated operation, not a
50-MB end-to-end RSS reduction. Focused System/cache tests and full-suite
verification cover semantics and integration.

## Consequences

Internal traversal avoids a large temporary set. Retained `A` and `B`, other
state-sized graph/phase data, and the durable paper integration gap remain.
The public property remains intentionally allocation-producing.
