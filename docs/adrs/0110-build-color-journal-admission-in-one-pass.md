# ADR 0110: Build color-journal admission in one pass

- Status: implemented; performance impact not separately measured
- Date: 2026-10-04

## Context

`Classes` admission retains the original class and seed roots so that first-
write undo can restore exact set/list identity. The capacity ceiling must cover
every original membership that this transaction could remove, while aliases
must be counted only once. The previous implementation built a unique-root
registry, then made a second pass over that registry to sum each set's O(1)
length.

## Decision

Construct the unique-root registry and accumulate its membership bound in the
same pass over class slots and the seed. Keep the exact bound, the 65,536-cell
floor, sparse first-write records, and explicit smaller capacities used by
bounded tests. Do not keep a separately mutable membership counter: the
coloring roots are mutable containers, and an independent counter would need
additional synchronization for every root and membership mutation to remain a
safe capacity bound.

## Consequences

- Automatic admission avoids a second O(number-of-roots) pass.
- Root registry construction and the alias-ownership audit remain O(number of
  color classes); this does not make transaction setup independent of class
  count.
- Exact capacity continues to scale with the retained class state without
  allocating that entire capacity in advance.
- No extra cache state, rollback field, or stale-count invalidation contract is
  introduced.

## Evidence and remaining qualification

The class journal tests cover repeated aliases, seed sharing, exact rollback,
explicit capacity boundaries, and a 65,537-membership state. Full-suite tests
establish behavior, not a measured speedup. Per-mode production timing and
remaining O(class-count) admission work are still open qualification items.
