# 0099: Keep paper fan intake sparse

Date: 2026-10-04. State: implemented; synthetic preprocessing qualification
only, not full pruning throughput.

## Context

Paper `Pruning.seed`, `Construction.direct`, `Construction.collect`, and
`Spectrum.classify` copied all graph edges merely to check a supplied edge set.
Seed/direct/collect also copied all colored edges for overlap validation. In
addition, direct fan construction allocated one adjacency list and one missing-
color set for every vertex, including isolated vertices.

## Decision

Validate canonical supplied edges with `Graph.has_edge`, and test colored-edge
overlap with local `Partial` membership. Direct fan construction now stores
incidence rows and missing-color palettes only for endpoints of the supplied
uncolored edges. Collect delegates its intake validation to direct construction
instead of repeating it. Spectrum classification sorts the supplied set once
and validates it in that pass instead of creating a second normalized set and
sorting twice.

## Evidence and limits

A million-label graph double rejects any call to `edges()`. The regression
exercises seed, direct, collect, and Spectrum classification; direct construction
also processes a valid sparse edge and rejects reversed noncanonical input.
On a 100,000-label/one-edge fixture, five repeated current direct calls measured
median 0.018 ms and 2,264 traced peak bytes. Recreating the prior intake data
structures—whole-edge set, per-vertex empty incidence lists, and per-vertex
missing-color sets—measured 198.459 ms and 44,062,256 traced peak bytes. The
baseline measurement is that preprocessing shape, not a complete invocation of
the former fan algorithm. Custom Graph lookup complexity may differ from the
built-in constant-time backends. This is not end-to-end pruning or Matcher
qualification.
