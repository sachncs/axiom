# 0030: Size committed-partner indexes to the active batch

Date: 2026-10-03. Status: implemented and locally qualified; wider durable
service performance remains part of the active repeatability work.

## Context

ADR 0012 added a dense `uint32` first-write slot for every vertex so readers can
obtain a coupled committed `(version, partner)` during a private mutation batch.
That gives constant-time lookup, but permanently spends 4 bytes per graph
vertex even when no transaction is active. At one million vertices this is
4,000,000 bytes of idle native allocation, separate from partners, adjacency,
the free-vertex bitmap, and SQLite. The committed-view guarantee does not need
an entry for an untouched vertex or a whole-graph snapshot.

## Decision

Keep the existing owner journal as the source of old partner values, but map
only vertices touched by the active batch. `FirstWrite` uses a small inline
open-addressed table for up to eight distinct vertices and grows by powers of
two while maintaining at most 50% occupancy. Hash slots store a vertex and its
earliest journal position. Commit and rollback clear the active map without
allocating; the highest allocated table capacity is retained and reused. The
map is auxiliary and never enters the portable checkpoint format.

Table growth is admitted against the shared native budget with old/new buffer
coexistence included. If admission or allocation fails after a graph edit has
begun, the ordinary batch rollback restores graph, partners, version, and
publication state. `Engine.check()` independently verifies occupied slots,
journal references, load-table invariants, and the first-write relation for all
journal entries. The native binding continues to retain the GIL for a coupled
read; this decision does not turn the C++ engine into a concurrent-writer API.

## Evidence and limits

A fixed 20,000-pair, one-million-vertex, average-degree-four native matching
trace on macOS 26.7.1 arm64 / Python 3.14.8 produced the same deterministic
trace digest and passed its independent matching audit. The dense-index run
reported 49,127,520 initial native bytes and 671,882 updates/s; the sparse-index
run reported 45,127,656 bytes and 662,241 updates/s. This is 3,999,864 fewer
initial bytes (8.1%) and a 1.4% lower single-run measured rate. The short
nondurable benchmark is noisy and does not establish a durable throughput or
tail-latency result; broader fresh-process repeats remain required. The full
candidate sample is retained at
[sparse-firstwrite-million-599.json](../../benchmarks/results/engine/sparse-firstwrite-million-599.json).

Regression coverage crosses hash-table growth and 256-vertex ID ranges,
checks that private partner values remain unpublished, rolls batches back and
commits them, and injects native-budget exhaustion during sparse-index growth
to require exact batch rollback and stale-token rejection. The complete Python
suite passes 1,175 tests on the rebuilt extension. Address/undefined-behavior
sanitizers pass 200,000 storage edits and 100,000 differential matching edits.

Large transactions can grow the table in proportion to their touched vertex
count and retain that high-water capacity. It remains subject to the native
budget, but is not automatically shrunk after commit. This improves idle and
ordinary small-batch memory; it is not an unbounded-transaction guarantee or a
billion-vertex support claim. Durable history, paper-engine persistence, total
RSS, and sustained service qualification are unchanged.
