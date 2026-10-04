# Phase 12 — Matching explanations and stable transport

**Roadmap coverage:** objectives 13 and 15.  
**Status:** Neither surface is implemented; transport must follow local semantics.

## Goal

Expose truthful algorithmic repair explanations and, only afterward, an optional production transport that preserves the embedded Service contract.

## Work

- Record bounded, version-linked repair facts: trigger, previous/current partner, candidates considered, and relevant mode-specific algorithm state.
- Ensure explanations are factual, deterministic, privacy-conscious, and do not claim business intent.
- Define bounded HTTP/gRPC request sizes, authentication integration points, idempotency, retry/error classification, backpressure, snapshots, and event streaming.
- Keep network handlers thin; all updates and reads must flow through the same durable Service APIs.
- Test client disconnects, retries, overload, partial failures, and version consistency.

## Exit evidence

- Explanation tests compare returned facts to recorded operations and algorithm instrumentation, including unavailable/truncated details.
- Transport end-to-end tests prove duplicate-safe retries, atomic batches, coherent reads, stream resumption, auth hooks, and overload behavior.
- Benchmarks demonstrate bounded transport overhead and no loss of local API guarantees.

## Dependencies

Explanations depend on phases 02 and 11; transport depends on phases 04, 07, 09, 10, and 11. Do not start transport implementation before these semantics stabilize.
