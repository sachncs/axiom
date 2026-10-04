# Phase 09 — Versioned event and change subscriptions

**Roadmap coverage:** objective 10.  
**Status:** Not implemented.

## Goal

Let clients consume committed matching and graph changes without unbounded polling or memory retention.

## Work

- Specify event types, stable identity, graph version, deterministic order, and previous/new values.
- Define delivery contract (at-least-once or equivalent), duplicate handling, resumption cursor, and recovery-completed events.
- Bound subscriber queues and lag; define overflow, disconnect, and overload signaling.
- Publish events only for durable committed changes, including atomic batches as one coherent version.
- Include vertex events when phase 06 is available; keep event state consistent with external IDs.

## Exit evidence

- Fault-injection tests cover crash between commit and delivery, duplicate delivery, reconnect/resume, and slow consumers.
- Queue bounds hold under sustained overload; event order and version align with durable history and query snapshots.
- Both modes produce identical event semantics for equivalent logical commits.

## Dependencies

Phases 02, 05–07, and 10; event publication must not weaken commit durability.
