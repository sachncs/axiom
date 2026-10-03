# ADR 0061: Store paper coloring incidence rows sparsely

Date: 2026-10-03  
State: Implemented; remaining graph and end-to-end qualification open

## Context

`Partial` allocated an empty Python `set` for every vertex during construction
and again during `reindex()`. Full `validate()` also allocated one empty set per
vertex. A million-vertex graph therefore paid for millions of Python objects
even when the partial coloring contained only a handful of edges. Recursive
`Extension.project` also allocated a zero-valued degree-dictionary entry for
every vertex, although only endpoints in the selected edge scope need counts.

## Decision

Store only nonempty incident-color rows. Read-only missing/vacancy/availability
queries use non-mutating dictionary lookups; assigning a color creates rows for
its two endpoints, while unassigning the final color removes empty rows. Reindex
and full coloring validation build their independent indexes only from colored
edge endpoints. `Extension.project` similarly counts degrees only at endpoints
in its selected edge scope.

The public `incident` mapping remains a plain dictionary for compatibility. Its
key set now means “vertices with at least one colored incident edge”; callers
must not rely on eager empty rows for all graph vertices.

## Guarantees and limits

Proper-coloring, edge-color index, failure rollback, and independent full
validation semantics are unchanged. Constructor and validation scratch now scale
with colored endpoints rather than the graph's entire vertex universe. Recursive
projection still creates an isolated child graph, which can itself be
O(vertices) under the Python `Adjacency` reference backend. That remaining
representation cost is not hidden by this change. Native `Packed` graphs and
durable production throughput are separate concerns; no billion-vertex support
claim follows.

## Evidence

- A one-million-vertex `Partial` constructor now creates zero incidence rows,
  used 656 traced peak bytes, and took 12 microseconds in one sample after the
  source graph was prepared.
- A deterministic million-vertex projection with two colored edges was measured
  under `tracemalloc`. Before the change it peaked at 878,257,592 bytes and took
  5.224 s; after sparse incidence and endpoint-only degree counting it peaked at
  224,457,760 bytes and took 1.029 s. Timing includes tracing and is not an update
  throughput measurement. The residual peak is primarily the full-universe
  Python `Adjacency` child graph, which this change intentionally does not alter.
- Regression coverage proves empty construction and isolated queries retain no
  rows, endpoint assignment creates exactly two rows, unassignment removes them,
  reindex stays sparse, and full validation succeeds. Existing injected
  transaction-failure tests continue to compare exact index state.

## Alternatives

- Keep all-vertex empty sets: rejected because the per-vertex object dominates
  memory at sparse colorings.
- Use a `defaultdict(set)`: rejected because read-only queries would mutate the
  index and turn isolated probes into retained allocations.
- Replace the public mapping with a custom sparse row container: unnecessary;
  ordinary dictionary lookup and explicit mutation preserve existing behavior.
- Replace the reference `Adjacency` child graph with another backend in this
  change: deferred because it changes graph-backend ownership and compatibility.

## Follow-up

The reference `Adjacency` child-row allocation in recursive color-group
projection is addressed by [ADR 0062](0062-compact-paper-projection-graphs.md).
Continue with recursive extension resource limits and adversarial workloads;
this local probe still does not establish end-to-end scale.
