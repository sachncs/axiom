# Separate-process offered-load stage

Installed production source `e24ae58`; wheel SHA-256
`e09b81f4bdcffcdab1b3c1c9ae0baeefbc167d0f1e50903461d81234df1d525d`.
Apple M3 Pro / 18 GiB / internal SSD/APFS, macOS 26.7.1, CPython 3.14.8,
SQLite 3.53.4. Sequential fresh isolated installed-wheel processes and archived
runners; no overlapping test/build/performance jobs.
Single-offer runner `ba39b2b`; batch-16 runner `d28d5dd`.

```bash
python -I runner/benchmarks/independent_load.py \
  --database /private/local/path/fresh.db --vertices 1000000 \
  --rate 11000 --query-rate 10000 --seconds 30 \
  --queue-capacity 4096 --ipc-bytes 65536 --ipc-batch 16
```

For the first two records use rate 10000/query-rate 1000/seconds 10/batch 1
and capacities 512/4096. The third uses the command above but batch 1.
Each starts with two million ring edges and performs hot-edge churn; odd admitted
counts leave one edge absent. Every admitted change is real. FULL/fullfsync,
checkpoint interval 32768, retention 16384 and group limit 256 remain enabled.

| Capacity / IPC batch / update-query offers/s | Delivered/s incl. drain | Real acknowledged | Producer misses | IPC drops | Server Busy | Query p99 upper | Ack p99 upper |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 512 / 1 / 10000-1000 | 9603 | 96212 | 70 | 395 | 3323 | 35.2 ms | 154.0 ms |
| 4096 / 1 / 10000-1000 | 9827 | 99714 | 100 | 186 | 0 | 32.5 ms | 203.0 ms |
| 4096 / 1 / 11000-10000 | 10679 | 320569 | 165 | 9266 | 0 | 59.8 ms | 196.1 ms |
| 4096 / 16 / 11000-10000 | **10930** | 329184 | 784 | 32 | 0 | 2.2 ms | 184.8 ms |

All rows pass independent exact topology/proper-maximal matching/recovery and
matching-digest checks. Loss columns count update offers only; raw records also
retain query misses/drops/Busy. The batch-16 run completes 299261 queries,
659 query slots are missed and 80 queries drop at IPC, with no query Busy.
Every original due timestamp survives batching; offered latency includes producer
aggregation, kernel queueing and consumer scheduling, not just lookup compute.
The 30.118-second headline includes final acknowledgment drain.
Owner/producer peak RSS is 182894592/28999680 bytes; ten checkpoints complete.

One-offer transport stalls can magnify query tails and kernel packet overhead.
Batching changes workload delivery, so these are staged samples, not an isolated
native algorithm speedup. No catch-up burst, acknowledgment wait or hidden
unbounded producer queue compensates for misses. Transport buffer sizes and
server capacity are explicit; larger admission trades memory/latency for stall
absorption. There is no production RPC, authentication or external retry protocol.
The first `413680a` runner failed with macOS peer-close reset and yielded no usable
qualification record; `ba39b2b` added drain confirmation/ENOBUFS accounting before
all retained measurements.

User acceptance defers stricter latency engineering for this version. Current
throughput evidence is not hard memory/disk, new-code long-soak or physical
power-loss qualification. [ADR 0019](../../../docs/adrs/0019-independent-arrivals-and-bounded-ipc.md).
