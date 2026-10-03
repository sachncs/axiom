# ADR 0046: Local maximality certificates for incremental updates

Date: 2026-10-03

## Context

After the per-update hierarchy audit was removed (ADR 0045), paper Matcher
updates still called `is_maximal_matching()` over the complete live graph at the
end of every update, and deletion repair also repeated that scan. The function
is an excellent independent audit, but this routine traverses unrelated edges
for a mutation that touches one edge and a bounded set of matching endpoints.
The existing `Views` first-write journal already records every matched endpoint
edited by the transaction.

## Decision

- Record both endpoints of each live topology edit and each matching-view edit
  in the active `Views` transaction.
- At successful transaction completion, for every affected endpoint that is
  currently unmatched, inspect its live neighbors and reject if any neighbor is
  also unmatched. The matching journal independently checks all modified edge,
  vertex, and partner cells.
- Retain the full maximality check when the transaction replaces matching-view
  roots with a rebuilt candidate. Keep full checks on construction/rebuild paths
  and keep the public `Matcher.maximal()` operation unchanged.
- On certificate failure, raise before publication so existing owner journals
  restore exact matching and graph state. Do not sample or disable the check.

The certificate is complete by induction. Before an update the matching is
maximal. An insertion can create a newly uncovered edge only at its two
endpoints; a deletion can expose a free endpoint only at its endpoints; and any
repair mutation can expose an endpoint only where a matching view changed. All
such vertices are included in the affected set. An edge between two free
vertices must therefore be incident to an affected free vertex and is found by
its neighbor scan. Candidate replacement bypasses this local proof and uses the
full checker.

## Alternatives considered

- Keep full scans on every update: rejected because profile and benchmark show
  avoidable graph-size work after each local mutation.
- Remove maximality validation: rejected; injected skipped-repair tests must
  still fail atomically.
- Sample vertices or edges: rejected because sampling can miss a newly
  uncovered edge.
- Use only matching-cell consistency: rejected because a proper matching can
  still be non-maximal.

## Evidence

[`local-maximality.json`](../../benchmarks/results/paper/local-maximality.json)
records a same-host comparison against `4ab447c`: 8,192 vertices, sparse target
degree four, deterministic churn, multilevel mode, seed 42, 128 real updates,
five batches. Update rate rises from 148.65 to 228.92/s (1.54×). The final graph
digest and matching certificate are unchanged; phase/subphase rebuild and scan
counters match. This is one bounded diagnostic, not production or million-vertex
qualification. Measured transient memory is effectively unchanged; this
decision is a compute optimization, not a storage reduction.

An injected missed-rematch failure verifies the certificate rejects the
resulting free-free edge and the complete Matcher Witness is exactly restored.
A guard test verifies an ordinary update does not invoke the whole-graph
maximality helper. The full regression suite passes. A separate 512-vertex
profile attributes 30.8% of profiled cumulative time to the remaining
`__check_auxiliary_indexes()` full audit; incremental auxiliary certification is
the next measured target. Profile timings are diagnostic, not throughput claims.

## Consequences

Ordinary updates now pay for changed endpoint neighborhoods rather than all
graph edges for maximality. High-degree changed endpoints still require
degree-proportional work, as correctness demands. Full independent checking
remains available and is retained at rebuild boundaries. No retained-storage
claim follows from this change.
