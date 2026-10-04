# Phase 08 — First-class bipartite API

**Roadmap coverage:** objective 9.  
**Status:** Not implemented.

## Goal

Offer a domain-friendly worker/job-style API without changing the core undirected maximal-matching contract.

## Work

- Define typed left/right partitions and deterministic validation for same-side edges.
- Reuse durable external IDs and internal compact integer mapping.
- Define behavior for vertex lifecycle, batches, snapshots, recovery, and concurrent reads.
- Keep the adapter thin and avoid duplicating matching state or bypassing the Service transaction boundary.

## Exit evidence

- End-to-end tests cover legal/illegal edges, arbitrary IDs, durable recovery, atomic batches, queries, and lifecycle behavior.
- Differential tests show the bipartite adapter produces the same underlying graph and matching state as equivalent core operations.
- API docs clearly state that maximal matching is not maximum-cardinality matching.

## Dependencies

Phases 05–07; do not introduce an independent durable store.
