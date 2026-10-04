# Phase 07 — Atomic update batches and version-coherent reads

**Roadmap coverage:** objectives 7 and 8.  
**Status:** APIs are implemented; independent scale, overload, and memory qualification remain open.

## Goal

Make bounded update batches atomic at one durable commit boundary and make multi-query reads observe one committed version.

## Work

- Test deterministic operation ordering, contiguous sequence enforcement, idempotent retries, and single-version publication.
- Inject algorithm, journal-capacity, SQLite, disk-full, and cancellation failures at every batch position; verify all-or-nothing state.
- Bound batch operation count, bytes, queue residence, and temporary journal memory; qualify efficient micro-batching.
- Test concurrent snapshot reads while batches commit, and define version behavior for errors/rejections.
- Keep snapshots bounded point-in-time results unless a separately budgeted retained-state model is introduced.

## Exit evidence

- Both modes pass randomized and adversarial multi-operation rollback/recovery tests with exact pre/post hashes.
- Concurrent readers never mix versions; retries produce the same durable outcomes.
- Repeated load tests report batch throughput, tail latencies, memory, queue depth, and rejection behavior at capacity.

## Dependencies

Phases 01–02; phase 06 extends the same atomic boundary to vertex operations.
