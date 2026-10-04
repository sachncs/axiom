# Queued concurrent-client stage

> Historical: these service runs used the former native matching Engine, which
> was removed from the product on 2026-10-04. Raw measurements and manifests are
> preserved for provenance only. They do not qualify current durable Basic or
> Multilevel matching, even where the SQLite/Service mechanisms overlap.

Short source `546464e`, service `1a6bafb`. Apple M3 Pro / 18 GiB / internal SSD/APFS;
software versions are recorded in raw JSON. Fresh sequential processes/databases;
no overlapping local build/test jobs during retained measurements.

```bash
python benchmarks/service.py --database /private/local/path/fresh.db \
  --vertices 1000000 --pairs 100000 --seed 599
```

Repeat seeds 600/601, plus n=32000/128000 with seed 599. Four update clients each
pipeline at most 64 individual requests; one query client pipelines 128 reads.
Server outstanding cap 512, persisted group cap 256, assembly deadline 1 ms,
checkpoint interval 32768, retry retention 16384. Native/image/database caps are
1 GiB / 64 MiB / 64 MiB; they do not hard-limit total RSS/WAL/disk.

Every run durably acknowledges 200000 real changes and completes 200064 partner
queries (199936 while writers are active), 1600 verified original retries and six
native checkpoint/retirement transactions. Final sequence 200000; checkpoint/floor
vary slightly with group boundaries. Largest group 256, peak outstanding 384.
Query/update RNG streams are separate, so these are not identical traces to the
earlier durable benchmark. Service scheduling does not change the update trace or
matching for a fixed seed/length; regression tests verify that property.

Headline timing includes client admission, queue/assembly wait, execution,
observed result delivery, concurrent queries/retries and native/SQLite maintenance.
Post-writer query drain is included. Fixed-size histograms retain exact maxima and
conservative 100us p99 bucket upper bounds; overflow at one second is reported
explicitly, not clipped. Completed client-held receipts, histograms, scratch and
public-query audit buffers count toward process peak RSS.

Outside headline timing, versioned live matching pages capture exact partners.
Recovery independently verifies exact expected topology, proper maximal matching,
and the same partner digest. Construction/live audit/open/recovery audit times are
separate. Every raw record passes these checks.

Limits: ~14-second million-vertex traces, closed-loop bounded windows, fixed
8192-pair pool, no open-loop offered-load/overload qualification, hub-degree mix,
hard RSS/disk caps, backup or device power-cut test. Query p99 remains 13.8–14.2 ms,
not the proposed 10 ms gate, and query/ack maxima approach 200 ms. Throughput is
above 10k on this richer staged workload; full production qualification remains
open. See [service contracts](../../../docs/service.md).

## Completed 30-minute queued-read soak

`soak-million-599.json`: frozen benchmark source `e50b59b`, installed service
`1a6bafb`, wheel SHA-256
`792e4167c8c72955c6692519a6a3f3945a8e733c5a48ecda1dde5851696b774e`.
Run on the same declared local machine, isolated installed wheel and archived
benchmark runner (no checkout `axiom` on the import path):

```bash
python -I runner/benchmarks/service.py --database /private/local/path/soak.db \
  --vertices 1000000 --pairs 100000000 --duration 1800 --timeout 1900 --seed 599
```

The requested duration completed: 1800.010 seconds, 24,501,440 real acknowledged
changes, **13,611.8 changes/s**, 24,501,376 partner queries, 191,424 verified retry
outcomes, and 747 native checkpoints. Ack p99 upper bound 28.1 ms (max 215.1 ms);
query p99 14.4 ms (max 207.5 ms). Native retained capacity 73,006,480 bytes,
peak process RSS 204,537,856 bytes, sampled DB/WAL/SHM peak 55,173,120 bytes.
Independent exact topology/proper-maximal matching and live/recovered partner
digest checks pass. Recovery/open 0.131 seconds; separate independent audit 3.207
seconds. All accepted receipts finish, none remain outstanding.

This establishes sustained throughput only for this closed-loop fixed-pool
queued-read workload. It does not pass the proposed query-latency gate, prove hard
resource ceilings, or qualify overload/skew/backup/device power loss. It predates
the additional 4-byte/vertex committed-read index and must not be reported as a
measurement of that new implementation. Current source `ec9926e` instead declares
exactly one committed partner read per admitted update; old raw data is unchanged.

## Committed-partner read stage

`committed-million-{599,600,601}.json`: native/service source `b8c36e7`, frozen
benchmark source `ec9926e`, isolated installed wheel SHA-256
`6611538f6598e9a661fdc3d7e0d484aa6a89f8a2d8ccbfe52cf70e84ecff9060`.
Same declared machine/software/storage stack. Sequential fresh processes with no
overlapping build/test jobs; archived benchmark runner, not checkout imports:

```bash
python -I runner/benchmarks/service.py --database /private/local/path/fresh.db \
  --vertices 1000000 --pairs 100000 --seed 599
```

Repeat seeds 600/601. Four writers/window 64, query window 128, exactly 200000
committed partner reads for 200000 real acknowledged updates; FULL/fullfsync,
native checkpoint interval 32768, capacity 512, default remaining policies.

| Seed | Real acknowledged changes/s | Ack p99 upper | Query p99 upper | Query max | Peak RSS |
| --- | --- | --- | --- | --- | --- |
| 599 | 15236 | 27.0 ms | 0.5 ms | 0.626 ms | 214.9 MB |
| 600 | 15389 | 25.9 ms | 0.5 ms | 0.614 ms | 214.8 MB |
| 601 | 15306 | 26.0 ms | 0.5 ms | 0.715 ms | 214.3 MB |

All independent exact topology/proper-maximal matching audits, exact recovery and
live/recovered partner digests pass. Update trace and final matching hashes agree
with the corresponding earlier queued-read records. Native retained allocation is
approximately 77.01 MB: the extra first-write index costs 4,000,024 bytes. Ack
maxima remain 200.3–207.9 ms; checkpoints still delay writes.

These 13-second runs improve the measured query-latency stage, not worst-case
latency qualification. Query credit timing/scheduling differs from the earlier
benchmark even though update traces agree. Credits are issued on update admission;
reads may observe a preceding committed prefix. They do not model independently
offered query arrivals during every maintenance interval, overload or hubs.
The new implementation has not yet repeated the 30-minute soak. Hard total
RSS/WAL/disk, backup and device power-loss gates remain open.

## Forced hub-repair stage

### Moderate-row candidate requalification

[Candidate hub record](rowpolicy-hub-million.json), source `6d5f3cd`, wheel
SHA-256 `19736864c92330d21fbe1af76496d145e1d137c991ebfebdfe1b074a0e1fad48`,
repeats the million-vertex degree-65,536 hub with 100,000 pairs on the same
declared development host in a fresh isolated process, after other benchmarks
finish. 200,000 real durable updates and 200,000 coherent queries complete at
16,622.1 updates/s with eight checkpoints including bootstrap. Exact topology,
proper-maximal matching, recovery and 1,600 retry outcomes pass; trace/matching
hashes agree with the previous long hub record. Native allocation is 79,233,888
bytes; peak RSS 283,328,512 bytes. Ack/query p99 upper bounds are 24.5/0.4 ms;
maximum ack is 190.9 ms. This preserves the short closed-loop indexed-hub stage,
not a sustained open-loop hub SLA or proof that every skew distribution qualifies.

### Historical baseline

Benchmark source `84c9fe3`, installed native `b8c36e7` / service `c5dd095`, wheel
SHA-256 `1d6085644c20cd36b1eddb1fea1583276aa2e1309b853b4f9f7cf7869b8b47a1`.
Same declared Mac/software/filesystem; fresh sequential isolated installed-package
runs, archived runner, no competing test/build jobs:

```bash
python -I runner/benchmarks/service.py --database /private/local/path/hub.db \
  --vertices 1000000 --pairs 10000 --hub-degree 65536
```

Repeat 32000/degree4096 and 128000/degree8192. Bootstrap adds D-4 known hub edges
separately; timed churn alternates the hub's matched ring edge and an alternate
chord. Each run completes 20000 real durable updates and 20000 partner reads;
exact full ring-plus-hub/proper-maximal/live-to-recovered partner audits pass.

| Vertices | Hub degree | Real changes/s | Ack p99 upper | Query p99 upper | Peak RSS |
| --- | --- | --- | --- | --- | --- |
| 32000 | 4096 | 18966 | 22.8 ms | 0.3 ms | 42.0 MB |
| 128000 | 8192 | 17236 | 24.9 ms | 0.3 ms | 51.5 MB |
| 1000000 | 65536 | **9048** | 197.0 ms | 0.3 ms | 283.1 MB |

The million graph has 2065532 edges, average degree 4.131064. Its 2.21-second trace
includes a timed native checkpoint; smaller stages last 1.05–1.16 seconds with
different checkpoint positions. These are single short samples, not an isolated
causal comparison or a hub SLA. The million result is below 10k; earlier uniform
success cannot qualify this workload. Degree-sensitive free-neighbor search and
maintenance remain engineering work. [ADR 0015](../../../docs/adrs/0015-skew-and-offered-load-qualification.md).

## Budgeted free-vertex index and read reservation stage

`free-hub-{32k,128k,million}.json` and `free-hub-million-long.json`:
native source `a77b0a5`, service/frozen benchmark source `3bd0b32`, installed wheel
SHA-256 `d05ac53bbfc637e14966fcac75dc3e051a593fc9f76733c41bd5f0dad8489378`.
Same M3 Pro / 18 GiB / internal SSD/APFS, macOS 26.7.1, SQLite 3.53.4;
this wheel environment reports CPython **3.14.8**. Sequential fresh isolated
installed-package processes with an archived runner and no competing test/build
jobs. Repeat the forced-hub command above; the long million run uses
`--pairs 100000`. FULL/fullfsync, checkpoints and 1:1 partner reads remain enabled.
Default read reservation is one of 512 slots.

| Vertices / pairs | Hub degree | Real durable changes/s | Ack p99 upper | Query p99 upper | Peak RSS |
| --- | --- | --- | --- | --- | --- |
| 32000 / 10000 | 4096 | 18667 | 21.6 ms | 0.5 ms | 41.8 MB |
| 128000 / 10000 | 8192 | 17897 | 22.7 ms | 0.5 ms | 51.4 MB |
| 1000000 / 10000 | 65536 | 15322 | 205.3 ms | 0.5 ms | 283.1 MB |
| 1000000 / 100000 | 65536 | 16108 | 24.9 ms | 0.5 ms | 283.3 MB |

All independent exact topology/proper-maximal matching and exact recovery audits
pass. The three short runs have identical update trace and matching digests to
their respective previous failing-stage records. The million native index adds
exactly 127160 retained bytes; final native allocation is 79233888 bytes.
The short million trace includes one timed checkpoint, while the long trace
reaches eight total checkpoints including bootstrap, completing
200000 updates and 200000 queries in 12.416 seconds. Max acknowledgment is still
207.0 ms in that longer run: p99 improvement does not remove checkpoint stalls.

This is evidence of the delivered sparse-free search stage, not a controlled
CPU-only causal comparison, sustained production arrival SLA or worst-case hub
bound. Many free vertices can still require substantial search. The changed
implementation has not repeated the old 30-minute soak. Paced offered-load still
fails 10k delivered/s; hard RSS/disk and physical power-loss qualification remain
open. [ADR 0016](../../../docs/adrs/0016-sparse-free-vertex-search.md) and
[ADR 0017](../../../docs/adrs/0017-read-admission-reservation.md).
