# ADR 0018: Reduce checkpoint validation dispatch, not its guarantees

Date: 2026-10-02. Status: implemented and failure-tested; diagnostic and one
paced-load sample recorded; production qualification remains open.

## Evidence and decision

A profiled installed-package million-vertex checkpoint validates 32768 retained
rows. Record construction takes 123.9 ms, including native audited snapshot
encoding at 23.2 ms; SQLite persistence takes 67.3 ms. Six strict field helpers
per row contribute 196608 Python calls (17.3 ms under profiling).
This is not solely native graph compute or solely storage I/O.

Inline the six strict type/range/sequence/version predicates within the existing
streamed history loop. Preserve checksum chaining, tail/control agreement,
independent native snapshot audit, atomic history retirement, FULL/fullfsync and
fail-stop before publication. Keep bounded streaming row consumption; do not
materialize history, add a second durable store, or skip validation based on an
in-memory assertion that previously written SQL must still be correct.
Checkpoint/durable formats and exact matching choices are unchanged.

Malformed live history tests cover sequence gaps, negative/out-of-range/real/text
fields and invalid digests. They require rejection before any generation/image
publication, unchanged native version and an unavailable owner. Existing crash,
corruption, retry-retirement and independent recovery tests remain.
The full suite passes 732 tests; isolated installed-wheel durable smoke passes.

## Limits and measurements

The candidate profiled sample takes 181.2 ms versus 191.3 ms before; record
construction takes 112.9 ms. Profiling overhead and storage variability prevent
treating this as an unprofiled causal speedup or latency SLA.
One unprofiled million-vertex 10k-offer sample delivers only 9565/s, with ack
p99 <=87.2 ms and zero query Busy. The target is still not qualified.
Changing durability settings or deleting history certificates is not the solution.

Next work must distinguish independent arrival generation, bounded admission
through checkpoint stalls and genuinely shorter maintenance. Concurrent/background
checkpointing would require a bounded consistent snapshot/publication design,
not sharing mutable native state or a SQLite connection across arbitrary threads.
[Raw diagnostic/provenance](../../benchmarks/results/checkpoint/README.md) and
[offered-load evidence](../../benchmarks/results/overload/README.md).
