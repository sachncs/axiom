# ADR 0124: Admit a coloring once for local pruning certificates

- Status: implemented
- Date: 2026-10-04

## Context

`Pruning.construct` handles each alpha group by calling `prune` and `reduce`.
Those stages already maintain touched-edge coloring certificates, but each
stage also performed a complete coloring validation. A graph-wide audit per
group made the cost grow with the graph even when the update touched only a
small region. Removing those audits without a trust boundary would weaken the
existing validation contract for direct callers and newly supplied state.

## Decision

`ColorJournal` carries an admission bit through nested local journals. The
public construction path performs one complete validation before mutation and
one after all alpha groups finish. Between those boundaries, the admitted path
uses its first-write journal region for a final local coloring certificate,
alongside the existing per-mutation edge and fan certificates. Direct
`prune`/`reduce` calls with an unadmitted journal retain their full entry and
exit coloring audits. Failed local certification continues through the
existing journal rollback path.

## Consequences

- Multi-alpha construction no longer repeats a whole-coloring audit for each
  group after admission; local work remains proportional to captured edges.
- Direct callers do not inherit trust implicitly and retain full validation.
- Admission is revoked when construction exits and is not copied to the
  caller-owned journal, so later direct operations must revalidate their input.
- A construction still has full-coloring audits at both admission and final
  publication boundaries, and local fan compatibility checks remain in place.
- This changes audit frequency, not the coloring algorithm or durable batch
  boundaries. End-to-end throughput impact has not yet been separately
  measured.

## Verification

Regression tests use two disconnected uncolored components with different
alpha groups and verify the construction has exactly two full audits, local
certificates, deterministic output, complete edge coverage, proper coloring,
and compatible fans. An unadmitted direct reduction still performs both full
audits. Fault injection corrupts a touched coloring index after admission and
verifies exact restoration of assignments, incident indexes, and the full
coloring witness. The focused paper-coloring suite passes; broad performance
qualification remains open.
