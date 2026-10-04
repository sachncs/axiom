# ADR 0134: Batch million-vertex recovery verification

- Status: implemented; constrained hosted rerun pending
- Date: 2026-10-04

## Context

After compacting the matched-vertex index (ADR 0133), the installed Basic
million-vertex growth/drain resource worker no longer failed at graph
insertion, but exceeded its 300-second deadline during recovery verification.
Inspection found that each full `Audit.verify()` made millions of separate
`partner()` and `has_edge()` calls, each acquiring the Durable owner lock. The
growth/drain cycle repeats this audit across pressure, retry, reopen, and backup
phases. The worker's timeout therefore did not isolate update time or indicate
a graph-memory failure.

## Decision

Read partner indexes and graph topology in bounded `Durable.read_snapshot()`
calls, pinned to the expected committed version and limited by `MAX_READS`.
Retain the independent checks for partner range/symmetry, exact optional
matching references, proper matched edges, expected ring topology, maximality,
matching cardinality, state certificate, digest, and idempotent/conflicting
retry behavior. Use a fixed-width partner buffer to avoid retaining a second
million-object Python integer list during verification.

## Consequences

- The verifier takes coherent bounded snapshots rather than making millions of
  separately locked calls; it does not change production update behavior or
  weaken version checks.
- Read query counts and temporary state remain bounded per chunk.
- Existing exact recovery and negative corruption checks exercise both batched
  result paths.
- The hosted resource worker must rerun before claiming the 512 MiB/resource
  gate; this verifier change does not constitute throughput qualification.

## Verification

All 47 `tests/test_resource_envelope.py` tests pass locally. Ruff formatting,
lint, mypy, and `git diff --check` pass for the changed verifier. The next
qualification is the hosted Basic resource worker under the same 300-second
deadline, followed by the Multilevel constrained run.
