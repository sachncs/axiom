# ADR 0105: Index Extend projection assignments by color

- Status: implemented; end-to-end qualification remains open
- Date: 2026-10-04

## Context

For each disjoint color group, `Extension.project` previously rescanned every
colored edge to collect that group's scope. A decomposition into g groups thus
performed O(gm) assignment visits for m colored edges. Fan selection similarly
needed to avoid sorting/materializing the complete parent fan collection.

## Decision

Build one temporary `ColorIndex` per Extend decomposition, grouping references
to existing edge keys by their current color. Each recursive sibling selects
only colors in its disjoint group. Index fan types by exact two-color pair and
select using whichever is smaller: the group's candidate color pairs or the
set of existing fan types. Selected fans remain deterministically ordered.
Direct `Extension.project` calls build a local index when one is not supplied.

The temporary assignment index is O(m) references and is released after the
decomposition. This trades a bounded transient allocation for avoiding repeated
full-coloring scans; the allocation remains a graph-sized structure and must
be counted in peak-memory qualification. Recursive child graphs/scopes are
unchanged by this decision.

## Consequences

- Tests prohibit a full parent-coloring rescan after the index is built and
  verify color-group scope isolation, fan type selection, deterministic order,
  and unchanged parent state.
- Large groups do not enumerate every possible color pair when the indexed fan
  type set is smaller; small groups do not scan all fan types.
- One isolated selection probe improved 100k assignments/10 groups by 2.69x,
  while the index retained about 852 KB of traced Python allocations. The
  sample is not an end-to-end Extend or Matcher performance result.

## Evidence

See [`extend-color-index.json`](../../benchmarks/results/paper/extend-color-index.json).
