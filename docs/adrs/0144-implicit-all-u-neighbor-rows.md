# ADR 0144: Use graph rows for large all-U Lambda indexes

- Status: implemented; constrained Linux recovery qualification pending
- Date: 2026-10-04

## Context

For a sparse `Packed` graph with degree below `z`, the exact System partition is
`A = B = ∅`, `U = V`, and `M = ∅`. In that state, every Lambda row equals the
graph's own sorted neighbor row. Materializing a Python map and one fixed-width
array per vertex duplicates adjacency storage and caused Basic recovery indexing
to fail under the hosted 512 MiB limit.

## Decision

For `Packed` graphs with at least 65,536 vertices, represent Lambda implicitly
when the System has no A/B vertices and U contains the full universe. Reads use
the live graph neighbor cursor, so update and delete transitions stay current
without cache-row edits. Structural System checks validate the all-U shape;
`check_lambda()` validates the implicit representation without rebuilding a
second adjacency copy. Materialized Lambda/L maps remain in use for other
partitions and for smaller graphs.

Immutable Multilevel phase-base Systems may also omit mutable cache rows when
the degree cap proves the all-U case. Refinement copies only their structural
partition and matching roots. The normal mutable level continues to satisfy the
full System and hierarchy certificates.

## Evidence and limits

- Two profiled one-million-vertex, two-million-edge macOS arm64 startup samples
  per mode completed with constructor certificates enabled. With `tracemalloc`,
  Basic peak RSS was 191.3 MB and Python peak allocation was 58.2 MB; Multilevel
  peak RSS ranged from 245.6 to 254.7 MB and Python peak allocation was 64.4 MB.
- `System.index()` completed in under 0.1 ms in these all-U samples because it
  retained no duplicate rows. Each result includes stage timing, RSS, and
  traced allocations in the linked raw records.
- Two fresh-process durable repeats per mode also applied 16 uniform updates,
  checked partner queries, backup/retry behavior, and exact recovery. They
  measured 1.12–1.32k updates/s Basic and 1.41–1.94k updates/s Multilevel, with
  260.7–266.6 MB and 419.6–421.3 MB process peak RSS respectively. The short
  trace verifies correctness and recovery only; it is not sustained throughput
  evidence.
- A longer two-repeat run applied 256 uniform updates per sample with partner
  queries and exact replay. Basic measured 8.32–9.94k updates/s at 261.1 MB peak
  RSS; Multilevel measured 11.31–11.42k/s at 420.8 MB. This is one-seed macOS
  evidence and omits the 512 MiB cap, pressure stages, and sustained workload;
  it does not close either mode's qualification gate.
- These measurements are diagnostic only: they are from macOS with tracing,
  not the installed Linux 512 MiB address-space and disk-pressure qualification.
  Recovery, adversarial high-degree cases, and operation throughput remain open.
- The phase-base overlay supplies the edge stream for the hierarchy graph,
  and the synchronized hierarchy root is retained as the phase base after
  rebuild.
  `phase_graph` and `phase_base_graph` therefore alias when the parent phase is
  stable; child refinement still creates detached projected graph roots.

The retained startup and durable records are in
[`memory-profile-macos-2026-10-04-summary.json`](../../benchmarks/results/paper/memory-profile-macos-2026-10-04-summary.json)
and [`million-implicit-all-u-macos`](../../benchmarks/results/repeatability/million-implicit-all-u-macos/summary.json).
The longer update records are in
[`million-implicit-all-u-128-macos`](../../benchmarks/results/repeatability/million-implicit-all-u-128-macos/summary.json).
