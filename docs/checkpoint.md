# Exact native checkpoint primitives

The codec preserves graph, partners, counts and logical version without rerunning
matching selection. The codec and opt-in durable v2 checkpoint/history publication
are implemented; **maintenance-inclusive production qualification is pending**.
See [durable contracts](durable.md) and
[ADR 0010](adrs/0010-native-checkpoint-and-history-compaction.md).

```python
from axiom.engine import Engine

engine = Engine(128)
engine.ring(2)
engine.delete(0, 1)
image = engine.snapshot(max_bytes=64 * 1024 * 1024)
restored = Engine.restore(image, budget=64 * 1024 * 1024)
assert restored.check()
assert restored.version == engine.version
assert restored.partner(0) == engine.partner(0)
```

Export performs a full audit and rejects active unpublished batches. Restore
validates immutable input and returns a new audited candidate; it never changes
the original. `MemoryError` covers image/native capacity rejection. Invalid format
or graph/matching input raises `ValueError`. Source certificate failure poisons
the source; it must not continue serving that state.

The portable little-endian image contains no C++ ABI layout/pointers or live
journals. Row/partner checks do not constitute an image checksum: a byte change
may produce another valid state. The durable layer must independently verify and
bind the image checksum to its sequence/version/control/retirement records.
Returning snapshot bytes or writing them to an unsynchronized file is not a
durable acknowledgment or backup protocol.

Default byte caps are 64 MiB; each new engine has its own native budget. Python
bytes, full-audit scratch and keeping original/candidate alive simultaneously
are additional memory. The restore candidate can reclaim retained native capacity,
but the current durable owner does not automatically replace its engine this way.

## Measure the primitive

```bash
python benchmarks/checkpoint.py --vertices 32000
python benchmarks/checkpoint.py --vertices 128000
python benchmarks/checkpoint.py --vertices 1000000
```

After 2048 real delete/insert pairs, the benchmark independently checks exact
topology, partners, degrees, counts/version, proper maximality, and repeated image
equality. Encode/restore timing includes native full audits; the final independent
public-query audit is reported separately. These are in-memory primitive timings,
not durable checkpoint/compaction/soak results.

Measured on Apple M3 Pro / 18 GiB / macOS 26.7.1 / CPython 3.14.7. Audits originally
allocated per-row hash sets (`e13ea09`); reusable compact row scratch (`f629943`)
retains the same full checks. Sequential fresh-process measurements:

| Vertices | Image bytes | Encode before → after | Restore before → after |
| --- | --- | --- | --- |
| 32,000 | 768,040 | 5.53 → 0.87 ms | 5.80 → 1.04 ms |
| 128,000 | 3,072,040 | 22.51 → 2.70 ms | 24.02 → 3.68 ms |
| 1,000,000 | 24,000,040 | 163.40 → 20.17–21.08 ms | 176.71 → 28.04–28.22 ms |

There is one before sample at each scale, one after at 32k/128k, and three fresh
after repetitions of seed 599 at one million. Image/matching hashes are identical
before/after and across repetitions, and every independent audit passes. This is
limited primitive evidence, not a hardware-independent speedup or p99 SLA.

Million-vertex native allocated capacity is 73,000,528 bytes in the live source
and 45,114,324 in the restored candidate. Process peak RSS is 171.7–171.9 MB with
both engines, image/repeated image and audits included. Source/candidate capacity
is not total RSS; the durable owner is not yet using this to compact its live engine.

Raw [before](../benchmarks/results/checkpoint/before-million-599.json),
[after 1](../benchmarks/results/checkpoint/after-million-599-1.json),
[2](../benchmarks/results/checkpoint/after-million-599-2.json),
[3](../benchmarks/results/checkpoint/after-million-599-3.json); smaller-scale records
are in the same directory. Local full suite: 541 passes, 84.28% Python coverage
(not C++ coverage). ASan/UBSan passes 100k matching edits with checkpoint corruption
tests and 200k storage edits after the audit change. Isolated wheel/source installs
exercise the native codec.
