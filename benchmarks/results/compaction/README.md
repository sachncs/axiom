# Durable checkpoint/retirement stage, not production qualification

Source: `525cbca` (durable implementation `f9b5d9b`). Apple M3 Pro, 18 GiB RAM,
internal SSD/APFS; software versions are in each raw JSON. Fresh sequential Python
processes, fresh private local database paths, default native/image/database caps,
256-operation supplied groups, interval 32768, retry retention 16384. No unrelated
build/test jobs ran during the retained measurements.

```bash
python benchmarks/durable.py --database /private/local/path/fresh.db \
  --vertices 1000000 --pairs 100000 --batch 256 \
  --checkpoint-interval 32768 --seed 599
```

Repeat with seeds 600/601, and n=32000/128000 with seed 599. Output is the raw JSON
here. Each trace acknowledges 200,000 real changes and executes 100,000 coherent
partner queries plus 6,400 verified retry outcomes. Every trace includes six
native FULL-WAL checkpoint/retirement publications and SQLite WAL maintenance.
Final checkpoint sequence is 196608, expired floor 180224, retained rows 19776;
this passes the legacy 65536 lifetime limit without lifting the retained-table cap.

Whole-trace timing includes request construction, publication, matching queries,
retries, maintenance and sampled disk usage. Exact independent topology/proper
maximal matching audit, open/recovery and exact post-recovery matching digest are
reported separately, not included in the update rate. Original latest-group retry
outcomes and expired-sequence refusal are checked after recovery.

Limitations: approximately seven-second million-vertex traces, fixed 8192-pair
pool across the universe, and synchronous queries **after** each acknowledged
group. There are no concurrent arrivals or queue waits, skewed-degree workload,
long soak, hard RSS/WAL/disk limits, power-cut test or backup qualification here.
Ack p99 can miss checkpoint-bearing groups (six of 782 groups); maximum latency
must be inspected. Query microsecond samples are not concurrent-client SLAs.
RSS includes benchmark latency lists, Python/audit scratch and recovery work,
not only native containers. Physical disk samples are not a hard high-water bound.

These results show maintenance-inclusive throughput headroom on this machine;
they do not finish the accepted full-service 10k qualification goal.
