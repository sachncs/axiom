# 0029: Retain Hierarchy roots and journal deferred phase deletions

Date: 2026-10-03. Status: Hierarchy root/deferred-edge journal shipped;
Matcher recursive copying has since been removed by ADR 0003. Durable paper
integration remains.

## Decision

The active plain `Hierarchy` root is retained by identity in the Matcher shallow
root snapshot. The transaction captures its shallow attribute roots, not a recursive copy
of level partitions/indexes. The root fields are replaced only when a rebuild
constructs a private candidate; rollback restores the original attribute roots.
The current incremental graph synchronization mutates the managed phase graph
(covered by graph rollback), System-owned rows/sets (covered by `Systems`), and
the hierarchy's `deferred_deletions` set. Deferred-edge membership uses a bounded
first-write journal with a 65,536-cell default cap and logs all clear operations
before clearing any element.

`Hierarchy.defer`, `undefer` and `clear` route through the active owner journal.
The transaction checks thread and handle ownership, validates exact supported
record/container types, and rejects journal replacement/deletion. Candidate
Hierarchy roots built by phase reconstruction must be plain idle records before
publication. Cleanup uncertainty retains the existing Matcher fail-stop policy.

## Mutation boundary and limitations

This removes recursive copying of the current Hierarchy root's unchanged
partition/index state. It does **not** provide undo for arbitrary in-place edits
to `A_levels`, `N_levels`, `R_levels`, `L_levels`, or their nested containers.
Incremental update code must keep these structures read-only; row mutations in
`L_levels` are routed through the System journal. Phase rebuilds construct
replacement roots and do not mutate the old partition sets in place. Tests cover
identity retention, deferred add/remove/clear capacity behavior, cross-thread
and handle failures, updates on both graph backends, post-repair failure,
post-phase-rebuild failure, exact Witness rollback, independent maximality and
hierarchy checks, and retry.

Matcher state is no longer recursively deep-copied. Auxiliary indexes and phase
clocks now use bounded first-write journals. System admission scans, global
certificates, Python journal allocation and durable paper codec/service work
remain. This is not proof that the paper algorithm meets the production
throughput target.

## Evidence

See [installed comparison](../../benchmarks/results/paper/hierarchies.json) for
wheel hashes, fixed workload, three timing repeats, transient memory, RSS,
latencies, matching certificate, rebuild counters and all-prefix hashes. The
candidate wheel has SHA-256
`70bcbbc26a3f045276c9dc5e54beb4058f0bcd5733ab0861309f93b1ea7d19f8`.
