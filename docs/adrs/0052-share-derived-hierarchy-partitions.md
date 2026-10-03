# ADR 0052: Share derived hierarchy partitions

Date: 2026-10-03

## Context

`Hierarchy` retained `A1` and `N1` as complete copies of the first
`A_levels`/`N_levels` entries. `A2` was also always rebuilt as a set union of
all upper A-levels, even when exactly one such level was nonempty. These are
derived roots; retaining duplicate hash tables wastes memory without adding
information.

## Decision

- Built hierarchies bind `A1` directly to `A_levels[0]` and `N1` directly to
  `N_levels[0]`.
- If no upper A-level is populated, `A2` remains an empty set. If exactly one is
  populated, `A2` points to that partition. If two or more are populated, build
  an independent union so the hierarchy's value semantics remain exact.
- Keep the dataclass fields, names, membership behavior and transaction root
  inventory unchanged. Aliasing makes mutations through either name affect the
  same partition, which also prevents those two names from drifting apart.

## Alternatives considered

- Remove the compatibility fields: rejected because callers and existing tests
  construct or inspect `A1/A2/N1` directly.
- Recompute every derived union on access: rejected because it would trade
  retained storage for repeated whole-partition allocation and iteration.
- Always retain independent sets: rejected because the duplicate contains no
  additional state when derived values equal an existing partition root.

## Evidence

[`hierarchy-partition-aliases.json`](../../benchmarks/results/paper/hierarchy-partition-aliases.json)
records an isolated one-million-label shape with one 500,000-member upper A
level. Materializing its duplicate union peaks at 16,778,056 traced bytes;
selecting the existing root peaks at 904 bytes. Deterministic hierarchy tests
cover the alias case and the multi-nonempty-level independent-union case, along
with full `Hierarchy.check()`.

## Consequences

Common derived roots no longer duplicate large partition tables. A2 still
materializes an independent union when multiple upper levels contribute, and
other hierarchy snapshots/certificates remain state-sized. This diagnostic
does not establish whole-process memory bounds.
