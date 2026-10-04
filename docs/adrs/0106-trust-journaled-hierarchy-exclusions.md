# ADR 0106: Skip repeated validation of journaled hierarchy exclusions

- Status: implemented; full paper-mode qualification remains open
- Date: 2026-10-04

## Context

During an ordinary Multilevel insert or delete, Matcher passes its current
inserted-edge overlay `E_I` to `Hierarchy.sync_graph` with exactly one
`changed_edge`. The hierarchy then updates the phase graph and endpoint rows
incrementally. Before reaching that local branch, it also traversed and
validated every edge in `E_I`, making the ostensibly local update O(|E_I|).
As the phase overlay grows, repeated validation can accumulate quadratic work.

## Decision

Add an explicit `journaled` contract. Matcher sets it only while
calling the incremental changed-edge branch with its own Auxiliary-journaled
`inserted_edges`. That branch validates the changed edge and endpoint delta,
but does not rescan unrelated overlay entries. Direct/untrusted callers retain
complete exclusion validation by default. Full synchronization/rebuilds always
validate every exclusion regardless of the flag. Existing Auxiliary and
Hierarchy journals still roll back the edge and all index changes atomically.

## Consequences

- Matcher-managed incremental phase synchronization no longer performs work
  proportional to accumulated unrelated inserted edges.
- The trust boundary is explicit in the call signature; arbitrary callers do
  not receive the unchecked fast path accidentally.
- Full rebuild and direct-call validation remain exhaustive. Invalid current
  edges still fail local validation, while owner-managed exclusion mutations
  remain covered by the auxiliary journal and update certificates.
- A regression supplies an exclusion set that raises if iterated and verifies
  the incremental branch never traverses it. This proves scan avoidance, not a
  throughput gain or weaker-boundary equivalence for out-of-band state edits.

## Evidence

Focused validation: hierarchy and System delta tests pass, including malformed
direct-call exclusions, malformed changed edges, and rollback-sensitive Matcher
updates. No isolated before/after timing is published; multi-level durable
performance and memory qualification remain open.
