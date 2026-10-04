# ADR 0142: Exercise paper update rollback under memory exhaustion

- Status: implemented; hosted rerun pending
- Date: 2026-10-04

## Context

The prior memory-pressure drill allocated nearly the full 512 MiB address-space
limit, then asked SQLite `wal_checkpoint(PASSIVE)` to raise `MemoryError`.
Checkpointing is a small SQLite maintenance operation, not a paper-state image
allocation, and it did not exercise the update journal. The earlier version
also compared a nonexistent checkpoint-generation status field.

## Decision

First independently verify the million-update source digest. In a separate
fresh Durable store, establish a verified two-operation graph state and prepare
a bounded 4,096-operation alternating edge group. Allocate memory until the
enforced process limit rejects another allocation, retain only one MiB of
headroom, and submit the whole group. Require an actual allocator `MemoryError`
and reject typed paper-journal-capacity exhaustion as a different condition.
After releasing pressure, require identical durable status and exact independent
matching/topology audit to the pre-update state. If Durable must fail-stop because
it could not rebuild its in-memory state while the address space is exhausted,
release the pressure, reopen the same store, and perform those same checks from
the persisted two-operation prefix.

## Consequences

- The memory qualification now exercises a real multi-update graph transaction,
  its Paper Matcher journal rollback, and unchanged durable operation history.
- It distinguishes actual allocator failure from the repository's typed
  retryable Matcher journal bound.
- A failure at the SQLite persistence boundary is treated as uncertain durable
  state and must survive reopen/recovery validation; it is not reported as a
  clean in-memory rollback.

## Verification

Local logic/type/full-suite checks pass, but this probe requires the hosted
Linux 512 MiB address-space run. Record the exact failure phase, status, digest,
and whether recovery was necessary before claiming qualification.
