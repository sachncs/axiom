# ADR 0145: Store proper matchings as compact partner arrays

- Status: implemented; Multilevel constrained qualification remains open
- Date: 2026-10-04

## Context

The matching set held one Python tuple and hash-table slot per matched edge.
For one million vertices, that sparse representation required tens of
megabytes and recovery could fail while allocating it under the 512 MiB
address-space cap.

## Decision

Matcher-owned matching indexes use a fixed-width unsigned partner array when
the state is a proper matching, storing the partner at each matched endpoint
and a sentinel for unmatched vertices. The payload is four bytes per vertex.
An edge-set compatible overflow retains malformed or overlapping edges so
invariant checks can detect invalid state instead of normalizing it away.
Standalone `MatchingIndex` instances keep their sparse representation unless
the caller explicitly enables the disjoint-matching mode.

## Evidence and limits

- Tests cover compact add/discard, promotion from overflow, overlapping-edge
  preservation, deterministic iteration, and exact update rollback.
- Two Linux ARM64 Basic full-cycle repeats pass the 512 MiB memory/disk
  pressure envelope and exact recovery. They measured 28.4–28.6k updates/s.
- Multilevel still reaches the process virtual-address limit near 300k updates
  in the same cycle. This index reduces matching storage but does not resolve
  remaining hierarchy, update-churn, or recovery peaks.

Raw Linux runs are retained in
[`resource-envelope-linux-arm64-local`](../../benchmarks/results/resource-envelope-linux-arm64-local/).
