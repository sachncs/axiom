# Phase 10 — Supported metrics, logs, and alerts

**Roadmap coverage:** objective 11.  
**Status:** Partial; current counters and benchmark histograms do not form a stable observability contract.

## Goal

Provide bounded-overhead operational visibility with stable names, meanings, and units.

## Work

- Define counters/gauges/histograms for updates, queries, batches, latency, queue, rejection, matching/edge/vertex counts, memory, storage/WAL, checkpoints, recovery, rollback, mode, invariant failures, and subscriber lag.
- Add a stable metrics interface and choose compatible Prometheus/OpenTelemetry export boundaries without making exporters mandatory for embedded use.
- Add structured logs with stable event names and correlation/version fields; redact caller identifiers by default.
- Establish actionable warning/critical thresholds from qualification evidence, not guesses.
- Measure observer overhead and ensure collection itself is bounded under load.

## Exit evidence

- Contract tests pin metric names/types/units and structured log schemas.
- Load tests measure overhead and verify metric values against independently counted outcomes.
- Operations documentation links each alert to a tested response procedure.

## Dependencies

Phases 03–04 and 09; expose queue/event lag after those contracts exist.
