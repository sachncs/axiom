# Phase 06 — Dynamic vertex lifecycle

**Roadmap coverage:** objective 6.  
**Status:** Not implemented; the current universe is fixed at construction.

## Goal

Add vertices and remove them atomically without requiring callers to predeclare the entire universe.

## Work

- Specify allocation, stable identity, deletion, and ID non-reuse semantics.
- Define deterministic incident-edge removal, matching repair, durable journaling/recovery, and rollback behavior.
- Coordinate external-ID mappings and concurrent query visibility.
- Retain fixed-size compact storage as an optional optimized mode only if both contracts remain explicit.
- Set capacity/admission bounds so vertex growth cannot bypass graph, memory, or durable limits.

## Exit evidence

- Property and data-flow tests cover add/remove across isolated, matched, high-degree, and repeatedly reused identity cases.
- Injected failures at each durable and in-memory transition restore exact graph, matching, mappings, and query version.
- Concurrent readers observe documented committed state; recovery reconstructs lifecycle history exactly.

## Dependencies

Phase 05 identity lifecycle; phases 02 and 07 transaction/recovery semantics.
