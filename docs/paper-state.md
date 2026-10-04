# Paper state and migration oracle

Durable paper integration now routes both `basic` and `multilevel` through the
same SQLite operation-log owner. `axiom.witness.Witness` remains a bounded
diagnostic comparison oracle, not a checkpoint decoder or persistence API. The
Matcher update path no longer calls `deepcopy`:
transactions retain shallow attribute roots and enlist owner-specific journals.
That removes recursive copy allocation; it does not establish durable paper
state, billion-vertex support, or zero state-proportional work in every journal.

Recent hot-path work reuses each changed endpoint's sorted neighbor row across
all hierarchy levels during Multilevel certification, rather than sorting it
once per level. `Spectrum.modify()` also no longer repeats pre-mutation
certificates inside its journal scope, and its post-flip fan repair uses the
per-vertex fan index instead of snapshotting all fans. Full independent entry
and exit certificates remain, so neither change eliminates state-sized audit
work. See [ADR 0111](adrs/0111-localize-modify-types-fan-repair.md) and
[ADR 0112](adrs/0112-reuse-hierarchy-endpoint-neighbor-rows.md).

Recursive hierarchy refinement no longer duplicates the complete lower-level
edge coloring into per-color Python sets to rank classes and select deferred
edges. It counts deleted edges in a `z + 1` row and scans the existing coloring
for selected results, preserving empty-color ordering and all independent
certificates. This removes one O(|M|) hash-membership copy, not the coloring,
global validation, or result sets. See [ADR 0114](adrs/0114-count-colors-without-edge-buckets.md);
full allocation and end-to-end qualification remain open.

`Paper.color()` also delays retaining its complete edge certificate until a
recursive seed has returned, so that set does not overlap the seed's temporary
edge sets. The final completeness check compares the coloring key view directly
instead of copying all keys. Full coloring/certification scans remain by design;
large-graph allocation effects are not yet measured. See [ADR
0115](adrs/0115-defer-paper-color-edge-snapshot.md).

`Matcher.partition()` now compares the returned coloring key view with the
system matching directly; missing/extra edge sets are materialized only for an
invalid result. The coloring, output classes, and independent range/properness
checks remain. See [ADR 0116](adrs/0116-compare-partition-color-keys-by-view.md);
full rebuild allocation measurement remains open.

`Paper.complete()` now scans the original edge universe after fan construction
instead of rebuilding `alledges - start.edges()` as a second difference set.
This preserves edges newly uncolored by chain flips, deterministic sorting, and
the skip for edges already colored by fan repair.
See [ADR 0117](adrs/0117-reuse-paper-pending-edges.md); end-to-end allocation
impact remains unmeasured.

`Paper.partition()` now stores dense Euler edge-ID membership and side
assignments in byte arrays rather than Python hash containers, while retaining
the existing deterministic traversal and an explicit completeness count. See
[ADR 0118](adrs/0118-byte-indexed-paper-partition.md); end-to-end memory impact
remains unmeasured.

## Coupled state inventory

| Owner | State that must survive rollback and recovery |
| --- | --- |
| Matcher | Algorithm and strategies; matching classes, seed and live matching; partner/vertex views; phase graphs and systems; clocks/schedules; insertion/deletion overlays; bad vertices; H/tilde-H and reverse indexes; accounting |
| System | Graph reference, z, A/B/U/M, Lambda and L lists |
| Hierarchy | Shared system/graph references, levels, partitions, recursive indexes and deferred deletions |
| Ledger | Every counter, including `phase_update_work`, which ordinary stats omit |
| Partial | Graph, palette, assignments, incident colors and vertex/color edge index |
| Fans | Members, spokes, assignments, assigned colors, per-vertex and per-type indexes |
| Graph | Reference adjacency rows and redundant edge count, or native topology, universe, version and configured budget |

Fans and partial coloring are temporary construction/repair state, not persistent
Matcher attributes. Their rollback is checked independently during real fan
collisions and chain routing. Durable recovery recreates them by replaying the
committed update stream through the persisted mode; there is no compact paper
state codec or snapshot compaction. Exact fan indexes still matter: comparing
only membership or the resulting complete coloring misses state corruption.

Alternating `Partial.flip()` now updates only its path and endpoint indexes,
rejecting endpoint color conflicts before mutation. A matching full-reindex
reference benchmark records equal checksums, roughly 2,960× lower time, and far
lower transient allocation for a short chain on a 50,000-vertex sparse coloring;
this operation-level result does not qualify the paper matcher end to end.
Single-fan replacement now preallocates its local type, assignment, and
incidence entries before removing the old value. Injected mid-reservation
failure restores exact roots and entries. A failure spanning multiple fan
updates in `Fans.flip()` now uses a path-endpoint-sized reverse journal; an
injected second-endpoint failure restores exact coloring/fan Witness state.
Rollback failure remains fail-stop. Durable transactions compose these paper
journals in bounded private slices, with one SQLite commit per caller batch;
recovery remains proportional to the stored operation history.

The oracle includes every instance field of the supported records. Unknown
types and unexpected instance fields reject rather than disappear. Default
strategies are stateless but their concrete identities are captured. Arbitrary
custom colorers/graphs need an explicit state contract before qualification.

## What comparison means

`Witness().capture(matcher)` returns canonical comparison bytes. Integer/string/
boolean/float/tuple/set types remain distinct; dict/set insertion order is ignored.
Mutable reference numbering follows deterministic traversal, not memory addresses.
Sharing a system or graph is distinguishable from copying an equal-valued object.
Native versions and budgets are compared; allocator capacity, journal tokens,
addresses and process RSS are not logical recovery state.

Capture must occur on the owning thread between operations. Positive node, depth
and byte limits reject excessive diagnostics. Temporary traversal references are
released on success and failure; a failed capture does not alter the source and
the oracle is reusable. These are diagnostic bounds, not a hard process-memory
quota. Capture is O(state size) and must not be placed on ordinary production
updates. There is deliberately no decoder and no stable production format promise.

Equality is not a correctness certificate: identical executions can share a bug.
Tests also check proper/maximal matching, partners and hierarchy invariants.
Basic's static saturated-degree certificate applies at rebuild boundaries, not
every intervening live-graph mutation; its partition is phase-owned. Multilevel
hierarchy checks remain separate. No static invariant is disabled to force equality.

## Covered and remaining

Tests replay every deterministic trace prefix in basic/multilevel on both
Adjacency and Packed, spanning phase rebuilds. Failure after repair/rebuild must
restore full comparison bytes, retain the supplied graph identity and permit
retry. Fan failure tests compare full coloring and fan state. Negative tests
detect changed counters/indexes, equal-cardinality alternate valid matchings,
equal-topology native versions and broken shared graph references.

Absent-edge deletes currently increment accounting although they do not change
topology or native graph version. Duplicate inserts do not change state. A future
durable paper codec/replay must retain these algorithm-specific semantics rather
than borrowing native `changed` bookkeeping without examination.

Accounting now uses ten-entry first-write undo; failed updates
preserve Ledger identity and exact counters, including absent-edge deletion
failures. [ADR 0024](adrs/0024-accounting-journal.md) records publication/fail-stop
behavior and the remaining migration boundary.

Matching edge/vertex sets and the partner map now use first-write cell undo, with
their original containers retained by the owner journal. Failed repair/rebuild
restores their identities, including old edits before candidate replacement.
[ADR 0025](adrs/0025-matching-view-journal.md) records the ownership precondition,
shared-view alias admission and uncopied-view mutation inventory.

Color classes and the seed now also retain original list/set references through
the owner journal. Registered removals use bounded first-write membership cells;
failed subphase/rebuild candidates restore original list slots and seed/class
sharing in place. [ADR 0026](adrs/0026-color-class-journal.md) records the mutation
inventory, global alias admission and remaining migration boundary.

Basic and multilevel now share `System.update` for endpoint-cache edits, using
sorted binary-search row deltas and no temporary partition union for point
membership. [ADR 0027](adrs/0027-system-cache-deltas.md) records its preconditions
and mutation boundary. Basic and multilevel updates now retain the original
System objects, root references, touched cache rows and deleted M edges in a
bounded owner-bound journal. Aliases shared with hierarchy row indexes use the
same first-write record. Failed updates restore System and row identities before
the remaining auxiliary Matcher rollback. [ADR 0028](adrs/0028-system-undo-journal.md)
documents admission, capacity and failure semantics. The active Hierarchy root
and unchanged partition/index roots retain identity; deferred edges have their
own bounded journal. Auxiliary maps/sets and clock cells now use bounded
first-write journals. Arbitrary in-place partition/index edits are not
journaled, and some admission/certificates remain state-sized.

The active Hierarchy itself and its unchanged partition/index roots now pass
through shallow Matcher root retention by identity. Deferred deletion membership has a
bounded first-write journal, while System-owned `L_levels` rows use the System
journal. Full rebuilds install private Hierarchy candidates; rollback restores
the original root, graph identity/topology, Systems and deferred-edge cells. This
does not journal arbitrary in-place writes to partition/index contents; that
mutation boundary must remain enforced and tested. See [ADR 0029](adrs/0029-hierarchy-root-journal.md).

Existing paper rollback is now journal-based for known mutation owners. Tests
check identity and aliases for enlisted roots, but do not claim arbitrary custom
colorer/graph objects are rollback-safe. Remaining work is to audit/integrate the
paper's coloring, fan, hierarchy and phase-maintenance operations as one production
path, exercise adversarial boundaries, and add typed recovery,
persisted algorithm/configuration, bounded checkpoint/history, SQLite failure,
commit/publication/ack sequencing, concurrent service admission and installed
per-mode qualification remain required under [ADR 0023](adrs/0023-durable-paper-integration.md).

The standalone paper `System.switch` primitive no longer snapshots its complete
matching/degree inputs or recomputes all degrees after an alternating route. It
retains path-edge and endpoint-degree before-images, with injected edge-write
and degree-write rollback tests plus randomized differential comparison. It has
no current internal caller, so its allocation gain does not yet reduce active
Matcher hierarchy cost. See [ADR 0095](adrs/0095-path-local-switch-undo.md).

Hierarchy refinement also uses missing-as-zero sparse matching-degree storage
below a conservative density threshold, retaining packed arrays for dense
matchings. A million-counter microprobe saved about 4 MB, but full 20k refinement
peak/time remained neutral because other snapshots dominate. This is an
allocation component result, not end-to-end Matcher improvement; see
[ADR 0096](adrs/0096-sparse-refinement-degrees.md).

Exact refinement cycle detection now stores no frozenset copies of U, A or the
chosen matching. A scalar guard verifies strict U reduction across every
continuing promotion pass; baseline/candidate Witness output was identical on
four graph families. Total traced peak stayed flat on the measured 20k star,
so the change removes per-pass cycle-key copies but does not qualify whole
refinement memory. See [ADR 0097](adrs/0097-monotone-refinement-progress.md).
