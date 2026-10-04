# Phase 04 — Service deployment and operational qualification

**Roadmap coverage:** objective 4.  
**Status:** Partial; sustained production-shaped and storage-operational gates remain open.

## Goal

Define and verify the supported deployment envelope for the durable threaded Service.

## Work

- Run sustained skew/burst and long-duration workloads while measuring aggregate process RSS, Python/native allocations, SQLite page cache, database size, and WAL growth.
- Exercise disk quota/full behavior, checkpoint contention, realistic storage errors, clean shutdown, restart, and bounded recovery.
- Specify sizing guidance, filesystem requirements, WAL/checkpoint limits, alert thresholds, retry/idempotency guidance, and overload behavior.
- Integrate transport only after local semantics pass; defer hardware power-loss drills for this version and state the exact limitation.
- Preserve exact acknowledged-prefix recovery and reject uncertain reads after failed commits.

## Exit evidence

- Repeated operational runs for both modes with retained resource reports and no unbounded queue, WAL, memory, or recovery growth.
- Tested runbook for disk-full, restart, checkpoint, overload, and recovery incidents.
- Published supported operating envelope with exclusions clearly labeled; no claim of billion-node capacity without evidence.

## Dependencies

Phases 01–03 and 07–10; transport depends on phase 12. Hardware power-loss remains deferred, not a passing gate.
