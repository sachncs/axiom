# ADR 0010: Restore exact native state before retiring replay history

Date: 2026-10-01. Status: native codec and opt-in durable v2 atomic publication,
bounded replay and retry retirement implemented/tested; maintenance-inclusive
performance measured in short staged traces; sustained service qualification pending.

## Context

The first durable format bounds its complete operation history and rejects new
operations at capacity. Replaying forever cannot satisfy sustained service or
bounded recovery. Reconstructing graph edges and selecting a fresh maximal
matching would change exact partners and future repair decisions. A checkpoint
must preserve the specified algorithm state, not merely another valid matching.

## Decision

Provide a separate audited native checkpoint image and candidate restore path.
No `pickle`, pointers, C++ object layout, hash-table buckets, live transaction,
allocator capacity, mutation epoch, or instance transaction tokens enter the
format. They are not portable logical graph/matching state.

Version `AXENG001` uses little-endian unsigned words:

| Field | Width |
| --- | --- |
| Format/backend magic | 8 bytes |
| Fixed vertex universe, reserved zero | 4 bytes each |
| Undirected edge count, logical mutation version, matching edge count | 8 bytes each |
| Per vertex: degree, partner (`UINT32_MAX` = free), then that many neighbors | 4 bytes per word |

Image size is exactly `40 + 8*n + 8*m` bytes. Explicit row lengths/reverse entries
allow direct, bounded native construction without running matching repair on
every restored edge or allocating another per-vertex degree counting array.
This trades image space for straightforward fast restore. Preserve neighbor row
order, though the matching algorithm chooses the minimum free neighbor and does
not depend on that order. Preserve partners/count/version exactly.

`Engine.snapshot(max_bytes=...)` rejects unpublished batches, applies an explicit
output cap before allocating Python bytes, and fully audits before returning an
image. Internal certificate failure poisons the source without changing topology
or logical version. Allocation/capacity rejection does not mutate it.

`Engine.restore(data, budget=..., max_bytes=...)` accepts only immutable bytes,
enforces input cap, validates every count/offset/range before graph assembly,
budgets a separate native candidate, and independently audits duplicates,
symmetry, degrees/edge count, live symmetric partners, matching count, and
maximality before returning it. Do not silently recompute partners to repair
invalid input. A failed candidate cannot change an existing engine.

Native audits reuse a compact row vector for duplicate checking instead of
allocating a hash set and nodes per vertex. Sorting/adjacent comparison retains
duplicate detection; ownership, reverse adjacency, index and accounting checks
remain independent and unchanged. Worst-case sorting work depends on degree.
This is a full-audit allocation optimization, not disabling ordinary certificates.

## Durable integration: explicit v2, not an implicit upgrade

The durable layer verifies an image checksum and binds format/backend,
checkpoint sequence/version, chain anchor, retired floor and retained retry state
before native restore. Structural correctness alone cannot detect a changed but
still-valid version or matching. Checksums detect accidental corruption, not an
adversary able to rewrite all data/checksums; keep the directory private.

Commit the new checkpoint and history retirement atomically in FULL-WAL storage.
After an uncertain publication, fail-stop and let recovery choose the committed
checkpoint/tail—not whichever in-memory state is convenient. Retained operation
outcomes must remain exact; sequences at/below a retired floor must reject as
expired, never be admitted as new mutations. Retirement/window semantics and
capacity are explicit. Do not guess an old successful outcome
after its retry record has been retired.

New stores opt in with a positive `checkpoint_interval`. Existing v1 stores keep
their history cap and two-table format; requesting checkpoint/retention policy on
one refuses recovery. There is no automatic migration. V2 persists interval `I`,
retry retention `R`, batch bound `B`, and operation-table bound `M` in metadata;
require `R >= B` and `I + R + B <= M`. Reopen inherits these values; explicit
conflicting values reject. Defaults are `R=16384`, `B=256`, `M=65536`; the caller
chooses `I`. Native/image/database budgets remain separate limits.

At checkpoint sequence `C`, retire through `F=max(0,C-R)`. Preserve the exact
last `R` outcomes, their checksum chain, the anchor/version at `F`, and the tail
at `C`. Persist one image plus its SHA-256, sequence/version/floor/generation and
certificate; update the control generation and delete retired rows in the same
FULL-WAL transaction. Guard publication against the expected old control record.
Only install the new in-memory floor after known commit. An exception after SQL
begins or during publication disables the owner, even if rollback appears to work.
Recovery, not the failed owner, decides which generation committed.

Before preparing a fresh group, checkpoint when the committed suffix has reached
`I`; an explicit `checkpoint()` also exists. Maintenance does not change graph
version or partners. Validate request/retry admission first. A successful
maintenance transaction may retire old retries even if the subsequent new group
fails native preparation; these are distinct transactions, not an assertion that
the entire `apply` call made no persistent change. Pre-SQL allocation failure
leaves a healthy owner reusable; native certificate failure still fails closed.
The owner gate covers maintenance: other calls get `BusyError`, not partial state.

Recovery checks generation/record count, metadata policy, image length/type,
retained row count and all digest boundaries before native candidate publication.
Restore exact graph/partners from the image; verify the retained pre-checkpoint
cache's sequence/version/checksum progression without reapplying it; replay only
the suffix after `C` and compare actual outcomes, then independently audit the
complete recovered graph/matching. Cached outcomes before `C` are integrity-bound,
not independently replayed from a now-retired genesis prefix. SHA-256 does not
authenticate against a writer who can replace the database and recompute hashes.

Retries at/below `F` raise `ExpiredError`; they never become fresh mutations or
invented acknowledgments. Callers must reconcile uncertainty inside the retained
window, size it for their retry/in-flight policy, and handle expiration explicitly.
Image admission prevents growth beyond `max_snapshot_bytes` before edits, with
exact bounded simulation near capacity so duplicates/no-ops remain admissible.
SQLite page exhaustion during checkpoint fails closed; recovery keeps the prior
committed prefix if the new checkpoint did not commit. Retirement bounds logical
rows/replay, not physical file size: SQLite can retain reusable pages and WAL.

Checkpoint copies, old/new candidate coexistence, SQLite binding/WAL buffers,
audit scratch, pause/queue time and maintenance cost count toward qualification.
A bounded portable codec is not evidence that durable compaction or sustained
10k/s has been qualified. The first durable format's history limit remains intact.
V2 removes that lifetime sequence limit through tested retirement, not by lifting
the operation-table cap or claiming maintenance is free.

## Evidence and limits

Property/reference tests verify exact state and future repairs. Malformed headers,
counts, offsets, partners, neighbors, duplicates/asymmetry, uncovered edges,
byte/native budgets and unpublished export are exercised. Valid alternative
matching images retain their supplied partners rather than recomputing them.
ASan/UBSan includes checkpoint round trips during 100,000 differential edits,
2,000 mutated images, and corrupt source export/fail-stop. Independently certified
million-vertex images are documented in the [historical checkpoint reports](../../benchmarks/results/checkpoint/README.md); the native Engine codec itself was removed from the product on 2026-10-04.

The 29 focused durable-checkpoint tests cover repeated compaction beyond the table
cap, exact graph/partner recovery and retained retries, expired IDs, policy
inheritance/refusal, checksum/cache corruption, byte admission, 500 differential
edits, pre-persistence allocation failure, SQLite disk-full and guarded publication
failure, checksum-valid invalid partners, corrupt live history before retirement,
and fail-fast query isolation during maintenance. Process-death tests interrupt
the prepared image/control/delete transaction
before COMMIT and after COMMIT/installation; recovery exposes the old or new
generation atomically. These are process-crash tests, not device power-cut proof.

Maintenance-inclusive million-vertex traces (`525cbca`, three seeds) acknowledge
200k real changes, issue 100k queries and publish six native checkpoints each:
27.6k–28.5k changes/s, 14.2–15.0 ms ack p99, but 193–204 ms maximum. A checkpoint
group is less than 1% of groups, so p99 alone obscures this tail. Queries occur
after acknowledgment; no concurrent queue wait is measured. Results motivate
bounded client aggregation (now ADR 0011) and further maintenance/query scheduling,
not a claim of
full qualification. Exact audits/recovery/retained retry/expiration pass; command,
hardware, raw records and limits are in [durable contracts](../durable.md).

Default input/output caps are 64 MiB. Bytes, candidate coexistence, and audit
scratch are additional to each engine's native container budget; this is not a
hard service RSS limit. Instance-local journals/tokens are not resumed from an
image. No compressed image, historical query retention, live database backup,
automatic format migration or maintenance-inclusive throughput SLA is claimed.
