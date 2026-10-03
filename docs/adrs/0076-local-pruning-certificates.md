# ADR 0076: Use local certificates inside Vizing pruning

Date: 2026-10-03  
State: Implemented; global audits retained at operation boundaries

## Context

`Pruning.reduce` may activate one local Vizing chain at a time. After each
activation it rebuilt blocked-color rows from every fan, scanned all coloring
and fan state, and ran full compatibility checks. A sequence of q activations
over F unrelated fans repeated O(F) fan work q times. The chain edges and spokes
provide an explicit mutation region.

## Decision

`BlockedColors` exposes the same Mapping semantics while retaining the owner
fan index and indexing only active u-edge center colors. Vizing leaf-color
selection queries the fan-assigned colors at the current candidate vertex
directly, so constructing blocked colors no longer copies the whole fan
collection. `Fans.repair`, `Fans.certify`, `Fans.compatible`, and
`Partial.certify` check the vertices/edges covered by the activated chain or
colliding chains inside the loop. Full coloring, fan-index, and compatibility
audits remain at `Pruning.reduce` entry and exit.

## Correctness

The selected chain's path edges and center-to-leaf spokes contain every edge
that Vizing activation can recolor or color; their endpoints contain every
vertex whose missing-color or fan-spoke compatibility can change. Collision
resolution supplies both chains' path/spoke regions. `Partial.certify` audits
the changed edge/index cells and all incident neighbors at touched vertices.
`Fans.certify` checks local member, type, assigned-color, assignment, and spoke
rows; `Fans.compatible` checks every fan indexed at those vertices. Independent
full audits still run before and after reduction. Tests corrupt local fan
assignment state to prove the scoped certificate rejects it, and count fan
collection iterations across multiple edge activations to prevent a return to
per-activation full scans.

## Evidence and limits

On 4,000 unrelated fans plus 100 independent uncolored edge activations
(12,208 vertices, 8,100 graph edges), five alternating runs measured median
`Pruning.reduce` time of 2.730 seconds before and 0.0480 seconds after (56.88x).
All 100 edges were extended, followed by full coloring/fan audits. The
disconnected fixture is a targeted scan-amplification diagnostic; connected,
skewed, allocation-peak, and end-to-end qualification remain open. See the
[raw comparison](../../benchmarks/results/paper/pruning-local-certificates.json).

## Alternatives

- Rebuild blocked colors and run full audits after every activation: rejected
  because the exact mutation region is already available and repeated fan work
  scales with qF.
- Remove validation: rejected; local certificates run immediately and full
  independent audits remain at the operation boundary.
- Apply local checks to callers without a complete changed-region certificate:
  rejected; those callers retain global repair/audit behavior.

## Follow-up

Measure connected and hub-skewed collision sequences. Apply scoped certificates
to additional pruning/rebuild boundaries only after proving their complete
changed-edge and changed-vertex sets.
