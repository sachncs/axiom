# 0035: Stage local fan-index updates before removing the old fan

Date: 2026-10-03. Status: implemented; success, collision, and injected partial
reservation failure tests pass.

## Context

`Fans.update()` discarded a live fan before constructing its replacement. An
exception during replacement construction or insertion could therefore leave
the fan collection missing a fan or with only some of its derived indexes
updated. This method runs while repairing fans after alternating-path flips, so
the failure could split the coloring and fan views.

## Decision

Construct the replacement and preflight its local separability constraints
before changing the live indexes. Reserve its membership, type, vertex/color,
and per-vertex fan-index cells first, recording a fixed-size undo bitmap. If any
reservation fails, remove only the newly reserved cells and retain all original
roots and entries. Once reservation succeeds, replace the old fan by applying
allocation-free removals/overwrites. Only the updated fan's constant-size
incidence is touched; the collection is not copied or globally revalidated.
Expected structural/separability failures still drop the damaged fan, matching
the post-flip contract.

## Verification and limits

Tests cover successful replacement with unrelated fan/root identity preserved,
expected collision removal, and an injected failure after membership, type, and
assignment reservations but during the assigned-color reservation. The latter
compares every collection root and entry with its exact pre-call snapshot. This
protects one fan update, not a transaction spanning multiple fan updates in one
`Fans.flip()`; that aggregate failure boundary remains part of paper integration.
