# ADR 0128: Compact Packed paper-index rows

- Status: implemented; constrained Linux qualification pending
- Date: 2026-10-04

## Context

ADR 0127 removed the large Python edge snapshots used only for `Packed`
admission. The next million-vertex CI attempt progressed beyond admission and
failed while `System.index()` retained one Python list of boxed neighbor
integers per indexed vertex. These Lambda/L rows are required by the paper
update algorithm, so omitting them or weakening their audits is not acceptable.

## Decision

For the exact native `Packed` graph backend, retain sorted cache rows as
unsigned 32-bit `array` storage. Keep ordinary lists for `Adjacency` and
caller-defined graph implementations. The graph universe already constrains
labels to this width. `System` deltas continue to use binary search and
in-place insertion/removal; `Systems` journals retain the original row object
and inverse edits, so rollback restores aliases and contents without copying
the row. Hierarchy certificates and exact-state witnesses accept the compact
representation explicitly.

The compact representation is an implementation detail of the paper index;
it does not change matching semantics, ordering, admission limits, or the
exhaustive checks retained for custom graph backends.

## Consequences

- Packed-backed Lambda/L indexes use four bytes per stored neighbor rather
  than a Python reference plus a separately allocated integer per neighbor.
- Row objects and map keys still have per-vertex overhead; this is not a claim
  that the complete paper engine fits every memory envelope.
- Mutable array rows require the journal, hierarchy checker, and witness
  encoder to preserve backend-specific row type and identity. Regression tests
  cover admission, edits, alias-preserving rollback, and exact state equality.
- A local macOS one-million-vertex, two-million-edge `System.build` smoke test
  reported `ru_maxrss` of 466,501,632 bytes (~455,568 KiB) after this change,
  versus 572,801,024 bytes (~559,376 KiB) with list rows. RSS is not the hosted
  worker's address-space limit; only the installed constrained Linux job can
  establish the release gate.

## Verification

Focused System, hierarchy, durable schedule, and transaction tests pass locally.
The revised installed Linux resource job and full hosted CI must pass before
this decision is treated as resource-envelope qualification.
