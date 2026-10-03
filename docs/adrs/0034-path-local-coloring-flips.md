# 0034: Apply alternating-path flips with local color-index deltas

Date: 2026-10-03. Status: implemented; focused paper tests pass.

## Context

`Partial.flip()` changed every path edge assignment, then rebuilt incident-color
sets and the vertex/color edge index for the entire graph. Its check happened
after assignments changed: if an endpoint already used its replacement color,
`reindex()` raised on the resulting improper coloring while leaving the new
assignments paired with stale old indexes. A short fan chain could therefore
incur O(n + m) repair work and corrupt state on a failed precondition.

## Decision

Validate the alternating colors, every touched edge/index cell, and both
endpoint replacement colors before mutation. Reserve the only new endpoint
incidence/index entries first, undoing partial reservations if allocation fails.
Then update path edge colors and the corresponding path-local index cells; only
the two endpoint incidence sets change. Interior vertices retain both colors.
This makes a valid flip O(path length), with O(path length) temporary control
storage, rather than rebuilding indexes for all vertices and colored edges.
Empty one-vertex paths remain no-ops, including the equal-color case used by
the spectrum transition.

## Verification and limits

Tests verify a proper nontrivial flip without calling full reindex, and reject a
path whose endpoint lacks its required replacement color while preserving the
exact assignments, incident sets, index contents, and root identities. The full
paper suite exercises spectrum's empty-path behavior. Full independent coloring
audits remain appropriate at phase boundaries and in differential tests; this
local certificate does not make arbitrary external edits to `Partial` safe.

The reproducible paper benchmark compares the new path-local operation against
the former full `reindex()` behavior on the same 50,000-vertex sparse coloring
(four colored edges, 20 flips, seven samples; macOS 26.7.1 arm64, Python 3.14.8).
Median timed operation was 0.113 ms path-local versus 333.946 ms full-reindex,
and separate peak traced allocations were 1,544 versus 30,023,640 bytes. Both
scenarios produced the same coloring checksum. This roughly 2,960× microbenchmark
result is specific to a four-edge path in a large sparse coloring; it is not a
paper algorithm throughput or durable service qualification.
