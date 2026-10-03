# ADR 0089: Derive the refinement B partition in exact cycle keys

Date: 2026-10-04
State: Implemented; cycle keys and other hierarchy snapshots remain

## Context

The ProcProcess cycle key contains U, A, B and the selected matching. During one
refinement, `old_u` is a copy of the previous U partition and `previous.B` is
fixed. Initially, every `previous.B` vertex is assigned to exactly one of the
new A/B partitions. Every promotion removes one vertex from U and adds it to
exactly one of A/B. Normalization moves vertices from B to A by removing before
adding. No operation adds vertices to both sides or moves one back to U.

Thus the three sets are a disjoint partition of the fixed universe
`previous.B ∪ old_u`. Given the exact U and A sets in the key, B is uniquely
determined as the remaining universe members.

## Decision

Remove `frozenset(new_b)` from the exact cycle key while retaining U, A, and the
chosen matching. Equality remains exact: for this fixed call, two states with
equal U, A and matching necessarily have equal B. Keep the partition mutation
rules and ProcProcess ordering unchanged.

## Correctness evidence

Existing refinement tests verify the exact selected matching, partitions,
deferred-edge behavior and complete hierarchy certificates. Five alternating
baseline/candidate runs compared canonical state across all levels, caches and
partitions; outputs were identical and passed `Hierarchy.check()`.

## Measurement and limits

Five alternating runs use 256 disjoint copies of the 8-vertex/16-edge
witness-heavy fixture (2,048 vertices, 4,096 edges), refining z=8 to z=4.
Graph and base hierarchy construction are excluded. Median traced peak changed
from 1,654,111 to 1,621,095 bytes (2.00% lower). Median elapsed time changed
from 258.731 ms to 256.876 ms; this is within small-sample noise and is not
claimed as a speedup. Tracemalloc excludes process RSS and native capacity.

See the [raw comparison](../../benchmarks/results/paper/refinement-b-partition.json).

## Alternatives

- Keep both A and B in each exact key: rejected because one side is exactly
  derivable from the other side and U over the fixed partition universe.
- Use a digest of the complete state: rejected because exact repeat detection is
  retained and no hash collision may alter behavior.
- Derive U or A instead: rejected because those sets are needed directly by the
  algorithm and retaining B derivation is the smaller safe change.

## Follow-up

Continue eliminating stable-frontier full-set snapshots and parent-boundary
rebuild copies. Validate the partition invariant under connected, dense, and
adversarial transition families before claiming broader paper-engine reliability.
