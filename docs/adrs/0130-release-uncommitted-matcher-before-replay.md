# ADR 0130: Release uncommitted Matcher state before durable replay

- Status: implemented; constrained Linux qualification pending
- Date: 2026-10-04

## Context

The million-vertex disk-pressure worker advanced into update processing, then
an update failed under the 512 MiB address-space limit. `Durable` correctly
replayed the SQLite-committed operation prefix after an uncommitted multi-slice
group failed. However, `_restore_committed_matcher()` kept the failed in-memory
Matcher alive while `_replay_operations()` allocated a second million-vertex
Packed graph. Recovery then failed allocating the replacement graph, and the
owner entered fail-stop state even though the durable prefix was intact.

## Decision

While the Durable owner lock excludes reads, clear non-current frames from the
caught exception traceback, then discard its private Matcher before
reconstructing committed state. A traceback can retain `Matcher.batch` frame
locals and therefore the graph even after the owner field is cleared. Replay
installs the new Matcher only after its Packed graph is constructed; replay
capacity retries likewise clear traceback frames and discard the partial
candidate before starting a smaller-slice attempt. If reconstruction or its
audit fails, the owner remains unavailable and callers must reopen it; the
uncommitted Matcher is not restored or exposed as authoritative state.

## Consequences

- Failed groups and capacity retries no longer require two full graph roots or
  their exception-traceback references to coexist during deterministic replay.
- The SQLite operation log and control row remain the source of truth; recovery
  still audits sequence, version, digest, graph, and paper state before use.
- If recovery fails, the Durable instance is fail-stop. Existing behavior
  already required reopening after failed recovery; no weaker partial reads are
  permitted.
- The fix addresses the exact overlapping-graph allocation observed in CI, but
  only a successful rerun of the installed 512 MiB worker can establish the
  memory gate.

## Verification

Both Basic and Multilevel capacity-retry tests hold only a weak reference to the
previous Matcher and assert it is collectible before replacement allocation,
then compare full public state and exact in-memory Witness after replay. Hosted
constrained Linux qualification remains pending.
