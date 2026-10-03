# 0101: Clear paper fan indexes by replacing roots

Date: 2026-10-04. State: implemented; component-level allocation improvement.

## Context

Sparsify-Types and Extend replaced their caller-owned fan collection by
materializing `tuple(fans)` and discarding every fan individually. This made a
full sorted fan snapshot and replayed every membership deletion even though the
resulting collection was immediately repopulated.

## Decision

`Fans.clear()` now swaps the six index roots for empty containers. When a
`FanJournal` is active, it captures those roots before replacement. The old
containers are left untouched, so rollback restores exact contents and object
identity; successful commit releases them when no enclosing journal retains
them. The operation is O(1) in the number of fans, excluding allocator costs.

Sparsify-Types and Extend use this operation for whole-collection replacement.
Selective invalidation continues to remove individual fans because those
operations must evaluate each candidate.

## Verification and limits

Tests cover clear without a journal and clear/add under nested journals with an
inner commit followed by outer rollback. They compare the complete Witness and
all original root identities. Focused paper tests exercise the affected
Sparsify-Types and Extend paths. This removes a full fan snapshot and discard
pass; it is not an end-to-end throughput qualification.
