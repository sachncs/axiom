# ADR 0133: Store matched-vertex membership in the compact index

- Status: implemented; hosted resource qualification pending
- Date: 2026-10-04

## Context

The latest million-vertex Linux resource run passed recovery and matching
audits, then exhausted its 512 MiB address-space allowance during an ordinary
Packed graph insertion. The `Matcher` retained `matched_vertices` as a Python
set, which stores boxed integers and hash-table slack for a dense universe even
though its hot operations are bounded-universe membership, add, discard, and
iteration. The repository already provides `Vertices`, two fixed-width arrays
using eight bytes per possible label.

## Decision

Initialize `Matcher.matched_vertices` as `Vertices(n)` and construct a fresh
compact index directly in `refresh()`. Do not create an intermediate Python
set. `Views` admits the compact root and retains it through ordinary rollback;
candidate validation verifies each edge's endpoints and partners plus exact
cardinalities without materializing another matched-vertex set. The consistency
audit checks the compact index invariant. `Witness` compares compact partitions
by canonical membership, not their swap-removal iteration order, because that
internal order is not matching state.

`Vertices.add()` appends to its member array before publishing the position
entry. If array growth raises `MemoryError`, the compact index remains
unchanged rather than containing a position for a missing member.

## Consequences

- Dense matched-vertex membership changes from a Python hash set to two
  fixed-width arrays, with storage proportional to the known vertex universe.
- `refresh()` avoids a graph-sized Python set and a conversion peak.
- Matching rollback retains the original compact root and restores logical
  membership without allocating a replacement index.
- The public container's iteration order is not stable across removals; set
  semantics, not incidental iteration order, define this index.
- External callers that relied on undocumented set-only methods such as
  `remove()` must use supported `discard()` / `add()` operations.
- No constrained Linux pass is claimed yet. If the next run still fails in
  Packed insertion, record allocation/RSS at native arena growth thresholds
  before changing its growth policy.

## Verification

The full local suite passes (1,272 passed, 1 optional performance-report test
skipped because `matplotlib` is unavailable). Ruff and mypy pass for the
changed implementation modules. The hosted 512 MiB resource job is the next
qualification gate.
