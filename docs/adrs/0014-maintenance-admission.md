# ADR 0014: Bound expensive work independently of ordinary receipts

Date: 2026-10-02. Status: implemented/tested; overload/resource qualification pending.

## Context and decision

A bounded queue of 16384 receipts still allows thousands of full audits,
checkpoints or backups. Counting every request equally is not an execution-work
bound and can make ordinary updates wait behind excessive maintenance.

Add `Service(maintenance_capacity=1)`, configurable from 1 through
`min(64, queue_capacity)`. Explicit `check`, `checkpoint` and `backup` share this
class limit **as well as** the global outstanding limit. Count active and queued
maintenance until its receipt completes, not just until dequeue. A full class
rejects synchronously with `BusyError`, creates no job/destination and consumes
no update ID. Ordinary updates, partner reads and status retain their existing
capacity/scheduling rules. Metrics expose the class capacity/outstanding count.

Completion/failure releases the class slot exactly once. Automatic checkpoints
inside a bounded update group are not separately queued maintenance jobs and still
execute when required for durability/history bounds. This is backpressure, not
cancellation, preemption or a latency SLA; one accepted job can still block the
owner for its execution duration. Untrusted callers also need authentication,
rate/work budgets and restricted administrative APIs, outside this local layer.

## Verification and limits

A paused active backup rejects repeated backup/checkpoint/audit attempts while
ordinary updates remain admissible and committed partner reads remain available.
No rejected target or acceptance counter/sequence changes occur. Successful and
failed jobs release capacity; invalid constructor limits reject before ownership.
Existing full-audit fail-stop and draining-close tests retain their guarantees.

This does not enforce total RSS, native scratch, WAL, disk, degree or per-update
work. Those remain separate hard-resource/workload qualification gates. Do not
report queue/maintenance bounds as a process/container memory quota.
