# Profiled checkpoint diagnostic

These results identify maintenance costs, **not** unprofiled update throughput
or an acknowledgment-latency qualification. Apple M3 Pro / 18 GiB / internal
SSD/APFS, macOS 26.7.1, CPython 3.14.8, SQLite 3.53.4. Fresh sequential isolated
installed-wheel processes, archived runner `a9f916d`, no competing build/test jobs.

Baseline `diagnostic-million-32768.json`: production source `3bd0b32`, wheel
SHA-256 `d05ac53bbfc637e14966fcac75dc3e051a593fc9f76733c41bd5f0dad8489378`.
Candidate `inline-diagnostic-million-32768.json`: production source `e24ae58`,
wheel SHA-256
`e09b81f4bdcffcdab1b3c1c9ae0baeefbc167d0f1e50903461d81234df1d525d`.

```bash
python -I runner/benchmarks/checkpoint_diagnose.py \
  --database /private/local/path/fresh.db --vertices 1000000 --updates 32768
```

The diagnostic constructs two million ring edges, performs 32768 real hot-edge
updates in groups of 256, then profiles a single explicit checkpoint. Interval
48896 prevents automatic checkpoints during setup; retention 16384 and operation
cap 65536 satisfy the persisted policy. This differs from the service interval
32768 and is not a service workload. FULL/fullfsync remain enabled. Exact topology,
proper-maximal matching, partner digest, version and retained policy recovery
are independently verified after profiling; retained native capacity can compact
during restore without changing logical state.

| Profiled component | Before | Inline field validation |
| --- | --- | --- |
| Whole checkpoint | 191.3 ms | 181.2 ms |
| Record construction (inclusive) | 123.9 ms | 112.9 ms |
| Native snapshot (included above) | 23.2 ms | 22.1 ms |
| Persist checkpoint | 67.3 ms | 68.2 ms |
| Strict field helper calls | 196608 | 0 (predicates still run inline) |

Do not sum nested cumulative timings or extrapolate these profiled samples to
unprofiled p99. Removing helper dispatch leaves history/digest/image work and
durable SQLite I/O substantial. Candidate paced-load evidence still falls below
10k delivered/s. [ADR 0018](../../../docs/adrs/0018-checkpoint-history-validation-cost.md).
