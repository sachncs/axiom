# ADR 0006: Introduce an explicitly selected native production matcher

Date: 2026-10-01. Status: explicitly approved; native in-memory core implemented;
first bounded durable layer added; full-service qualification pending.

## Context

The paper engine maintains coloring, Vizing fans, recursive hierarchy, and phase
accounting to investigate a research algorithm. Its current Python implementation
does not claim all paper asymptotic bounds. Those structures, snapshots, and scans
are not necessary to expose a proper maximal matching on the target sparse graph.
Reusing only native adjacency leaves the main update costs intact.

## Decision

Add a **separate, explicitly selected** native incremental maximal-matching
production backend with compact partner state, bounded journals/certificates,
and the durable/query service contract in ADR 0007. The user explicitly approved
this direction rather than requiring optimization only of the existing paper
engine. Keep that engine available; do not secretly fall back or change its mode.

Initial production algorithm direction:

1. On insertion, match the new endpoints if both are free; otherwise retain the
   current matching. The only newly introduced edge is thereby covered.
2. On deletion of an unmatched edge, retain the matching.
3. On deletion of a matched edge, free its two endpoints and deterministically
   rematch each against an available free neighbor. Choose by stable vertex order.
   Removing the matched edge creates only these free vertices; rematching can
   only reduce the free set. After checking their remaining incident edges, no
   uncovered edge can have been introduced elsewhere.

This is a proposed local maximal-matching algorithm, not the paper's routing path
or theoretical bound. Require a formal implementation invariant, native/reference
differential tests, hub/adversarial traces, corruption/failure injection, and full
proper/maximal audits. Deletion may scan large neighborhoods: average degree 4
does not bound maximum degree or p99. Measure that limitation explicitly.

Use compact partner arrays/counters rather than per-vertex Python sets/dicts and
whole-matching copies. Journal every graph/partner/count/version edit and expose
no writable escape hatch that bypasses the owner/certificate boundary. Queries
return one committed version; large enumerations are bounded/versioned.

## Consequences and alternatives

Both backends promise proper maximal matching, but may choose different edges
and have different performance/complexity. Exact historical replay must use a
specified backend/format/algorithm version and deterministic ordering; "same
maximality" does not imply identical output. No maximum-cardinality guarantee is
added. No paper-theorem claim transfers to the production backend.

Optimizing only the paper engine was considered and not selected for this
production target. Arbitrary graph sharding, hidden greedy recomputation on
failure, and eventual matching consistency are not part of this decision.

## Evidence

`axiom.engine.Engine` now implements compact partners, shared graph/partner budget,
joint journals, immediate certificates, independent full audits, private batch
visibility, and bounded/versioned pages. Reference tests exercise deterministic
decisions, proper maximality, budget rejection, and exact batch rollback.
A 100,000-edit differential C++ run passed ASan/UBSan.

Three short million-vertex average-degree-4 runs with real churn and matching
queries produced approximately 686k–720k in-memory updates/s. Exact public-query
graph/matching audits passed. This is compute headroom, **not** durable 10k/s
qualification. See [contracts/results](../engine.md). The separate bounded
[durable layer](../durable.md) adds FULL-WAL commit/replay and retry outcomes;
opt-in native checkpoint/retirement and bounded local aggregation (ADR 0011) are
now implemented. Maintenance/soak and full-service qualification remain pending.
