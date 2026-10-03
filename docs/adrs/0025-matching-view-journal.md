# 0025: Journal matching cells and retain original containers

Date: 2026-10-03. Status: matching-view migration implemented; complete paper
journal migration, incremental validation and durable integration remain active.

## Decision

The paper Matcher owns three coupled views: matching edges, matched vertices and
partners. Copying all three on every real update scales with the entire matching,
even when local repair changes only one pair. Snapshot rollback also replaced
these containers, invalidating external references to the old authoritative views.

`Views` retains the original containers and records each touched edge and endpoint
once before any local mutation. An endpoint record preserves vertex membership,
partner-key presence and the old partner separately. Missing entries and values
are not conflated. The default bound is 65,536 distinct edge/endpoint records;
capacity/allocation failure occurs before the associated view edit. Repeated
drop/add transitions retain the pre-update value, not an intermediate one.

At this ADR's implementation stage, the snapshot memo retained all three
containers without deepcopy while other paper state still used snapshots.
Those remaining recursive Matcher copies were removed later by ADR 0003.
`add_match`/`drop_match` register mutations;
Hierarchy I3 repair already delegates to these helpers. `refresh` constructs
new private containers and replaces all three root references. Failed refresh,
including failure between assignments, restores the old references and earlier
in-place edits. Successful candidates become authoritative only after validation.

## Ownership and certificates

External references to the three containers are retained on rollback. Sharing a
matching container with other owned algorithm state is rejected in a preflight
before graph/counter mutation: those other mutations are not matching operations
and cannot silently bypass matching undo. Ordinary phase graph sharing and the
seed/color-class aliases remain supported; they are separate from these views.
Plain sets/dictionary are required. Active journal replacement/deletion, nesting,
stale handles and cross-thread operations reject before modifying journal state.

GIL-enabled CPython skips the alias walk only when each plain matching container
has exactly three strong references: its Matcher field, this journal field and
the `getrefcount` argument. An additional internal or external alias prevents that
proof and retains the full walk. Other interpreters and free-threaded CPython
builds always use the conservative walk. This is an ownership proof, not a
replacement for graph or matching certificates. Tests trap any traversal to prove
both the unique fast path and the shared/disabled-GIL fallback.

All algorithm writes to existing matching views must use the registered matching
helpers. Raw field/container edits during a transaction are not a supported update
API. Adding a write site requires extending the mutation inventory and tests;
public names do not make arbitrary concurrent/debug mutation safe. Clients must
use update/query APIs and externally serialize the current standalone paper engine.

Changed endpoint/edge dependencies are checked before publication. A rebuilt
candidate gets a complete coupled-view certificate. Existing full matching,
maximality, auxiliary and hierarchy checks are retained, not replaced or disabled.
Failed rollback or cleanup after graph publication fail-stops the Matcher under
[0024](0024-accounting-journal.md), rather than claiming closed graph tokens undo.
Python undo may allocate small container/control storage; it is not the native
allocation-free guarantee. Failure during undo is explicit fail-stop.

## Efficiency boundary and evidence

This removes complete matching-view copies and preserves their identity. It does
**not** make ordinary paper updates constant-time: shared-view alias preflight
traverses remaining owned Python state, and global snapshots/certificates still run. Entry
capacity bounds undo records, not preflight scratch, candidate coexistence, total
RSS or graph allocations. No million-vertex paper throughput claim follows.

The [installed-wheel diagnostic](../../benchmarks/results/paper/README.md) retains
the initial full-walk regression as well as the uniqueness-proof follow-up:
108.00, 100.09 and 123.11 real updates/s respectively on the same small basic
trace. Transient traced memory decreased 8.9%; RSS did not. This is not durable
throughput qualification, and does not certify other runtimes or shared views.

Tests cover both modes and both graph backends, original edge/vertex/map identity,
first-write retention, old edits followed by candidate replacement, capacity
rejection and retry, repair/rebuild/copy/publication failure, endpoint corruption,
partial candidate assignment, unsafe aliases/cycles, lifecycle/thread errors and
post-publication fail-stop. Instrumented deepcopy calls at this stage required
memo reuse for the three views. Full-state replay/rollback oracle checks remain independent of
proper/maximal matching checks.

Matching classes/seeds, System/Hierarchy containers, clocks and auxiliary maps
still need journal migration. Alias admission and validation must become local
before scaling the paper path; a bounded cell log alone is not full qualification.
Typed images, algorithm identity, bounded history, SQLite failures and concurrent
durable Service workflows remain required by [0023](0023-durable-paper-integration.md).
