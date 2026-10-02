# 0024: Journal paper accounting without replacing the Ledger

Date: 2026-10-03. Status: accounting migration implemented; wider paper state
journal migration and durable paper integration remain required, not delivered.

## Decision and rationale

Paper accounting has ten scalar integer fields. Previously every real update
copied this object along with global state, then replaced it after failure. An
absent-edge delete incremented three counters outside the rollback boundary;
failure between increments could leave inconsistent accounting without changing
any edge or graph version. Exact recovery includes accounting, not only topology.

`Journal` retains each original integer before its first write, with a positive
distinct-field capacity. Repeated writes to the same field retain its original
value once. Admission/allocation/type failure precedes that field's mutation.
Only existing plain integer attributes are supported; descriptors and mutable
containers are rejected. Tokens are single-owner-thread and close once. This is
scalar undo, not a generic container interception layer or durable codec.

Ledger routes active assignments through this journal, with ten entries maximum.
Active field deletion and journal replacement reject before changing state.
The Matcher snapshot memo retains the original Ledger and aliases rather than
copying it. On failure, accounting rolls back in place alongside graph journals;
other Python state still uses the established snapshot path. Absent-edge deletes
now also use an accounting transaction while retaining their existing no-op
accounting semantics and unchanged graph version. Duplicate inserts remain no-ops.

## Publication and uncertainty

Accounting token and owner validation occurs before native group publication.
Once graphs publish, their old graph tokens cannot truthfully roll back. Failure
in subsequent accounting cleanup therefore fail-stops the Matcher. Failure while
unwinding any participating state also fail-stops it. Update, matching/query and
public repair APIs reject a failed instance; discard it rather than clearing the
flag and continuing. Raw public fields remain available for diagnosis, not as
certified query state. Standalone paper state has no durable restart authority
yet, so this is **not** a durable recovery mechanism.

Python rollback uses retained scalar values and no full-state copies, but Python
control operations are not an allocation-free native undo guarantee. If they
fail, the instance is explicitly unusable. The ten-entry bound is not a process
RSS quota. Ledger/Matcher remain externally serialized outside active journal
ownership; this does not substitute for thread-safe production Service admission.

## Evidence and remaining work

Tests cover all ten counters, first-write retention, capacity/allocation failure,
invalid writes/descriptors, nesting, stale/wrong-owner tokens, cross-thread writes
and close, success, post-rebuild failure, publication rejection and failed snapshot
creation. Both modes and both graph backends compare full state and retained Ledger
identity, then retry. A copied-Ledger hook rejects any attempted accounting deepcopy.
Absent-delete failure after earlier counter writes restores all counters; owner
replacement rejects before graph publication. Cleanup/rollback faults must fail-stop
and reject later queries/updates rather than claim exact rollback.

No throughput improvement is claimed from removing this small part of copying.
Matching sets, partners, auxiliary maps, System/Hierarchy in-place containers,
root replacement/rebuilds and ephemeral coloring/fan mutations remain separate
journal work. Their snapshots must stay until equivalent failure coverage passes.
The [state inventory](../paper-state.md) and [durable integration contract](0023-durable-paper-integration.md)
remain the completion gates. Native performance results do not certify paper modes.
