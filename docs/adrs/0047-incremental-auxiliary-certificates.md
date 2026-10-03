# ADR 0047: Incremental paper auxiliary-index certificates

Date: 2026-10-03

## Context

After ADRs 0045 and 0046 removed the per-update full hierarchy audit and global
maximality scan, a 512-vertex cProfile attributed 30.8% of cumulative update
time to `Matcher.__check_auxiliary_indexes()`. That validator rebuilt expected
inserted-edge incidence, S-hat, H/reverse-H and H-tilde/reverse-H-tilde tables
from all active state after each mutation.

## Decision

- Track graph/matching affected vertices and journaled changes to inserted edges,
  bad-vertex membership, H rows, reverse-H target rows, H-tilde edges and
  reverse-H-tilde target rows in the existing `Auxiliary` transaction owner.
- Certify changed inserted-edge incidence against both endpoint buckets;
  validate affected buckets contain only live inserted edges incident to that
  vertex; validate H rows against the live graph and active System Lambda rows;
  validate reverse membership for every old/new target of a changed H source;
  and validate S-hat for affected matching endpoints.
- Validate H-tilde directed edges and reverse entries for changed inserted
  edges, touched endpoint incident edges, changed H-tilde cells, and vertices
  whose matching/bad status changed.
- When auxiliary roots or the active System are replaced, run the complete
  reconstruction audit before publication. Keep the independent full checker
  callable to tests and verification tools.
- Make generated-update tests run the full independent auxiliary oracle after
  every operation. Inject an omitted incident-index write and require exact
  transaction rollback.

This is inductive: the prior committed indexes are valid; only graph/matching
endpoints, inserted-edge endpoints, changed bad vertices and journaled rows can
change their defined relations. The candidate rows are checked against the
authoritative graph/System and old/new reverse dependencies. No index check is
sampled or disabled. The full reconstruction remains an independent oracle at
replacement boundaries and throughout generated test traces.

## Alternatives considered

- Rebuild every expected index after each update: correct but scans unrelated
  vertices/edges and duplicates derived state; measured as the leading cost.
- Remove validation entirely: rejected; the transaction still needs to reject
  an omitted or inconsistent touched row before publication.
- Sample a subset of rows: rejected because a missed stale reverse entry could
  corrupt rematching decisions.
- Allocate a second full outgoing H-tilde index: rejected for now because it
  increases persistent memory to avoid a scan; local certificates use the
  existing incident inserted-edge index instead.

## Evidence

[`auxiliary-certificates.json`](../../benchmarks/results/paper/auxiliary-certificates.json)
records baseline `6668b6d` and the candidate on the same seeded 8,192-vertex
average-degree-four multilevel trace (128 updates, five timing batches). Rate
rises from 228.92 to 436.54 updates/s (1.91×), with identical final graph and
matching certificate hashes and identical repair/rebuild counters. A separate
512-vertex profile falls from 0.1423 to 0.1035 profiled seconds for 128 updates
(27.3%). This is diagnostic only; transient traced bytes and single-sample RSS
are effectively unchanged. No million-vertex, durable or release guarantee is
implied.

The full local suite passes 1,214 tests. Property-generated traces call the
complete auxiliary checker after each operation; adversarial 1,000-update
multilevel traces and injected missing-index rollback are included.

## Consequences

Ordinary update validation is proportional to touched index rows and endpoint
incidence rather than a reconstruction of every paper auxiliary structure.
High-degree endpoints and large inserted-edge incidence still cost work. Phase
rebuilds retain global checks. This decision reduces compute, not retained
storage. The next profiled costs are atomic journal admission/cleanup, stale
matching cleanup, graph lookups and System journal validation; durable paper
integration and state-sized snapshot/admission migration remain active
engineering work.
