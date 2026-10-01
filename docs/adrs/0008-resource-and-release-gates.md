# ADR 0008: Scale by bounded ownership and evidence, not worker count or optimistic rates

Date: 2026-10-01. Status: partial foundations; full-service gates pending.

## Context

Extra workers cannot remove global snapshot costs or safely mutate one matching
without a concurrency protocol. Short traces hide phase/maintenance tails,
memory growth, disk behavior, and overload. Native code adds ABI and memory-safety
risks that Python-only CI did not cover.

## Decision

Start with one mutation owner per connected graph and appropriately sized native
storage. Independent graphs may use independent workers. Query concurrency must
obey committed-version visibility. Distribution of a single graph requires a
separate cross-partition repair/commit/recovery design, not arbitrary edge shards.

Bound vertices/edges, applicable degree/work, undo/WAL batch, admitted queue,
checkpoint/rebuild backlog, compaction coexistence, retained readers, dedup state,
and recovery memory. Reject/backpressure before exceeding a limit. Surface these
limits and failure/degraded status; per-container budgets are not enough.

Qualification progresses 32k → 128k → 1m before larger experiments, using fresh,
isolated runs with declared CPU/RAM/time/storage limits. Compare identical trace
digests, real transitions, proper/maximal certificates, end-to-end acknowledged
rates, p99/max latency, and constructor/retained/transient/process memory.
Include maintenance in sustained measurements rather than timing only the best
ordinary update. Record query mix, batch policy, journal/queue pressure, and
recovery/checkpoint times. Repeat and soak; report failures/timeouts honestly.

Inject failure at reserve, graph edit, matching repair, certification, WAL write,
durability barrier, commit marker, publication, acknowledgment, and recovery.
Exercise retries, duplicate/reordered operations, process death, disk-full,
corrupt/truncated inputs, and subsequent valid use. Require state/version/outcome
agreement with the defined reference contract. Test power failure separately
where that durability claim is made.

Keep native ASan/UBSan differential stress, Python optimized-mode tests, strict
typing/lint, coverage, artifact reproducibility, isolated wheel/source installs,
and documentation example execution in release gates. Platform wheels need an
explicit supported matrix; success on one development Mac is insufficient.

## Consequences and alternatives

The target remains unmet until all relevant requirements have authoritative
evidence; passing unit tests or allocating a million vertices is not completion.
Billion-vertex claims require 10m/100m stages and a separate qualified workload.
Unbounded developer-workstation experiments, disabling checks, and extrapolated
storage-only rates are rejected.

## Evidence

Native container budgets, sanitizer tests, reference comparisons, benchmark
subprocess time caps, artifact/CI checks, and million-vertex storage measurements
exist. Corrected CI `08eb153` passed all jobs, including Python 3.10–3.13 clean
installs/tests, documentation examples, package checks, and bounded stress.
The first durable layer now provides fail-fast ownership/admission, bounded
history/groups, database page limits, replay checks, and process-death/storage-full
tests. Opt-in native checkpoint compaction now bounds retained history/replay;
bounded local aggregation is implemented in ADR 0011. Hard service RSS/WAL/disk
accounting, overload/work-class admission, full matcher qualification and production
latency/memory gates remain pending.
