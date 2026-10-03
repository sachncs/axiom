# 0026: Retain paper color classes and seed aliases through rollback

Date: 2026-10-03. Status: class/seed journal implemented; System, Hierarchy,
auxiliary snapshots and durable paper integration remain active work.

## Decision and mutation inventory

Color classes are phase-owned sets, distinct from the live matching views. The
seed initially aliases the first class; subphase augmentation can replace it and
the first list slot independently. Deletion removes an edge from the seed and
every class. Settled repair removes stale seed edges from both seed and class zero.
Previously the snapshot restored copies, losing external class/list identities.

`Classes` retains the original list, a tuple of its set references, the original
seed and a distinct-set identity registry. Registered `remove` operations log
original edge membership once per retained set. Repeated references or repeated
removals do not duplicate cells. Partitioning builds a fresh list/sets and seed
augmentation builds a private seed before mutation; these candidates need no
original-set undo. Slot zero replacement is restored from the retained references.
Rollback restores memberships, original slots, roots and intentional seed/class
sharing in place, including edits made before candidate construction.

At this stage, the snapshot memo preserved original list/seed/class references
rather than copying edge populations; the remaining recursive Matcher copy was
removed later by ADR 0003. Existing proper-coloring, live matching, maximality, seed containment,
auxiliary and hierarchy certificates remain. Journal validation additionally
requires supported plain candidate containers; it is not a substitute for those
algorithm certificates. Raw container edits are not a supported transactional
API. New class mutation sites must register before modifying retained sets.

## Admission and failure contract

The default capacity is 65,536 retained distinct sets plus edge-cell records.
The initial list length plus seed is conservatively bounded before retaining
references; a new cell rejects before the associated set edit. This is not a
process-memory quota: admission, remaining snapshots, private candidates and
global certificates can still allocate or traverse the whole state.

Plain list/set roots and set elements are required. Intentional seed/class and
repeated-class sharing is supported. Sharing a class/list into other owned
algorithm state rejects before graph/accounting mutation, because those writes
would bypass removal hooks. Alias admission traverses owned state with cycle
detection; external holders are supported and restored, not rejected.

GIL-enabled CPython can skip that traversal only after proving uniqueness of
every retained container. The list has its owner field, journal field and the
`getrefcount` argument. Each set has its registry entry and argument, two references
per occurrence in the original list and retained slot tuple, and two additional
references if it is the seed (owner and journal seed fields). Exactly these counts
are required, not an upper-bound guess. Extra internal/external holders prevent
the proof. Other interpreters and free-threaded builds retain the full walk.
This O(number-of-classes) proof does not remove remaining global snapshots or
certificates. Trap tests establish the fast path with shared, independent and
repeated seed/class references, plus the external-alias and disabled-GIL fallback.

Owner binding, active lifecycle and thread checks reject nested, stale and
cross-thread use. Active handle replacement/deletion is forbidden. Graph
publication precedes journal release. Python undo can allocate; failed undo or
post-publication cleanup fail-stops the Matcher and refuses updates/queries under
[0024](0024-accounting-journal.md). Standalone paper access still requires external
serialization; this does not implement durable Service concurrency.

## Verification and remaining work

Component/data-flow tests cover present/absent and repeated removals, shared sets,
original list slots, private candidates, capacity exhaustion and retry, unknown
container types, cyclic/unsafe owned aliases, lifecycle/thread guards and cleanup
uncertainty. Real deletions in both paper modes and both graph backends inject
failure after local repair, subphase replacement, phase rebuild and publication.
They compare full Witness state and original list/seed/class identity before
retrying. Instrumented snapshot calls require original references in the memo.
The installed-wheel verifier also exercises class identity across live edits.

This is another certified copy boundary, not completion of paper migration or
proof of faster updates. Shared-class alias admission remains global. System/Hierarchy
and auxiliary containers, clocks, typed recovery, persisted algorithm identity,
bounded SQLite history and concurrent per-mode durable qualification remain
required by [0023](0023-durable-paper-integration.md).

The [installed diagnostic](../../benchmarks/results/paper/README.md#color-class-follow-up)
retains the initial full-walk regression (99.72 versus 123.11 updates/s) and the
ownership-proof correction (126.50/s, 1.0% less transient traced memory, unchanged
RSS). All trace/outcome/certificate/counter checks agree. This small sparse case
mostly has empty classes and no rebuilds; it measures admission overhead, not
dense-class scaling or durable paper throughput. The full local suite passes
1,056 tests with 100% class-journal line coverage; optimized focused tests and a
fresh installed wheel also pass. CI must qualify the exact pushed revision.
