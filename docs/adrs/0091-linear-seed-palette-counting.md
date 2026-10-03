# ADR 0091: Count seed palette frequencies in one edge pass

Date: 2026-10-04
State: Implemented; large high-degree qualification remains

## Context

When recursive paper seeding produced a palette wider than `delta + 1`,
`Paper.seed` chose two least-used colors by counting each palette color with a
fresh scan of every combined edge color. For E colored edges and C palette
colors this did O(E*C) comparisons, even though every edge has exactly one
color and all frequencies can be accumulated together.

## Decision

Allocate one count per palette color, traverse `combined.values()` once, and
sort the palette indices by `(frequency, color)` to preserve the existing
deterministic tie-break. The frequency phase is now O(E+C log C), replacing
O(E*C+C log C). Subsequent retained-edge extraction/remapping is unchanged.

## Correctness evidence

A deterministic K34 complete graph has `delta=33`; its balanced partition
produces two child palette widths whose sum exceeds `delta + 1`, forcing the
reduction path. The regression asserts this precondition, runs `Paper.seed`,
and certifies that every edge receives a proper color within the requested
palette. Existing seeded family and randomized coloring tests remain active.

## Measurement and limits

Three alternating seed runs on the same K34 graph, each followed by complete
color certification, compared the previous implementation to the candidate.
Elapsed seconds were 1.219419 / 1.154117 on the first cold pair, then
1.152478 / 1.178922 and 1.174880 / 1.177317. The later warmed runs are neutral;
no speedup is claimed. Traced peaks were approximately 537 KB for both paths.
The fixture has only 561 edges and a 36-color pre-reduction palette, so it
validates the branch and output but does not measure the asymptotic advantage at
large E or C. No graph-level or service throughput claim follows.

## Alternatives

- Keep one complete edge-color scan per palette color: rejected because its
  O(E*C) frequency work is unnecessary.
- Use a histogram keyed by observed colors: unnecessary because colors are
  already dense integer indices in `[0, palettesize)`.
- Change least-frequency tie-breaking or the number of removed colors: rejected
  because it would alter deterministic paper-seed behavior.

## Follow-up

Benchmark high-degree recursive seed workloads at larger graph and palette
sizes, while tracking end-to-end coloring time and memory. Continue migrating
remaining graph-sized paper snapshots and global hierarchy operations; durable
paper-mode integration is still pending.
