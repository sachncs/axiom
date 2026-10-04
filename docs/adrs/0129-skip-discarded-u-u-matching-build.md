# ADR 0129: Skip greedy edges that the U-U rule discards

- Status: implemented; constrained Linux qualification pending
- Date: 2026-10-04

## Context

In a sparse graph whose maximum degree is below the Basic paper cap `z`, the
ordinary builder first inserts every edge into the greedy `M`, then derives an
empty saturated set and removes every edge again because both endpoints are
in `U`. On a million-vertex degree-four graph, that temporary Python edge set
is larger than the persistent Packed graph and can dominate construction RSS.

## Decision

For the exact built-in `Adjacency` and `Packed` backends, first check whether
every host degree is strictly less than `z`. When true, construct the proven
final state directly: `A=B=M=empty`, `U=V`, then build the required Lambda/L
indexes. This is equivalent to the greedy-cap-plus-U-U-removal sequence: no
vertex can become saturated, and all selected matching edges are U-U and are
removed. Skip the promotion pass because with `B=empty` no U vertex can be
promoted. Other graph backends and any graph with a degree at least `z` retain
the general paper builder.

## Consequences

- The exact common sparse case avoids an O(m) transient Python matching set
  and an O(n) promotion scan without weakening the System invariant check.
- The fast path still builds and audits the persistent paper neighbor indexes;
  compact Packed row representation is covered separately by ADR 0128.
- A local macOS 1M-vertex / 2M-edge Packed build reported `ru_maxrss` of
  286,670,848 bytes (~273.3 MiB) after both optimizations. This is a smoke-test
  measurement, not the hosted Linux address-space qualification.
- The degree scan costs O(n), which is bounded by the construction already
  required and stops as soon as a degree reaches `z`.

## Verification

A regression verifies the exact empty-M partition, index count, and full
System certificate on a degree-four Packed ring with `z=5`. Existing mixed
degree system and hierarchy tests exercise the fallback builder. Hosted Linux
resource qualification remains a release gate.
