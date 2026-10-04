# ADR 0141: Qualify larger atomic groups in the constrained resource trace

- Status: rejected; reverted to 256
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

Keep both production and resource qualification groups at 256. The 512-request
resource-only experiment completed one million updates in 224.454 seconds
(about 4,455/s), compared with the prior 256-request sample at 140.538 seconds
(about 7,115/s). The runs are not a controlled same-runner A/B, but the larger
group was materially slower and therefore rejected. Durable's production
defaults remain unchanged.

## Consequences

- On this workload, groups of 512 did not reduce end-to-end update cost; Service
  reported 3,252 groups and a largest group of 512.
- The larger batch also did not complete memory/recovery qualification, so it
  cannot be treated as a reliability or latency improvement.
- The 10k/s target remains unmet. Profile the paper update path rather than
  continuing to enlarge caller groups without causal evidence.

## Verification

The hosted 512-group run reported 4,455/s and was reverted. The prior 256-group
run reported 7,115/s. Both failed later in different memory-pressure code; the
new atomic OOM rollback probe still requires hosted qualification. Local full
suite before the latest resource-only pressure changes: 1,289 passed, one
optional matplotlib report skipped. Ruff and mypy passed.
