# Phase 02 — Durable Basic and Multilevel recovery contract

**Roadmap coverage:** objective 2.  
**Status:** Implementation exists; independent qualification and paper-state checkpoint decoding remain open.

## Goal

Ensure persisted mode identity and recovery are exact, bounded, versioned, and fail closed for both supported paper modes.

## Work

- Specify durable compatibility metadata and corruption/incompatibility behavior for Basic and Multilevel.
- Preserve mode-specific journals and invariant audits; reject reopening a database in a different mode.
- Add a versioned paper-state checkpoint codec/decoder for graph, matching, hierarchy, coloring/fan state, and auxiliary indexes—or formally prove and document why deterministic replay is the chosen bounded alternative.
- Bound retained-history replay cost and verify recovery at phase/subphase boundaries and after partial durable batches.
- Keep removed native matcher and compatibility-shim behavior out of the supported path.

## Exit evidence

- Fresh-process restart tests compare exact logical state, partner results, mode metadata, and deterministic hashes for both modes.
- Negative tests reject truncated, corrupted, unsupported-version, and cross-mode persisted data without serving reads.
- Checkpoint and replay recovery benchmarks publish time, memory, and retained-history scaling.

## Dependencies

Phase 01 resource work; coordinate batch durability work in phase 07.
