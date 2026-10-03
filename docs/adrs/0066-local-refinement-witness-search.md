# ADR 0066: Find refinement witnesses through incident graph edges

Date: 2026-10-03  
State: Implemented; broader paper-engine qualification remains open

## Context

The second `ProcProcess` branch in `refine_hierarchy` chooses B-neighbors for
matching swaps. To establish that a B vertex has its required selected M-edge
into U, the implementation scanned the entire `chosen` matching for each
candidate. A matching contains at most one edge incident to a given vertex,
and `chosen` is already available for constant-time edge membership tests.
Searching all selected edges therefore repeated global work where the working
graph already provides the incident-edge neighborhood.

## Decision

Search `working_graph.neighbors(neighbor)` for a partner that is in `new_u` and
whose canonical edge belongs to `chosen`. Do not construct a second matching
index. Preserve the existing candidate order and witness selection behavior;
the simple-graph matching invariant means a vertex has at most one such
selected witness.

## Correctness and failure behavior

The working graph is the exact graph used by this refinement: it retains the
selected deferred deletions and includes the requested insertions. Requiring
both `partner in new_u` and canonical-edge membership in `chosen` is equivalent
to the former full-matching predicate. If fewer than `need` B-neighbors have a
witness, the existing explicit `RuntimeError` remains in force before swaps
are applied. The regression uses a fixed eight-vertex graph that executes two
swaps, checks the exact refined matching and full hierarchy certificate, and
verifies that the input graph remains unchanged.

## Evidence and limits

Three traced repeats compare the implementation at `e92cd69` with this change
on disjoint copies of that fixed graph. Graph and base hierarchy construction
are outside the timed/traced region. Median refinement time and maximum traced
peak bytes were:

| Components | Vertices | Prior time / peak | Candidate time / peak | State |
| ---: | ---: | ---: | ---: | --- |
| 64 | 512 | 0.0886 s / 470,395 B | 0.0823 s / 469,275 B | identical; certificate passes |
| 256 | 2,048 | 0.8298 s / 2,252,903 B | 0.8121 s / 2,252,975 B | identical; certificate passes |
| 512 | 4,096 | 2.8290 s / 4,953,343 B | 2.7825 s / 4,953,423 B | identical; certificate passes |

The samples show a modest 1.6–7.1% time reduction for this witness-heavy shape,
with no meaningful peak-allocation change. They do not establish general
refinement throughput, RSS, production/durable behavior, or the performance of
other refinement stages.

## Alternatives

- Keep scanning all of `chosen`: rejected because it repeats matching-wide
  work for local witness queries.
- Build and retain a per-vertex matching-partner map: rejected because the
  graph's incident rows already provide the needed candidates and a second
  index would add O(n) state and mutation obligations.

## Follow-up

Continue adversarial refinement profiling across degree distributions and
promotion patterns. Preserve the missing-witness failure test and exact
hierarchy checks when changing candidate selection or witness indexing.
