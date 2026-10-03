# ADR 0055: Share the hierarchy-owned phase graph root

Date: 2026-10-03

## Context

At each multilevel rebuild, `Rebuild.multilevel` cloned `matcher.multi.graph`
into `matcher.phase_graph`. Repository-wide inspection found no algorithmic
reader of this separate mirror. `Hierarchy.sync_graph` updates the hierarchy's
graph in place, so the mirror was also stale between rebuilds. It nevertheless
retained an entire additional graph and was opened as a second transaction
participant (deduplicated by identity only when the objects happened to match).

## Decision

Keep `Matcher.phase_graph` for compatibility and inspection, but make it an
alias of `Matcher.multi.graph`. The hierarchy owns the graph and its edge
journal; the Matcher root snapshot preserves the alias assignment on rollback.
The atomic-update participant map deduplicates graph roots by object identity,
so the alias does not open a second graph journal.

Required phase-base graph snapshots are unchanged. This decision removes only
the redundant observational clone and does not introduce copy-on-write storage,
alter graph semantics, or claim that all paper snapshot costs are solved.

## Alternatives considered

- Keep the independent mirror: rejected because it is unused by production
  algorithm code, stale between rebuilds, and duplicates graph-sized native
  storage.
- Remove `phase_graph`: rejected to preserve the existing inspection surface
  and reduce compatibility impact.
- Replace all graph snapshots with overlays or persistent storage: deferred;
  that requires separate graph semantics and transaction/rebuild qualification.

## Evidence

Seven isolated `Packed.copy()` samples on a one-million-vertex,
one-million-edge native ring used 37,000,264 bytes for each cloned graph;
median copy time was 0.68 ms. The change removes one such retained clone per
multilevel rebuild. Timing is a component diagnostic, not a full Matcher
rebuild or RSS measurement.

Tests assert `phase_graph is multi.graph`, verify phase-edge exclusion remains
correct, and inject a multilevel rebuild failure to confirm graph identity,
contents, and rollback remain exact. The full graph journal still includes the
hierarchy graph once through identity deduplication.

## Consequences

Multilevel Matcher state retains one fewer full graph. Callers inspecting
`phase_graph` now observe the current hierarchy graph instead of an independent
rebuild-time copy; that copy had no algorithmic consumer. Snapshot migration is
incomplete: `phase_base_graph`, opaque custom-graph rollback fallback, other
state-sized paper structures, and durable paper integration remain open.
