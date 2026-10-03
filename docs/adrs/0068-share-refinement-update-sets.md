# ADR 0068: Avoid redundant update-set copies during refinement

Date: 2026-10-03  
State: Implemented; broader child-rebuild qualification remains open

## Context

The child rebuild made copies of `matcher.deleted_edges` and
`previous.deferred_deletions` before combining them, even though one set union
already produces the required owned combined set. It also copied
`matcher.inserted_edges` and each newly returned hierarchy's deferred-delete
set before passing them to the next refinement level. `refine_hierarchy`
validates and reads these arguments but does not mutate them.

## Decision

Use the set union operator directly for the one required combined deletion
set. Pass the Matcher-owned insertion set and each preceding hierarchy's
deferred-delete set by reference across refinement calls. The old hierarchy is
replaced after the call; the set is only read. Preserve a fresh empty insertion
set after the first level because those insertions are already part of the
projected graph.

## Correctness and ownership

`refine_hierarchy` performs membership, intersection, cardinality and sorted
iteration operations on the inputs but contains no mutation of either set.
The regression snapshots nonempty deletion/insertion inputs and proves they
remain unchanged after a complete valid refinement. The child rebuild's
transaction owns Matcher update sets, and no operation in the recursive loop
mutates them. Each deferred set remains owned by the preceding hierarchy until
that hierarchy is replaced; no other reader receives mutable access during
the serialized rebuild.

## Evidence and limits

An isolated 120,000-plus-120,000 edge-set probe compares the former
`set(left) | set(right)` expression with `left | right`. Both produce the same
180,000-element result. Traced peak fell from 20,972,168 to 12,583,128 bytes
(40.0%); final retained result allocation was 8,388,824 bytes in both cases.
This is an expression-level allocation probe, not a full rebuild or RSS
measurement. Passing the insertion/deferred sets by reference removes further
copies not included in this isolated comparison. See the
[raw probe](../benchmarks/results/paper/refinement-update-sets.json).

## Alternatives

- Clone every input before refinement: rejected because the callee is
  read-only and caller serialization already controls ownership.
- Mutate the caller's update sets in-place: rejected because these sets remain
  part of Matcher transaction state and are needed after child rebuilds.
- Reuse the old deferred set as the combined deletion set: rejected because
  current child deletions must be unioned without changing either source.

## Follow-up

Continue auditing state-sized copies at the phase boundary. Keep the
read-only-input regression if refinement starts editing update sets; then
introduce explicit ownership transfer or a bounded journal rather than silently
sharing mutable state.
