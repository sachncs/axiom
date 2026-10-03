# ADR 0002: Replace object-heavy adjacency with bounded native storage

Date: 2026-10-01. Status: implemented; full-service qualification pending.

## Context

`Adjacency` eagerly owns a Python set for each vertex. On the measured interpreter,
an empty set is 216 bytes plus an approximately 8-byte list slot: about 224 MB per
million vertices before edges or algorithm state. Multiple graph layers and
snapshot copies multiply that cost. This allocation model is not measured RSS.
Static CSR is compact but does not alone support efficient arbitrary edge edits.

## Decision

Keep `Adjacency` as an explicit reference/caller backend. `Matcher` now defaults
to bounded `Packed` storage:
native dense metadata, reusable four-neighbor blocks, low-degree row scans, and a
high-degree membership/location index. Reserve arena/index/journal growth before
changing either endpoint. Preserve sorted deterministic neighbor iteration and
canonical streaming edge iteration. Keep the backend through native phase copies,
hierarchy projections, and coloring subgraphs rather than quietly recreating
Python adjacency layers.

Expose retained-capacity accounting and a per-container allocation budget;
compaction builds and publishes a verified-by-tests budget-checked candidate.
Native growth accounts coexistence of old/new buffers. Read the precise
[contracts and exclusions](../storage.md): this is **not** a shared process quota,
and scratch, Python state, allocator overhead, copies, and reader versions add
memory. Budget failure must not partially edit graph contents or version.

## Consequences and alternatives

Python remains the API/reference/test layer; C++17 and CPython headers are needed
for source builds. Platform-specific wheels replace universal pure-Python wheels.
Clean-install checks must isolate the installed package from checkout imports;
otherwise local Python files hide the installed native extension. Native code
adds memory-safety/packaging risks, requiring differential tests, sanitizers, and
artifact smoke tests across supported Python versions.

CSR alone, more Python workers, and arbitrary connected-graph sharding were not
selected: none resolves mutable storage plus coherent matching on its own.
Current uint32 block handles cap the arena at 2^32−1 blocks. This is not a
general billion-vertex representation; denser workloads require widened/segmented
addressing, measured total RSS, and a separate qualification program.

## Evidence

Storage-layout update 2026-10-03: live four-neighbor blocks are now 24 bytes;
the former `used` word was redundant because each non-tail block is full and
tail occupancy follows the row degree. A fixed million-vertex degree-four
storage trace now retains 37,000,264 native bytes, versus 41,000,264 before this
change, with the independent exact audit passing. [ADR 0031](0031-derived-block-occupancy.md)
records the invariant, adversarial coverage, and qualification limits. Earlier
measurements below preserve their original 28-byte layout provenance.

Commits `bf055d9` and `574628f` implement the backend and measurements; `08eb153`
corrects installed-package test isolation. Three fresh-process million-vertex,
two-million-edge ring runs retained 41,000,360 native bytes and peaked at
83.4–83.8 MB process RSS. Exact final row audits passed after 40,000 journaled
edits per run. These are short **storage-only** measurements, not matcher/durable
service rates. Raw records are in `benchmarks/results/storage/`.
