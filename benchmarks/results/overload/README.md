# Paced offered-load and saturation stage

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
