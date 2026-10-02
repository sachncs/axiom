# 0027: Share endpoint-cache edits and avoid point-membership unions

Date: 2026-10-03. Status: shared System delta boundary implemented; System and
Hierarchy journal migration and durable paper integration remain active.

## Problem and decision

Basic and multilevel owners duplicated System Lambda/L cache edits. Basic
appended and sorted a whole row, while multilevel searched linearly before sorted
insertion. Both constructed `B | U` merely to test a neighbor's membership.
Some System/Hierarchy certificates similarly materialized saturated/region
unions inside edge or neighbor loops. Those allocations scale with the partition,
not the edited endpoints, and complicate a future first-write row journal.

`System.update` now owns both Lambda/L endpoint transitions. Basic's existing
internal coordination method and Hierarchy's incremental synchronization delegate
to it. It requires valid distinct vertex labels, a boolean delta and graph
membership matching the delta before changing any cache. The graph owner applies
the topology transition first. Invalid/unapplied deltas reject before creating
keys or touching rows. This checks one edge, not the full partition or graph.

`System.change` uses binary search on the existing sorted unique row. Insertion
and removal preserve row identity and shift O(row length) entries; they are not
constant-time list edits. Duplicate insertion and absent deletion do not change
the row. The existing public `hierarchy.update` helper remains an alias to the
same class-owned primitive, rather than a second implementation or new wrapper.
Raw unsorted/invalid row edits remain outside the mutation contract.

Point membership uses the original sets directly: membership in a union is an
OR of memberships, and absence is an AND of absences. Certificates still check
the same predicates and all existing degree/partition/matching constraints.
Unions needed to enumerate or compare complete partitions remain; this does not
make full validation local or eliminate its O(state-size) work.

## Reliability and migration boundary

System delta edits still rely on the enclosing Matcher transaction's snapshots
for failure rollback. They are not a System journal, a standalone transaction or
durable persistence. Standalone callers serialize access and arrange restoration
of graph and caches together. `System.index` still creates new map/list candidates;
refinement also changes graph references and matching subsets. A complete journal
must cover those replacements, row contents, shared hierarchy list aliases and
inherited System identities before removing snapshots.

Tests cover row ordering, first/middle/last insert/remove, repeated/no-op edits,
unaffected row identity, both graph backends, invalid labels/delta types, unapplied
graph changes, endpoint membership with unions trapped, shared multilevel routing,
complete hierarchy certificates without per-edge saturated-set materialization,
and full-state rollback/retry after cache failure. A malformed multilevel tombstone
case deliberately forces phase-cache failure recovery; it is not valid-workload
performance evidence. Existing valid replay/update tests remain independent.

Installed comparisons must retain the exact trace, source/runner/wheel provenance,
matching/counter results and measurement scope. Native durable throughput does not
qualify this paper path. The durable integration gates in [0023](0023-durable-paper-integration.md)
and the remaining state inventory in [paper-state](../paper-state.md) remain required.
