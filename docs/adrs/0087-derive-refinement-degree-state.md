# ADR 0087: Derive refinement degree state from the selected matching

Date: 2026-10-04
State: Implemented; other exact cycle-key fields remain state-sized

## Context

After [ADR 0086](0086-bound-refinement-cycle-snapshots.md) bounded cycle-key
history to the current U frontier, each key still copied `tuple(enumerate(degree))`.
That tuple contains n vertex/counter pairs. In `refine_hierarchy`, `degree` is
the selected-matching degree vector, not graph degree: it starts at zero, then
adds one for each endpoint of every edge in `chosen`. Each later chosen-edge
insertion increments both endpoint counters and each removal decrements both.
The graph is fixed during ProcProcess.

Thus `(fixed graph, chosen)` already determines the degree vector exactly.
Retaining another n-cell copy in every key stores derived state and increases
both memory and key-hash/equality work.

## Decision

Remove the derived degree vector from the exact cycle key. Keep the U, A, B,
and chosen-edge sets in the key, so equality remains collision-safe and exact;
this does not replace exact state comparison with a probabilistic hash. Keep
degree mutations paired with chosen-edge mutations and preserve all process
ordering and cycle failure behavior.

## Correctness evidence

Inspection confirms the only mutations to `chosen` within refinement are its
initial construction, defensive U-U removal, U-neighbor insertion, and B-witness
edge swaps. The latter three all update both endpoint degree counters in the
same operation. Five before/after refinement runs produced equal canonical
hierarchy state, including every level's partitions, matching, and cache rows;
both versions passed `Hierarchy.check()`. Existing exact-output and adversarial
refinement regressions pass.

## Measurement and limits

Five alternating runs use the 2,048-vertex, 4,096-edge fixture with 256
disjoint copies of the 8-vertex/16-edge witness-heavy component, refining z=8 to
z=4. Graph and base hierarchy construction are excluded. Relative to the
immediately preceding implementation (which already clears obsolete U-frontier
history), median time changed from 414.231 ms to 396.461 ms (4.29% faster), and
peak traced Python allocation changed from 1,989,839 to 1,654,047 bytes (16.88%
lower). Against the pre-ADR-0086 implementation, combined peak reduction is
26.59% and elapsed-time reduction is 5.59%. The measurement is not process RSS
or full matcher/service qualification.

See the [raw comparison](../../benchmarks/results/paper/refinement-degree-state.json).

## Alternatives

- Keep degree in every cycle key: rejected because it is deterministically
  derived from the chosen matching and maintained in lockstep.
- Replace exact state keys with a digest: rejected; ordinary hash collisions
  must not be able to trigger false cycle rejection or hide a repeated state.
- Recompute and certify the full degree vector before every comparison:
  rejected on the update path because it would add O(n + |M|) work per pass.

## Follow-up

Reduce the remaining U/A/B/chosen cycle-key copies without weakening exact
repetition detection, and remove other global partition/phase-boundary work.
This change does not integrate paper modes into durable production.
