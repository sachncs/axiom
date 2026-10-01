# ADR 0001: Make the production target a verified workload contract

Date: 2026-10-01. Status: target explicitly accepted; qualification pending.

## Context

Vertex count alone does not specify memory or update work. Earlier evidence was
mostly at 32–2,048 vertices. Native storage construction at one million vertices
does not establish full matching throughput, acknowledgment durability, or query
consistency. The user has now explicitly required delivery of the production
target, not another storage-only demonstration.

## Decision

Qualify **at least 10,000 real edge updates/s on a graph with 1,000,000 fixed
vertices and average degree 4**, including durable acknowledgments and matching
queries. The initial graph therefore has approximately 2,000,000 undirected edges.
The primary sustained trace is balanced insertion/deletion churn around that edge
count. Count accepted real edge transitions; duplicate inserts, absent deletes,
rejected requests, retries, and merely queued requests cannot inflate the rate.

Report graph mutation, matching repair, journal, persistence, queue waiting,
publication, query latency, and end-to-end acknowledged latency separately.
Qualify on a declared machine/filesystem/storage stack with explicit limits.
Require independent proper/maximal matching, graph/version agreement, recovery,
and deduplication checks. Performance gained by weaker semantics is not success.

The workload must additionally exercise growth/drain, skewed hubs, bursts,
compaction/checkpoints, concurrent clients, duplicate requests, and overload.
Long-duration runs must expose retained-memory growth and maintenance costs.
The exact p99 SLA, query mix, hardware/RAM cap, maximum edge/degree envelope, soak
duration, and recovery-time objective remain to be specified and recorded before
final qualification; do not invent agreement on those values.

## Consequences and alternatives

At 509 updates/s the small basic-mode result needs approximately 20× improvement;
that is not a forecast at one million vertices. Ten thousand updates/s gives a
100 µs average serialized execution budget before queueing; a p99 or durability
promise does not follow from that arithmetic. Group commit may amortize barriers,
but delayed acknowledgment must be reported and bounded.

Batch storage speed, ingestion speed without matching, and eventually consistent
matching are rejected as substitutes for the accepted target. Billion-vertex
support remains unqualified and requires separate stages after the million gate.

## Evidence

No full-engine result meets this target yet. Existing measurements are linked in
[engineering.md](../engineering.md); record future qualification commands, source
revision, raw data, workload/configuration, resource caps, and failure outcomes.
