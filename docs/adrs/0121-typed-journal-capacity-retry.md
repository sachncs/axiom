# ADR 0121: Retry typed paper-journal capacity failures

- Status: implemented
- Date: 2026-10-04

## Context

Durable paper updates split a group into bounded Matcher transactions. When a
component journal cannot admit its write set, Durable reconstructs the last
committed paper state and retries with a smaller private slice. This is an
engineering recovery policy: smaller slices reduce cumulative journal demand;
they cannot repair a single update whose intrinsic write set exceeds a journal
limit. Per-row System journaling was changed to inverse deltas in ADR 0119 so a
large sorted cache row no longer consumes journal space proportional to the
entire row.

The retry decision previously searched arbitrary `MemoryError` text for the
phrase `journal capacity exceeded`. That coupled control flow to diagnostics
and could misclassify an unrelated memory failure as retryable capacity
pressure.

## Decision

Paper component journals raise the shared `JournalCapacityError` subtype of
`MemoryError` when their configured cell bound is reached. Native graph storage
uses that same Python exception when its configured memory budget cannot admit
another undo record. Durable retries only that type. A native allocator failure
(`std::bad_alloc`) remains an ordinary `MemoryError`; it is not treated as
retryable journal pressure. Other allocation failures propagate through the
ordinary atomic failure path and restore the last committed paper state; they
are not silently retried under a different batch shape.

## Consequences

- Capacity retry is explicit and independent of human-readable error wording.
- Existing callers catching `MemoryError` remain compatible with the subtype.
- Native undo-budget exhaustion can use the same bounded smaller-slice retry
  policy as Python paper journals without weakening the configured budget or
  confusing allocator exhaustion with journal admission.
- The finite per-component journal limits remain in place; an intrinsically
  oversized single update can still fail atomically and must not be described
  as automatically scalable.
- SQLite retains one commit boundary for the whole accepted Durable group.
  Successful intermediate Matcher slices are private and are discarded by
  replay if a later slice fails before persistence.

## Verification

Both Basic and Multilevel tests inject typed capacity pressure and verify
smaller-slice retry, cross-slice rollback, exact reopen state, and retryability.
Native storage tests verify that undo-budget refusal has the exact shared
exception type, does not mutate the rejected edit, and still rolls back prior
edits exactly; other native allocation/capacity failures retain their existing
classification.
A new negative regression injects an unrelated `MemoryError` whose message
contains the former retry phrase; Durable makes exactly one attempt, restores
the committed state, and remains usable.

A current one-million-vertex, average-degree-four smoke committed 4,096 real
updates in one 4,096-operation group for each mode. Both runs passed the
independent audit, 4,096 idempotent retry checks, and exact replay. Basic
measured 2,421 updates/s, 1.67 s group publication latency, 14.19 s recovery,
and 1.46 GB peak RSS. Multilevel measured 3,344 updates/s, 1.20 s group
publication latency, 19.91 s recovery, and 1.91 GB peak RSS. The runs used
Python 3.11.16 and SQLite 3.53.1 on macOS arm64; they are single-run diagnostics,
not repeatability evidence. Neither qualifies the 10k/s goal or hard resource
limits.
