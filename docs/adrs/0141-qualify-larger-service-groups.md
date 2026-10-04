# ADR 0141: Qualify larger atomic groups in the constrained resource trace

- Status: experiment queued; hosted rate and latency pending
- Date: 2026-10-04

## Context

The current constrained million-vertex trace completes its one-million-update
growth/drain cycle at about 7,115 acknowledged updates/s, below the 10k/s
qualification target. Its Service group size is 256. Durable accepts larger
bounded batches and commits each caller group in one SQLite transaction while
using bounded 256-operation Matcher journal slices internally. A local change
that consolidated Service receipt bookkeeping measured 6,988 versus 6,938
updates/s in single 200k-update mixed-query samples; that difference is too
small and noisy to claim as an improvement.

## Decision

Keep production defaults unchanged. For the isolated resource qualification
only, submit 512 requests per group and configure `max_batch=512`. Durable's
existing typed journal-capacity retry must continue to split paper work into
smaller atomic slices and persist the accepted outer group once. Verify every
receipt before the next group, and report the observed largest group.

## Consequences

- This tests whether reducing full SQLite commit count improves the constrained
  workload without changing the default production batch policy.
- A larger group can increase per-update acknowledgment latency and memory; the
  resource run must retain latency, resource-limit, rollback, and exact-recovery
  checks before the result can qualify.
- This experiment does not claim the 10k/s target. If rate does not materially
  improve without unacceptable latency, revert the resource-only setting and
  profile the paper update path further.

## Verification

The Service 256→512 measurement is pending in the next hosted constrained run.
Local full suite: 1,289 passed, one optional matplotlib report skipped. Ruff
and mypy pass. The one-sample receipt-bookkeeping A/B is diagnostic only.
