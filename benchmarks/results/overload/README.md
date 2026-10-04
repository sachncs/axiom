# Paced offered-load and saturation stage

> Historical native-matcher results: the matching Engine used for these reports
> was removed from the product on 2026-10-04. Raw data is retained for provenance
> only and does not qualify current Basic or Multilevel matching.

Benchmark source `a3eef31`, native `b8c36e7`, service `c5dd095`, installed wheel
SHA-256 `1d6085644c20cd36b1eddb1fea1583276aa2e1309b853b4f9f7cf7869b8b47a1`.
Apple M3 Pro / 18 GiB / internal SSD/APFS, macOS 26.7.1, CPython 3.14.7,
SQLite 3.53.4. Sequential fresh isolated processes, archived runner, no competing
build/test jobs. Ten-second offering intervals, then drain and exact audits.

```bash
python -I runner/benchmarks/overload.py --database /private/local/path/fresh.db \
  --vertices 1000000 --rate 10000 --seconds 10 --query-rate 1000 --queue-capacity 512
```

Repeat n=32000 at 10000/30000/100000 offers/s, n=1000000 at 100000 offers/s.
The initial graph has two million ring edges at n=one million. Repeated hot-edge
delete/insert changes are all real; the final graph can have one fewer edge when
accepted count is odd. Queries are independently paced against the hot endpoint
and validate its exact committed-version partner, including during private batches.
FULL/fullfsync, native checkpoint interval 32768, bounded retry history and receipts
remain enabled. All count reconciliations, independent exact topology/proper-maximal
matching and live-to-recovered partner digests pass. Rejection never consumes an ID.

| Vertices | Scheduled offers | Producer-missed slots | Server Busy | Real acknowledged | Delivered/s incl. drain | Ack p99 upper |
| --- | --- | --- | --- | --- | --- | --- |
| 32000, 10k/s | 100000 | 2409 | 453 | 97138 | 9706 | 26.6 ms |
| 32000, 30k/s | 300000 | 45271 | 10757 | 243972 | 24384 | 118.9 ms |
| 32000, 100k/s | 1000000 | 302898 | 345621 | 351481 | 35118 | 145.6 ms |
| 1000000, 10k/s | 100000 | 2745 | 1573 | 95682 | **9561** | **84.8 ms** |
| 1000000, 100k/s | 1000000 | 297101 | 377961 | 324938 | 32468 | 227.6 ms |

The million 10k-offer run does **not** deliver 10k/s. Neither a configured arrival
rate nor gross saturation throughput is a passing production result. At 100k
offered/s, 4689 query offers also get Busy and 544 query slots are producer-missed;
4767 succeed with p99 <=1.0 ms. Global outstanding capacity remains bounded but
does not reserve availability for reads. Million process RSS peaks at 177.5–177.9
MB; these are observations, not enforced quotas.

The producer shares CPython/GIL/CPU with the service, and its missed slots expose
that limitation. Missed slots and Busy responses are distinct; no catch-up burst
or hidden input queue compensates. Successful acknowledgment timing includes
client observation and final drain; intended-arrival latency is recorded separately.
Queries rejected at admission have no successful latency sample—report their count,
not just p99 of successes. Results are single short hot-edge samples, not uniform
network traffic, hub-overload, a sustained arrival SLA, or hard resource/power-loss
qualification. [ADR 0015](../../../docs/adrs/0015-skew-and-offered-load-qualification.md).

## Reserved read-admission stage

`reserved-million-{10000,100000}.json`: native source `a77b0a5`, service and
frozen runner `3bd0b32`, installed wheel SHA-256
`d05ac53bbfc637e14966fcac75dc3e051a593fc9f76733c41bd5f0dad8489378`.
Same machine/storage/software as above except installed CPython **3.14.8**.
Fresh sequential isolated processes with no competing build/test jobs; same
ten-second command and 1000 query offers/s. Default reserve is one of 512 slots.

| Update offers/s | Missed update slots | Update Busy | Real acknowledged | Delivered/s incl. drain | Ack p99 upper | Query Busy / completed | Query p99 upper |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10000 | 3154 | 1701 | 95145 | **9508** | 91.6 ms | 0 / 9954 | 0.6 ms |
| 100000 | 306967 | 371955 | 321078 | 32062 | 238.0 ms | 0 / 9581 | 1.0 ms |

All count reconciliations and independent exact audits/recovery pass.
Query-producer missed slots remain 46/419. Peak outstanding remains 512 and
client receipts 511; peak RSS is 178.6/177.7 MB (observed, not enforced).
The reservation removes measured query admission rejections under update-only
saturation without bypassing the global cap. Other reads can still consume it.

The 10k-offer test **still fails to deliver 10k/s**; acknowledgment tails remain
checkpoint-sensitive and the shared-GIL producer is not an independent network
generator. Do not label either gross overload throughput or zero query Busy as
full qualification. [ADR 0017](../../../docs/adrs/0017-read-admission-reservation.md).

## Seeded million-vertex power-law workload

`power-law-million.json` records four ten-second runs of the new deterministic
power-law harness from the source checkout (CPython 3.14.8, macOS 26.7.1 ARM64,
SQLite 3.53.4; dirty tree at source commit 6afd6b4). Each run starts from a
one-million-vertex degree-four ring, bootstraps 2,048 chords across 16 weighted
hubs, sends 1,000 paced partner queries/s, and independently recovers/audits the
complete matching and exact final topology. Peak RSS was 220.5–220.8 MB; maximum
degree ranged 564–569.

| Offered updates/s | Repeats | Real updates/s incl. drain | Busy offers | Producer misses | Ack p99 upper | Query p99 upper |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 2 | 9,538–9,549 | 1,467–1,470 | 2,979–3,052 | 81.3–84.9 ms | 0.5–0.6 ms |
| 12,000 | 2 | 11,146–11,151 | 3,178–3,189 | 5,239–5,290 | 150.6–152.2 ms | 0.5–0.6 ms |

All four runs reconciled every scheduled offer, had zero Busy query offers, and
passed final exact recovery/certification. The same seed produced the same
matching digest, while update-trace/topology digests differed because scheduling
loss and Busy outcomes changed the accepted prefix. At 10,000 offered/s this
workload misses the real 10k/s target. At 12,000 offered/s it exceeded 11k real
changes/s in these short samples, with materially higher acknowledgment tails.
This is source-checkout paced evidence only—not an installed-wheel repeat, soak,
independent load generator, full historical-query replay, or deployment gate.
Do not generalize the short 12k sample into a sustained production guarantee.
See [ADR 0015](../../../docs/adrs/0015-skew-and-offered-load-qualification.md).

### Longer single-run probe

`power-law-million-60s.json` records one additional 60-second run at 12k
updates/s offered and 1k queries/s. It completed 681,039 real updates
(11,348/s), 59,451 partner queries, zero server Busy updates and zero Busy
queries. The same-process producer missed 38,961 update slots (5.4%) and 549
query slots. Ack p99 upper was 181.4 ms, queue-wait p99 166.6 ms, query p99
0.7 ms, peak RSS 198.2 MB, and exact recovery took 0.149 s. Exact audit and
recovery passed. This strengthens duration evidence but does not pass the
10k-offered profile, remove producer/GIL losses, or establish an installed-wheel
soak or production SLO.

## Inline checkpoint field-validation stage

`inline-million-10000.json`: installed production `e24ae58`, frozen runner
`a9f916d`, wheel SHA-256
`e09b81f4bdcffcdab1b3c1c9ae0baeefbc167d0f1e50903461d81234df1d525d`.
Same machine/software and isolated fresh-process protocol; unchanged ten-second
10k update/1k query offers, capacity 512, reserve one and FULL/fullfsync.
95717 real changes acknowledge at **9565/s** including drain; 2664 update slots
are producer-missed and 1619 offers receive Busy. Ack p99 <=87.2 ms, max 193.4 ms.
9957 queries complete with zero Busy, 43 missed query slots and p99 <=0.6 ms.
Independent exact audit/recovery passes. This single sample still fails the
10k delivered target; do not infer a causal throughput improvement from differences
in producer scheduling. [ADR 0018](../../../docs/adrs/0018-checkpoint-history-validation-cost.md).
