# ADR 0125: Admit fan state once during pruning construction

- Status: implemented
- Date: 2026-10-04

## Context

`Pruning.construct` processes seeded uncolored edges by alpha group. Each
`prune` and `reduce` call previously rebuilt and checked every fan index and
walked every fan for coloring compatibility at its boundaries. For `g` groups
and `F` retained fans this repeated global work proportional to `gF`, even
though each collision/chain mutation already identifies affected vertices and
certifies their fan rows.

## Decision

The coloring journal's explicit construction admission is the trust boundary for
both coloring and fan state. Construction validates its initially empty fan
collection and, after all alpha groups, fully validates fan indexes and
compatibility. Between those boundaries, `prune` and `reduce` certify fan
indexes and compatibility only at vertices incident to their journaled coloring
edges; mutation paths retain their existing local repair/certificates. The
admission is scoped to the construction journal and is revoked on exit. Direct
calls without an admitted journal retain full fan checks at entry and exit.
Failure rollback continues to run full fan validation.

## Consequences

- Removes per-alpha whole-fan index reconstruction and compatibility walks from
  the admitted `construct` route.
- Retains full validation at construction boundaries and on failure; this is
  not a replacement for independent offline certification.
- Direct `prune`/`reduce` calls keep their conservative full-check behavior.
- The scaling regression proves two full fan audits for a two-alpha trace that
  creates a fan, plus local certificates and compatibility checks. This is
  structural work-count evidence; end-to-end throughput and allocation impact
  are not yet measured.

## Verification

Two independent collision gadgets are configured to seed different alpha
colors. Tests verify deterministic output, complete pending-edge coverage,
proper coloring, fan compatibility, exactly two full fan-index and compatibility
audits independent of the number of groups, and nonzero local fan checks.
Existing unadmitted-call tests retain full entry/exit audits; injected coloring
certificate failure restores the exact coloring witness. Existing fan
post-mutation failure coverage checks exact fan-index and coloring rollback.
