# Phase 05 — Durable external identifiers

**Roadmap coverage:** objective 5.  
**Status:** Partial; typed mappings exist, but installed-package and sustained recovery qualification is incomplete.

## Goal

Provide stable caller-facing string, UUID, and signed-64-bit integer IDs while retaining compact internal vertices.

## Work

- Verify deterministic mapping, indexed lookup, persistence, schema-version migration, and immutable/no-reuse semantics.
- Define mapping behavior on failed updates, recovery, duplicate registration, and future vertex lifecycle operations.
- Test schema corruption and incompatible data; prevent mapping changes from diverging from edge/matching commits.
- Measure lookup latency and mapping storage overhead at realistic scale.

## Exit evidence

- Fresh-process tests prove exact external↔internal mapping and edge/query behavior after restart and migration.
- Negative and transactional tests cover duplicate IDs, malformed IDs, rollback, corruption, and exhaustion boundaries.
- Installed-wheel tests and bounded memory/latency results are retained.

## Dependencies

Phase 02 durable compatibility rules; coordinate ID lifecycle with phase 06.
