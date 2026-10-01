# ADR 0017: Reserve bounded admission capacity for reads

Date: 2026-10-02. Status: implemented/tested; saturation measurement pending.

## Context and decision

The offered-load stage rejects thousands of cheap partner queries because update
receipts occupy all global capacity. Faster native lookup does not fix admission
starvation. Bypassing the global cap would weaken the resource contract.

`Service(query_reserve=None)` defaults to one reserved slot, except a single-slot
service defaults to zero. Explicit values range from zero through
`queue_capacity - 1`. All `submit` calls, including pending duplicates and retained
retries, stop at total outstanding `queue_capacity - query_reserve`. Read admission
still obeys the original global cap. Count active/queued/completed work exactly as
before; no hidden queue, update ID consumption or graph mutation occurs on Busy.
Metrics expose the reserve and update admission limit.

This protects reads when **only updates** saturate admission. Other queued reads
and administrative jobs can still fill the global cap; no unconditional query
availability, fairness, timeout or latency SLA is promised. Maintenance retains
its separate class limit. One direct partner call uses its reserved slot only
through synchronous completion; caller threads still need external bounds.

The default changes effective update capacity by one; callers that deliberately
need the previous all-update capacity can select `query_reserve=0`. Match client
windows/bootstrap groups to `update_admission_limit`, not just the global cap.
Retry-retention requirements still use the full queue capacity. Operational
reservation is not a persisted graph/backend format change.

## Verification

Paused durability tests fill update admission, reject fresh/duplicate submissions
without consuming IDs, and repeatedly read the previous publication. A queued
status can consume the last global slot, after which further reads correctly get
Busy. Releasing persistence drains exact outcomes and reuses capacity. Test
single-slot defaults, explicit zero legacy behavior and invalid policies. Forced
offered saturation verifies bounded receipts and no Busy partner calls when
updates are the only outstanding work. Broad qualification remains open.
