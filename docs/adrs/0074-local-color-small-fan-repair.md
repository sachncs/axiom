# ADR 0074: Repair only fans touched by Color-Small activation

Date: 2026-10-03  
State: Implemented; other global repair and snapshot paths remain

## Context

Each Color-Small activation captured every fan's type and then globally scanned
all fans for compatibility damage, even though the coloring mutation is limited
to one alternating path and the activated fan's spokes. With F independent fans,
repeating these O(F) passes for O(F) activations caused quadratic fan traversal.

## Decision

`Fans.repair` accepts an optional set/iterable of changed vertices. In local mode,
it obtains candidates through the existing vertex-to-fan index, so only fans
incident to those vertices are checked. `Construction.activate` supplies all
vertices on the selected alternating path plus the activated fan's center and
leaves. It snapshots pre-activation types only for fans in that local region,
removes surviving fans whose type changed, colors the exposed spoke, and repairs
the same region. Color-Small no longer repeats its own whole-collection type
snapshot and global repair after each activation. Calls without a changed-vertex
set retain the global repair behavior for callers without a local mutation
certificate.

## Correctness

The operation changes colors only on vertices of its alternating path and on
the center/leaf endpoints of its exposed spoke. A fan can become incompatible
only if one of its assigned colors is no longer missing at a touched vertex or
one of its spokes becomes colored; in either case the affected fan contains an
endpoint in the supplied region and is present in the vertex-to-fan index.
Deterministic multi-component coverage asserts that Color-Small exhausts every
fan, completes the expected edges, retains coloring validity, and does not
iterate the whole collection for each activation. A separate test verifies
local repair leaves disjoint untouched fans intact.

## Evidence and limits

On 400 disjoint activation gadgets (1,600 vertices, 1,200 edges, 400 fans),
three Color-Small runs measured median time of 144.78 ms before and 6.64 ms
after (21.82x), with exact progress and complete coloring/fan checks. This is a
synthetic single-host component benchmark; it excludes setup, does not measure
peak memory, and does not qualify connected/adversarial fan distributions or
whole Matcher behavior. See the
[raw comparison](../../benchmarks/results/paper/color-small-local-repair.json).

## Alternatives

- Recheck every fan after each activation: rejected because the changed region
  is known and the repeated scan scales quadratically on independent fans.
- Omit compatibility validation: rejected; the local index selects candidates
  while retaining immediate validation of every potentially affected fan.
- Apply local mode to callers without a proven mutation region: rejected; they
  retain the global fallback.

## Follow-up

Migrate other mutation sites to explicit changed-vertex/edge regions only when
their mutation boundaries are proven, then measure remaining snapshots and
phase-wide audits independently.
