# 0102: Reuse the synchronized graph at a parent-phase boundary

Date: 2026-10-04. State: implemented; correctness regression evidence.

## Context

At a child-to-parent phase boundary, hierarchy synchronization already builds a
detached graph containing the exact current live topology. The rebuild then
made a second equivalent graph snapshot solely to retain as the next immutable
phase base, causing another O(n + m) traversal and graph allocation.

## Decision

Retain the synchronized hierarchy graph itself as the next phase-base graph.
Rebuild the level-1 `System` on that graph, preserving the rule that the live
matcher graph and immutable phase base are distinct while avoiding a redundant
copy. The hierarchy and phase-base graph may intentionally share identity at
this boundary; subsequent matcher transactions already deduplicate graph roots
and journal their mutations.

## Verification and limits

The regression forces a child-to-parent boundary, asserts that no call to the
standalone snapshot helper occurs, checks exact live/phase topology and
hierarchy/system certificates, then injects a later rebuild failure and
compares graph roots, edge contents, matching, and hierarchy identity after
rollback. This establishes the boundary's semantics, not end-to-end rebuild
throughput or memory qualification.
