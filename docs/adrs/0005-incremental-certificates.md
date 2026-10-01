# ADR 0005: Maintain immediate local correctness certificates, not an unchecked mode

Date: 2026-10-01. Status: native production edge/matching certificates implemented;
paper hierarchy work and full-service qualification pending.

## Context

Scanning all graph edges, matching views, auxiliary indexes, and hierarchy levels
on every local edit is incompatible with the intended update budget. However,
successful speed tests alone cannot establish correctness. Periodic audits do
not substitute for mandatory pre-commit checks.

## Decision

For sealed native graph mutators, immediately certify the two endpoint degrees,
symmetric membership, edge-count delta, and logical version delta. The sealed,
non-subclassable/immutable native type has tested two-endpoint mutation semantics.
Opaque custom graph mutators retain full edge-set checks, including tests rejecting
no-op and extra-edge mutations. Do not infer locality for arbitrary caller code.

The native production matcher must maintain a certified proper maximal matching:
partner symmetry, live matching edges, matching count, and no edge with two free
endpoints. Derive affected dependencies from the complete write set, not just the
request endpoints. Prove/test that unaffected state cannot lose validity; reject
if immediate checks fail before publication. Keep full independent graph/matching
audits at initialization, recovery, checkpoints/qualification, and bounded
consistent audit points. Cache/dirty-propagation design is still pending.

For the paper engine, fan compatibility, complete/proper coloring, hierarchy,
forward/reverse auxiliary indexes, and phase graph agreement remain required.
No research invariant is removed just because the new production backend does
not own those structures.

## Consequences and alternatives

Certificates must cover every mutator and injected dependency corruption. Adding
a new write requires extending its validation/undo contract. A "fast mode" that
turns checks off, sampling checks only, or assuming maximality implies properness
is rejected. Independent audits must use one coherent committed version and
account scratch/latency rather than hiding their cost from qualification.

## Evidence

Native storage and production matching certificates, reference/corruption/budget
tests, and independent full audits are implemented. Three short million-vertex
churn runs passed separate exact graph/proper-maximal matching certificates via
public queries. These do not qualify durable service behavior or arbitrary-degree
latency. The paper matcher retains global matching/hierarchy checks; no paper
hierarchy incremental certificate implementation is claimed.
