# ADR 0077: Bound PruneVFans rollback to changed spokes and created fans

Date: 2026-10-03  
State: Implemented; other paper snapshots remain

## Context

`Pruning.prune` previously copied all coloring assignments and materialized all
fans at entry. The routine's mutations are narrower: every coloring rotation
and exposed-edge assignment is on a center-to-leaf spoke in one of the colliding
Vizing fans, and the only fan mutation is adding a newly constructed fan.

## Decision

Use the reusable `ColorJournal` first-write before-image for spoke edges before
each exposure. Record newly constructed fans before adding them. If pruning
fails, restore only touched coloring cells through `Partial.replace` and discard
only fans created by this invocation. Successful and failed operations retain
the caller's coloring and fan container roots. Other paths whose mutations are
not tracked this way keep their existing full-snapshot rollback behavior.

## Correctness

`Pruning.expose` rotates only the supplied fan's center-to-leaf spokes, and its
following assignment colors the exposed edge in the same set. The journal
captures every leaf edge of the current and existing fans before an exposure,
deduplicating repeated edges across the loop. Existing fans are read but never
mutated by this algorithm; only fans listed in the invocation's created-fan log
can be removed during rollback. Failure injection after a created fan has been
indexed verifies exact coloring and fan values, stable roots, and retention of
an unrelated compatible sentinel fan. The existing failed-second-exposure
test still covers rollback after a partial color rotation.

## Evidence and limits

On a 50,008-vertex graph with 10,000 unrelated fans and 10,000 unrelated
colored edges, three traced runs measured peak temporary allocation of
19,994,184 bytes before and 19,476,056 bytes after (2.59% lower). Median elapsed
time moved from 189.46 ms to 182.93 ms (3.45% lower); this small timing result is
not treated as a performance claim. The measured snapshot reduction is
component-level and does not establish total RSS or whole-engine efficiency.
See the [raw comparison](../../benchmarks/results/paper/prune-bounded-rollback.json).

## Alternatives

- Copy the whole coloring and fan collection: rejected because touched spokes
  and the created-fan list are known as mutations occur.
- Roll back every fan by rebuilding all indexes: rejected; no existing fan is
  mutated by this operation.
- Remove rollback or swallow invariant failures: rejected; failure remains
  explicit after exact local restoration.

## Follow-up

The prune transaction's safety depends on the invariant that existing fans are
not mutated in this method and every coloring mutation passes through the
captured expose path. Keep mutation-site tests current if the algorithm changes.
Continue migrating `Pruning.construct`, `Color-Small`, and `Sparsify-Types`
snapshots separately.
