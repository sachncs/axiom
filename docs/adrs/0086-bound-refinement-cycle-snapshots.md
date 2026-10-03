# ADR 0086: Bound hierarchy refinement cycle snapshots by the U frontier

Date: 2026-10-04
State: Implemented; stable-frontier snapshots and broader refinement work remain

## Context

`refine_hierarchy` retains exact cycle-detection keys containing copies of U,
A, B, the selected matching, and every degree cell. A promotion strictly
shrinks U; refinement never adds a vertex back to U. Consequently, a state
recorded before a shrink cannot recur afterward because exact U membership is
part of the key. Keeping those old states wastes O(graph state) memory for each
promotion pass.

The repeated-state guard cannot simply be removed or replaced by the claim that
every changed pass consumes U. ProcProcess branches can change the matching
while processing the pass's ordered U snapshot, and existing deterministic
regressions exercise those transitions.

## Decision

Keep exact full-state equality checks for cycle detection on the current U
frontier. After a pass shrinks U, clear all older keys; they are unreachable
under the monotone-U invariant. Do not change the pass order, stale entries in
the ordered iteration snapshot, matching swaps, or failure behavior. This bounds
retained cycle history to the current frontier's unchanged-U sub-iterations
rather than all earlier refinement passes.

The individual key is still graph-sized, and multiple matching-only transitions
at an unchanged U frontier can still retain multiple keys. This ADR does not
claim complete removal of hierarchy snapshots.

## Correctness evidence

Existing deterministic refinement regressions cover repeated B-neighbor repair,
deferred deletion, hierarchy certificates, and exact selected matching output.
The measured before/after run compares canonical hierarchy state, including all
level partitions, matching edges and cache rows; state was identical, and both
outputs passed `Hierarchy.check()`. Focused hierarchy tests and Ruff/mypy pass.

## Measurement and limits

Five alternating runs use 256 disjoint copies of the 8-vertex, 16-edge
witness-heavy component (2,048 vertices, 4,096 edges), refining z=8 to z=4.
Hierarchy/graph construction is outside the timed and traced region. Median
`refine_hierarchy` time changed from 419.946 ms to 410.625 ms (2.22% faster).
Peak traced allocation changed from 2,252,959 to 1,989,807 bytes (11.68%
lower). Tracemalloc is Python allocation, not process RSS or native capacity.

See the [raw comparison](../../benchmarks/results/paper/refinement-cycle-snapshots.json).

## Alternatives

- Remove cycle detection: rejected because matching-only ProcProcess transitions
  can occur without immediately shrinking U.
- Use probabilistic state hashes: rejected because cycle rejection remains exact.
- Keep all historical states: rejected because strict U shrink makes those
  states impossible to revisit.

## Follow-up

Migrate the remaining per-state snapshot on a stable U frontier without
weakening exact cycle detection. Continue reducing global partition and
phase-boundary reconstruction work, then qualify connected, skewed, and
multilevel refinement end to end.
