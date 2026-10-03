# ADR 0080: Journal Color-Small path coloring

Date: 2026-10-03
State: Implemented; fan before-images and broader qualification remain

## Context

`Construction.small` can process many u-fans, but its failure handler copied
every colored edge before beginning. Each activation already computes the exact
alternating path it will flip and the single previously uncolored spoke it will
color. Consequently the coloring rollback copy scales with the whole partial
coloring even when the operation touches a small fraction of its edges.

## Decision

Allow `Construction.activate` to enlist those path edges and the activated
spoke in an enclosing `ColorJournal` before mutation. `Construction.small`
owns one journal for the complete operation, so first-write before-images span
all activations. On failure, restore touched coloring cells in place and retain
the existing fan rollback. Full coloring/fan validation and compatibility
checks remain at operation boundaries.

## Correctness evidence

A deterministic two-fan fixture injects a failure after the second activation
has completed. It checks exact coloring and fan contents, preserves all
coloring and fan container roots, and runs full validators and compatibility
checks after rollback. The normal fan-activation regression and the full paper
coloring suite exercise successful activation. Journal capture occurs only
after the selected alternating path is known and before its first mutation.

## Allocation evidence and limits

Five alternating fresh-state samples on a 53,000-vertex fixture with 25,000
unrelated colored edges and 1,000 independent fans measured median traced peak
of 22,480,136 bytes before and 21,206,536 bytes after (5.67% lower). Setup and
post-operation full validation were excluded. This probe measures temporary
allocation, not elapsed time, process RSS, connected/skewed workloads, or
end-to-end paper/Matcher throughput. The fan rollback still retains a tuple of
all original fans and is itself a state-sized snapshot.

See the [raw measurements](../../benchmarks/results/paper/color-small-rollback.json).

## Alternatives

- Keep a complete assignment dictionary: rejected because activation already
  provides an exact bounded mutation region.
- Remove rollback or weaken full validation: rejected; atomic semantics and
  boundary certificates remain.
- Claim all Color-Small rollback is bounded: rejected because fan before-images
  still scale with the full fan collection.

## Follow-up

Design a first-write fan collection journal spanning `Fans.flip`, local repair,
and activation, then qualify failure at each mutation point. Measure connected
fan chains, high-degree/skewed inputs, elapsed time, allocations, and process
RSS independently. Review sibling Vizing/pruning snapshot paths separately.
