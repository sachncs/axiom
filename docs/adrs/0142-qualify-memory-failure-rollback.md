# ADR 0142: Exercise paper update rollback under memory exhaustion

- Status: hosted memory-pressure and exact-recovery stage passed; disk gate remains pending
- Date: 2026-10-04

## Context

The prior memory-pressure drill allocated nearly the full 512 MiB address-space
limit, then asked SQLite `wal_checkpoint(PASSIVE)` to raise `MemoryError`.
Checkpointing is a small SQLite maintenance operation, not a paper-state image
allocation, and it did not exercise the update journal. The earlier version
also compared a nonexistent checkpoint-generation status field.

## Decision

The main source graph is certified by the Service audit before backup and by
exact backup restoration after pressure phases. In a separate fresh Durable
store, establish a verified two-operation graph state and prepare a bounded
4,096-operation group of distinct edge insertions absent from the audited ring.
Allocate memory in 64 KiB
chunks until the enforced process limit rejects another allocation, retain
only one 64 KiB chunk of headroom, and submit the whole group. Require an actual
allocator `MemoryError` (or fail-stop when committed-state reconstruction
cannot fit) and reject typed paper-journal-capacity exhaustion as a different
condition. The distinct edges ensure that the workload allocates graph and
paper state rather than repeatedly toggling one already-known edge.
After releasing pressure, require identical durable status and exact independent
matching/topology audit to the pre-update state. If Durable must fail-stop because
it could not rebuild its in-memory state while the address space is exhausted,
release the pressure, reopen the same store, and perform those same checks from
the persisted two-operation prefix.

## Consequences

- The memory qualification now exercises a real multi-update graph transaction,
  its Paper Matcher journal rollback, and unchanged durable operation history.
- The initial one-MiB-headroom probe was too weak: repeated toggles of one edge
  succeeded under pressure. A hosted run exposed that gap; the probe now uses
  out-of-ring edges and only 64 KiB headroom. A review caught and corrected an
  intermediate candidate whose distinct edges were already ring members.
- The first out-of-ring run forced `MemoryError`, but immediate reopen still
  failed while unreachable partially constructed Matcher objects were awaiting
  cyclic collection. The probe now releases the failed Durable owner and runs
  collection before testing exact recovery from disk.
- It avoids replaying the million-operation source history a second time solely
  to seed the isolated memory probe; source integrity is still checked by the
  Service audit and final exact backup restoration.
- It distinguishes actual allocator failure from the repository's typed
  retryable Matcher journal bound.
- A failure at the SQLite persistence boundary is treated as uncertain durable
  state and must survive reopen/recovery validation; it is not reported as a
  clean in-memory rollback.

## Verification

Local logic/type/full-suite checks pass. Earlier hosted attempts exposed two
probe flaws: same-edge requests did not allocate, and the first corrected run
did not collect partially built Matcher state before disk reopen.

The installed Linux run on `bc02b7e` ([resource job 111408654605](https://github.com/sachncs/axiom/actions/runs/37192873974/job/111408654605))
completed the memory stage: the 4,096-edge group hit `MemoryError`, the failed
owner was released, and after cyclic collection the database reopened with the
same status and exact baseline matching/topology digest. The run then failed in
the independent disk-checkpoint stage; this memory result remains valid, but the
overall resource envelope is not qualified.
