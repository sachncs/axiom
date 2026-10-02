# Paper state and migration oracle

The durable paper integration is **not implemented**. `axiom.witness.Witness`
is a bounded diagnostic comparison oracle, not a checkpoint decoder, persistence
API or mutation journal. It establishes the differential test boundary needed
before removing the paper matcher's current `deepcopy` rollback path.

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
collisions and chain routing. Exact fan indexes still matter: comparing only
membership or the resulting complete coloring misses state corruption.

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

Existing paper rollback restores logical state but replaces many Python objects
from snapshots. The tests do **not** claim preservation of every pre-failure
Python object identity. Journal migration must additionally preserve identities
and aliases while covering in-place container edits, attribute replacement,
phase/hierarchy reconstruction and failure during allocations. Typed recovery,
persisted algorithm/configuration, bounded checkpoint/history, SQLite failure,
commit/publication/ack sequencing, concurrent service admission and installed
per-mode qualification remain required under [ADR 0023](adrs/0023-durable-paper-integration.md).
