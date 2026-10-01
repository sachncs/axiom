# Queued concurrent-client stage

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
