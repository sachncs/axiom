# ADR 0126: Audit retained paper state before durable acceptance

- Status: implemented
- Date: 2026-10-04

## Context

`Durable.check()` previously verified SQLite graph storage, partner-map
consistency, matching-edge membership, and maximality, but could accept a state
whose paper-mode partition, hierarchy, color-class, or rematching indexes were
corrupt. Recovery and backup call this audit, so matching-only validation was
not a sufficient production integrity boundary. Full validation is state-sized
and must remain outside the update hot path.

## Decision

Add `Matcher.audit()` as an explicit, mode-aware diagnostic and call it from
Durable's audit after the graph storage check. Basic validates its current
partition and live Lambda/L caches, omitting System M and degree/P1/P2 checks
that are phase-owned and are not invariants between rebuild boundaries.
Multilevel validates the live deferred-edge hierarchy, cross-references, and
I3 index. Both modes validate matching edges and partner/vertex views, retained
color-class matchings and seed roots, plus the complete auxiliary
inserted-edge/H/H-tilde/S-hat indexes. Operation-local Vizing fans and partial
colorings are certified by the algorithms that create and mutate them; they
are not persistent Matcher roots.

The audit is used by recovery, backup preflight, and explicit `check()` only.
It does not execute on each accepted update. Any false result fail-stops the
Durable owner.

## Consequences

- Corruption in mode-specific retained state is detected even when the graph
  and reported matching remain a valid maximal matching.
- Durable state is independently checked in both modes rather than inheriting
  one mode's audit assumptions.
- Explicit checks/recovery cost more than a graph/matching-only audit and scale
  with retained graph, hierarchy, class, and auxiliary-index state.
- This does not add a serialized paper-state decoder or remove replay-linear
  startup work; the audit remains a verification gate after reconstruction.

## Verification

Both modes are audited after each request in a small mixed update trace and
after exact close/reopen comparison. Negative regressions corrupt Basic's
partition, Multilevel's hierarchy metadata, and mode-specific auxiliary index
rows without touching graph or matching state; `Durable.check()` rejects each
and fail-stops the owner. The focused Durable and paper-coloring suites pass.
