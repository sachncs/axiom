# ADR 0049: Local matching cleanup after edge deletion

Date: 2026-10-03

## Context

ADR 0048 moved System cache validation from whole-map scans to touched rows. The
resulting profile exposed two calls to `Matcher.__cleanup_stale_edges` in every
deletion. Each call traversed the entire matching and queried the graph for
every matched edge, even though one Matcher update edits exactly one graph edge.

## Decision

Remove both full-matching cleanup passes. On deletion of `(u, v)`, the only edge
that can have become stale is `(u, v)`. If it is matched, the existing direct
membership check drops it before either endpoint is rematched. Rematching does
not edit graph topology. Insertions cannot make an existing matching edge stale.

This argument depends on graph mutation being owned by Matcher during an update.
Out-of-band edits through the publicly exposed graph are unsupported while the
matcher is live; they already violate its graph/matching consistency contract.
Complete matching audits remain at rebuild/replacement boundaries and in
independent test oracles. The public Ledger stale-cleanup field/method is kept
for compatibility, but ordinary updates no longer need global repair through it.

## Alternatives considered

- Keep two global scans as defensive repair for arbitrary external graph edits:
  rejected because it makes every deletion O(|M|), masking unsupported mutation
  and imposing the cost on all valid callers.
- Replace each scan with another global audit: rejected for the same reason;
  full audits belong at replacement/rebuild boundaries, not every local update.
- Add a stale-edge index: unnecessary because the single-edge transaction already
  identifies the only candidate exactly.

## Evidence

[`deletion-cleanup.json`](../../benchmarks/results/paper/deletion-cleanup.json)
records the same fixed 8,192-vertex sparse average-degree-four multilevel churn
trace as ADR 0048 (seed 42, 128 real updates, five timing batches, unchanged
runner). Throughput rose from 610.30 to 1,103.56 updates/s (1.81×); trace and
final matching certificate are identical. Sampled memory is unchanged. This is
one-host diagnostic evidence, not durable or million-vertex qualification.

A deterministic test measures four graph-membership calls for a matched-edge
deletion at each of 16, 128, and 512 unrelated matching edges. The complete
suite, Ruff and mypy pass.

## Consequences

Deletion work no longer has an O(|M|) cleanup term. Incorrect external mutation
is not silently repaired by the next deletion; callers must preserve Matcher
ownership and use explicit consistency audits when diagnosing such corruption.
Remaining profiled costs and state-sized paper snapshots are still open.
