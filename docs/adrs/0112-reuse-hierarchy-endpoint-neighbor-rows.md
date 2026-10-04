# ADR 0112: Reuse endpoint neighbor rows across hierarchy levels

- Status: implemented; end-to-end performance effect remains unmeasured
- Date: 2026-10-04

## Context

Every journaled Multilevel edge delta runs an endpoint certificate. The
certificate checked both changed endpoints at every hierarchy level, but it
sorted each endpoint's complete neighbor row inside the level loop. For a
degree-`d` endpoint and `k` levels, this repeated O(d log d) sorting and
degree-sized allocation `k` times during one durable update.

## Decision

Read and sort each changed endpoint's neighbor row once before traversing the
levels. Reuse those immutable ordered rows for each level's Lambda, L, region,
and degree-bound checks. Keep all endpoint conditions, independent failure
diagnostics, and entry/exit rollback behavior unchanged.

## Consequences

- Neighbor-row traversal and sorting per edge certificate changes from
  O(k·d log d) to O(d log d); level-specific membership checks remain O(k·d).
- Temporary sorted-row allocation is two endpoint rows per certificate rather
  than one new pair per hierarchy level.
- The certificate still scales with endpoint degree; this is not a constant-time
  update guarantee and does not remove reads of other high-degree neighbors.
- No persistent cache or extra rollback state is introduced.

## Evidence and remaining qualification

A three-level hierarchy with a degree-63 hub verifies that a certificate reads
each endpoint's row once and remains valid. Existing corruption-detection and
exact Matcher rollback tests continue to cover the certificate's correctness
boundary. Durable throughput, allocations, and high-degree tail latency remain
to be measured for both paper modes.
