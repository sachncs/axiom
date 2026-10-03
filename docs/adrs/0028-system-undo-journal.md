# 0028: Journal System roots, cached rows and matching cuts

Date: 2026-10-03. Status: admitted System undo implemented; Hierarchy-owned
containers, auxiliary state and durable paper integration remain active.

## State and mutation inventory

Each admitted plain System owns a graph reference, degree parameter, A/B/U
partitions, matching set M and Lambda/L row maps. Across one Matcher update,
Systems may be shared by the live basic owner, phase base and several levels.
Hierarchy's level list shares those System objects; its `L_levels` maps can share
row lists with the first System. Refinement replaces System roots, edits retained
M sets and rebuilds indexes. Incremental cache updates mutate rows, potentially
through a second hierarchy alias.

`Systems` admits the distinct pre-update System objects, retains their shallow
root dictionaries and registers their maps/rows. `retain(memo)` marks the System
objects, root sets/maps and current rows as unchanged references for the remaining
snapshot. It does not copy row contents. A single first-write row record is keyed
by list identity across all map aliases. Original map keys remember prior key
presence and values before `setdefault`; private replacement maps are candidates
and are restored by restoring System roots. Failed `index()` replacements cannot
orphan original rows. Original set M removals are logged once across all admitted
Systems before changing them. Repeated cuts preserve the pre-update membership.

Basic and multilevel `System.update` route eligible endpoint edits through this
owner journal. Incremental Hierarchy `L_levels` edits pass through it too, so an
alias reached by either route shares one undo cell. `System.restrict` routes
refinement cuts through the same journal. Standalone Systems without an active
owner still use the direct edit path and need caller-supplied serialization and
rollback.

## Bounds and rollback

The default capacity is 65,536 logical control cells: each System root field,
each new map-key record, each changed row plus its copied integer entries, and
each distinct matching edge removal. This bounds journal records and row snapshots,
not overall process memory. Admission enumerates the original Systems and cache
rows to register shared references; that temporary/bookkeeping work scales with
the retained state. Remaining Matcher and Hierarchy snapshots, graph snapshots,
candidate construction and global certificates also remain outside this quota.

Matching cuts stream the original set to discover removed edges. They log each
edge before changing the set, then remove by iterating the bounded undo entries;
they do not allocate a second full matching-sized difference set. Capacity
failure during discovery occurs before any matching removal. Rollback restores
rows, original map-key presence, set memberships and all original System roots
in place, then the existing snapshot restores other Matcher/Hierarchy fields.
Packed graph journals roll back topology/version separately, before System roots.
Python undo may allocate and fail; uncertain rollback or post-publication cleanup
fail-stops the Matcher and rejects future queries and updates.

Admission requires exact System records, nonnegative integer z, graph universe
matching the Matcher, plain partition/matching sets and plain row maps/lists.
Unknown System fields and unsafe active-handle replacement reject. Every candidate
is revalidated before publication. Full System/Hierarchy/matching certificates
remain independent; row journaling does not certify algorithm invariants.

## Verification and remaining work

Tests cover map-key absence, multiple aliases to one row, repeated edits,
index/root replacement, M cuts, capacity failure before mutation, partial cuts,
rollback and retry, snapshot-allocation and publication failure, invalid schemas,
stale/cross-thread handles and cleanup fail-stop. Both modes and both graph
backends inject failures after repair, subphase/rebuild work, deep-copy admission
and publication; exact Witness state, System/root/row identities and retry are
checked. The independent journal component has 100% line coverage. The installed
verifier checks System, partition-map, row and undo-handle identity across live
edits. Installed per-mode measurements and CI must qualify the pushed source.

This migrates System-owned roots and touched System lists/sets. It does not remove
the Hierarchy snapshot, Matcher auxiliary snapshots, Graph rollback for opaque
implementations, full certificate scans, or O(state) journal admission. Phase
clocks, all hierarchy levels/partitions/deferred sets, type indexes, and typed
durable encoding/recovery still require their own write inventory and tests.
The basic/multilevel durable Service remains required by
[0023](0023-durable-paper-integration.md).
