# ADR 0010: Restore exact native state before retiring replay history

Date: 2026-10-01. Status: native checkpoint codec implemented/tested;
durable publication, replay compaction and dedup retirement pending.

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

## Durable integration contract (not implemented yet)

The durable layer must verify an image checksum and bind format/backend,
checkpoint sequence/version, chain anchor, retired floor and retained retry state
before native restore. Structural correctness alone cannot detect a changed but
still-valid version or matching. Checksums detect accidental corruption, not an
adversary able to rewrite all data/checksums; keep the directory private.

Commit the new checkpoint and history retirement atomically in FULL-WAL storage.
After an uncertain publication, fail-stop and let recovery choose the committed
checkpoint/tail—not whichever in-memory state is convenient. Retained operation
outcomes must remain exact; sequences at/below a retired floor must reject as
expired, never be admitted as new mutations. Retirement/window semantics and
capacity must be explicit before release. Do not guess an old successful outcome
after its retry record has been retired.

Checkpoint copies, old/new candidate coexistence, SQLite binding/WAL buffers,
audit scratch, pause/queue time and maintenance cost count toward qualification.
A bounded portable codec is not evidence that durable compaction or sustained
10k/s has been delivered. The first durable format's history limit remains intact
until the new atomic checkpoint/recovery protocol is tested.

## Evidence and limits

Property/reference tests verify exact state and future repairs. Malformed headers,
counts, offsets, partners, neighbors, duplicates/asymmetry, uncovered edges,
byte/native budgets and unpublished export are exercised. Valid alternative
matching images retain their supplied partners rather than recomputing them.
ASan/UBSan includes checkpoint round trips during 100,000 differential edits,
2,000 mutated images, and corrupt source export/fail-stop. Independently certified
million-vertex images are measured in [checkpoint contracts](../checkpoint.md).

Default input/output caps are 64 MiB. Bytes, candidate coexistence, and audit
scratch are additional to each engine's native container budget; this is not a
hard service RSS limit. Instance-local journals/tokens are not resumed from an
image. No compressed image, historical query retention, live database backup,
durable codec publication, or automatic format migration is claimed here.
