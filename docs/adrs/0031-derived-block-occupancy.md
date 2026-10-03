# 0031: Derive adjacency-block occupancy from row degree

Date: 2026-10-03. Status: implemented; focused regression and sanitizer
qualification passed; broad repeatability continues.

## Context

Each native adjacency block held four uint32 neighbor IDs, `next`, `previous`,
and a uint32 `used` count: 28 bytes total. In a row's linked chain every block
before the tail is full. Only the tail can be partial, and its occupancy is
determined by the row degree. Retaining another word per block duplicated
information in the already-required dense degree array. For a million-vertex
degree-four graph this cost 4 MB of native arena capacity.

## Decision

Remove `used` from `Block`, reducing its statically asserted layout from 28 to
24 bytes. A live non-tail block has four neighbors; a live tail has
`(degree - 1) % 4 + 1`. Append offsets follow `degree % 4`. Erase first moves the
tail neighbor into the removed slot, decrements the row degree, and unlinks the
tail exactly when the new degree is divisible by four. Released blocks clear
their `previous` link before joining the free list; free-list ownership and row
ownership remain independently audited.

No durable format or checkpoint changes: checkpoints serialize row degree and
neighbors, never arena blocks or allocator metadata. Index locations continue
to identify the block and item offset. All mutation and rollback paths use the
same derived-occupancy rule, including compaction, ring construction, index
activation, restoration, and full validation.

## Evidence and limits

On macOS 26.7.1 arm64 / Python 3.14.8, a million-vertex, two-million-edge
degree-four ring now retains 37,000,264 native bytes in `Packed`, down from
41,000,264 before this layout change. The full matching benchmark retains
41,127,656 initial native bytes, down from 45,127,656, with identical trace
digest and independent proper/maximal matching audit. One short Engine sample
measured 635,995 updates/s versus 662,241/s before; the ~4% difference is one
noisy nondurable run and needs fresh-process repeats before attributing a compute
regression or improvement. Raw current runs:
[storage](../../benchmarks/results/storage/million-derived-occupancy-599.json),
[Engine](../../benchmarks/results/engine/million-derived-occupancy-599.json).

Tests verify degree transitions across four-item boundaries, tail-block release,
free-list reuse, high-degree indexed rows, exact rollback, compaction and
checkpoint round trips. The rebuilt candidate passes 1,176 Python tests plus
ASan/UBSan runs of 200,000 storage edits and 100,000 differential matching edits.
These local checks do not qualify durable service throughput, total RSS,
billion-vertex support, or all graph degree distributions.
