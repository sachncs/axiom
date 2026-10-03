# 0032: Bit-pack adjacency ownership in full audits

Date: 2026-10-03. Status: implemented; native boundary, corruption, differential,
and rollback tests passed.

## Context

`Store::check()` independently verifies that every adjacency block belongs to
exactly one row or the free list. Its `vector<uint8_t>` ownership scratch used
one byte per block during a full audit. The retained graph budget intentionally
does not include this temporary allocation, so a large audit could add a
substantial process-memory peak even when the stored graph fit its budget.

## Decision

Track ownership in a dedicated `BlockOwners` bitset. Claiming an out-of-range
block fails, claiming a block twice fails, and completion requires every valid
bit—including the partially used final word—to be set. The payload is
`ceil(block_count / 64) * 8` bytes, an 8× reduction from the former byte map.
The audit still independently traverses row and free lists and rejects
duplicate, missing, or invalid ownership. The bitset is audit scratch, not
retained graph state, and remains excluded from `memory()` and the native graph
budget.

## Verification and limits

Native tests cover empty and partial-word maps, word boundaries, duplicate and
out-of-range claims, incomplete ownership, and a deliberately corrupted Store
with two rows sharing one block. The focused Python storage suite and the
200,000-edit native differential/rollback test pass. Peak process RSS for a
large full audit is still workload- and allocator-dependent; this change does
not impose a process RSS cap or qualify billion-vertex graphs.
