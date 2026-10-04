# ADR 0138: Bound resource growth cycles by durable history

- Status: implemented; hosted rerun pending
- Date: 2026-10-04

## Context

The constrained resource worker's million-vertex growth/drain sequence was
configured as 1,040,000 updates: one million operations to insert and remove
the antipodal matching edges, then 40,000 balanced churn operations. Durable
stores default to and currently cap `max_operations` at 1,000,000. The worker
therefore failed admission partway through its last submitted group, after the
last progress line at 900,096 completed updates. This was an invalid benchmark
configuration, not an algorithm, journal, or storage failure.

## Decision

Keep the durable operation-history limit unchanged. The full growth/drain cycle
alone is a useful exactly-one-million-operation qualification, so `Cycle`
accepts a zero-length tail. The CLI caps its optional tail at the supported
history limit; smaller supported graphs still run the 40,000-operation tail.
No accepted update is dropped or acknowledged without durable commit.

## Consequences

- The one-million-vertex worker now tests the entire insert/delete growth cycle
  without requesting operations the configured store must reject.
- The disk-full update-commit probe uses a separate two-operation recovery trace,
  so it tests SQLite exhaustion without needing operation-history space after
  the million-operation cycle has consumed the main store's complete allowance.
- Recovery retry verification replays the actual final request in the selected
  workload; for a growth cycle, that is its final antipodal-chord deletion, not
  an unrelated insert.
- It no longer includes the extra 40,000-update post-cycle tail at that stage;
  adversarial and repeatability workloads remain separate qualifications.
- This corrects the qualification workload only. It does not raise the
  documented operation-retention limit or claim 10k updates/s.

## Verification

Unit coverage accepts the exact million-vertex cycle, checks first/last cycle
operations, and retains rejection of malformed references. A hosted constrained
resource rerun is required to measure final rate, recovery, backup, and pressure
stages.
