# Phase 11 — Deterministic replay and historical debugging

**Roadmap coverage:** objective 12.  
**Status:** Partial; bounded durable history and deterministic recovery replay exist, but supported import/replay verification and historical matching queries do not.

## Goal

Make a mutation sequence independently exportable, replayable, and verifiable, with configurable historical access.

## Work

- Define a versioned mutation-log export format with integrity digests and compatibility metadata.
- Add clean-state replay and verification of graph, matching, and committed-version hashes.
- Add checkpoint-assisted replay or a bounded replay contract so startup cost does not grow without an explicit limit.
- Evaluate versioned partner/matching queries with bounded retention; reject unsupported versions clearly.
- Make replay deterministic across fresh processes and supported Python/platform builds.

## Exit evidence

- Export/replay round trips reproduce exact hashes in both modes and reject edited, truncated, reordered, or incompatible logs.
- Historical query tests verify boundary/retention behavior and memory bounds.
- Recovery benchmarks report replay time and memory versus history length.

## Dependencies

Phases 02 and 07; checkpoints depend on phase 01 allocation budgets.
