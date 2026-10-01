# ADR 0016: Search sparse free vertices instead of every hub neighbor

Date: 2026-10-02. Status: implemented and differential/regression tested;
installed-package performance qualification pending.

## Context and decision

The degree-65536 hub stage falls below 10k/s. The native repair helper scans its
entire row even when nearly every vertex is matched. A Python/C++ set per free
vertex would add object/node allocations and make allocation-free undo harder.
Copying the graph is not a solution. Neither is disabling matching certificates.

Add a fixed-universe hierarchy of uint64 free-vertex bitmaps: leaves encode
`partner == NONE`, upper levels encode nonempty child words. At most six levels
cover uint32 addressing. When free count is less than one eighth of row degree,
iterate free vertices in increasing order and test adjacency; otherwise keep the
original row scan. Both return the minimum free neighbor, preserving exact
deterministic matching choices. This is an engineering search optimization, not
a different matching algorithm or a transferred paper theorem.

The index costs approximately 127 KB at one million vertices, plus fixed native
metadata. Include every level's retained capacity in the shared native budget,
initial admission and old/new graph candidate accounting. Partner writes update
bits/count/summaries without allocation. Reverse partner undo updates the same
derived state; no additional whole-state journal/copy is needed. Ring publication
and checkpoint restore rebuild it from exact partners in linear time. The index
is ephemeral: checkpoint format, matching values and durable protocol do not change.

## Certificates, threading and verification

Local certificates compare touched leaf/summary paths with partners and global
free count with `n - 2*matching_size`. Candidate iteration checks bounds and
partner agreement; encountered malformed summaries fail the edit, roll back and
poison the engine. The independent full audit reconstructs every expected leaf,
summary, shape and count from partners and still scans graph rows independently
for maximality. It does not certify maximality by replaying the optimized search.
Opaque native ownership remains the invariant boundary; this is not a promise
to detect every unrelated memory bit flip on every local edit.

The CPython binding retains the GIL; concurrent committed-partner readers use
the existing undo view, not this private search index. Free-threaded builds and
arbitrary concurrent C++ mutation remain unsupported (ADR 0012).

Tests cover bitmap/summary boundaries, deeper addressing, native budget rejection,
ordered enumeration, minimum neighbor selection independent of insertion order,
repeated private hub repairs, exact logical rollback, failed-edit recovery and
checkpoint rebuilding. Native differential stress retains 100000 mixed edits,
9.6 million published-view reads, independent audits and allocation-free rollback
under ASan/UBSan. Corrupt summaries must reject rather than access invalid memory.

## Limits

Worst-case repair is still workload-dependent: many free vertices or low-density
hub neighborhoods can require substantial search. The extra bitmap audit/rebuild
work must be included in checkpoint/recovery timings. No billion-scale, overload,
latency or hard process-memory claim follows from its compact size or unit tests.
Retain before/after raw installed-package measurements and exact trace/matching
digests; do not hide the previous failing skew result.
