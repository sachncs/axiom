# ADR 0119: Journal System cache rows by inverse delta

Date: 2026-10-04
State: Implemented; high-degree durable qualification remains open

## Context

`Systems.edit()` previously retained `tuple(values)` as the before-image for a
sorted `Lambda`/`L` cache row. The journal charged one cell per copied item
against a fixed 65,536-cell ceiling. A diagnostic one-million-vertex Basic
hub-churn run preloaded a 65,280-spoke hub; the next insert raised
`MemoryError("system journal capacity exceeded")` while admitting the large
row snapshot. Smaller Durable slices could not make that single edit fit. The
committed SQLite prefix remained intact at sequence 65,280, but repeated
rollback recovery made the path expensive. The run was interrupted during
recovery and is retained only as failure evidence, not a performance result.

## Decision

Retain the original map-key state and row object reference, and append one
inverse journal record for each actual sorted-row insertion or deletion. On
rollback, apply these edits in reverse order before restoring original map
keys and System roots. No row-sized tuple or copied integer payload is stored.
No-op edits do not consume delta capacity. Sorted order remains maintained by
the existing `System.change()` primitive.

## Consequences

Undo storage is proportional to actual changed cache cells, not the degree of
the row being edited. This permits a single hub-edge update to fit the default
journal when its actual write set is small. Forward list insertion/deletion
still shifts O(row degree) elements; this decision fixes journal admission and
snapshot memory, not high-degree update time. Batches can still exhaust the
bounded journal through many distinct edits and use Durable's existing
chunk-halving/replay path.

## Verification

Tests edit and exactly roll back a 65,536-entry row under the default journal
limit, verify the original list identity, exercise shared aliases and repeated
inverse operations, and force capacity failure before a delta mutates the row.
The Basic/Multilevel durable suites pass. One million-vertex run in each mode
crossed the former 65,536-cell boundary and recovered exactly after 65,792
operations. Basic measured 1,470 updates/s and 280 s recovery; Multilevel
measured 215 updates/s and 951 s recovery with 1.96 GB peak RSS. These single
runs confirm the capacity fix but are negative performance evidence, not
repeatability or deployment qualification. Raw records are in
[`benchmarks/results/durable`](../../benchmarks/results/durable/README.md).

Follow-up recovery work batches operation-log replay into bounded atomic
Matcher slices and restarts from the beginning with smaller slices when a
paper journal reaches its capacity. Reopening the same retained 65,792-row
databases took 47.6 s for Basic and 152.8 s for Multilevel, versus the original
280 s and 951 s. These are sequential single-run comparisons on the same
workstation and database state, not throughput re-runs or qualification; replay
is still too slow for an acceptable million-vertex recovery objective.
