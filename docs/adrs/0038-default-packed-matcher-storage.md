# 0038: Default Matcher to bounded Packed graph storage

Date: 2026-10-03. Status: implemented; compatibility and full-engine sizing remain qualification work.

## Context

The native `Packed` backend was available but opt-in, leaving ordinary
`Matcher(n, ...)` construction with one Python set per vertex in `Adjacency`.
On the declared macOS/Python environment, fresh-process graph-only construction
at one million vertices reached approximately 251,069,016 bytes peak RSS for
`Adjacency` and 26,296,776 bytes for empty `Packed` (about 9.5x difference).
This measures graph construction only, not matching state, edges, durability,
or end-to-end workload performance.

## Decision

When callers omit `graph`, `Matcher` now creates `Packed(n, budget=budget)`;
`budget` defaults to 1 GiB and applies to that graph container. A caller-supplied
graph remains authoritative and unchanged. Callers requiring the Python reference
implementation can explicitly pass `Adjacency(n)`. Matching semantics and
algorithm selection (`basic`/`multilevel`) do not change.

## Consequences and limits

- The default graph layer avoids eagerly allocating a Python set object per
  vertex and rejects native graph growth before exceeding its per-container cap.
- This is not a process-wide memory limit. Matcher indexes, phase copies,
  allocator retention and SQLite/durable state remain outside this graph budget.
- The measurement does not qualify full Matcher memory or throughput at one
  million vertices; paper durable integration and broad per-mode qualification
  remain active.
- Code that accessed the undocumented `Matcher.graph.adj` implementation detail
  must pass `Adjacency` explicitly or use the graph protocol methods. Existing
  graph injection continues to preserve object identity.

## Verification

Default construction/budget behavior and ordinary insertion are tested. The
full suite exercises both paper modes and injected `Adjacency`/`Packed` backends,
including exact rollback and matching certificates. The graph-only RSS sample is
retained as a directional storage comparison, not as a release-scale claim.
