<p align="center">
  <img src="site/public/logo.svg" alt="axiom logo" width="160" />
  <h1 align="center">axiom</h1>
  <p align="center">Deterministic fully dynamic maximal matching in pure Python.</p>
  <p align="center">
    <a href="#installation"><img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue" alt="Python"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
    <a href="https://github.com/sachncs/axiom/actions"><img src="https://img.shields.io/github/actions/workflow/status/sachncs/axiom/ci.yml?branch=master" alt="CI"></a>
    <a href="https://github.com/sachncs/axiom"><img src="https://img.shields.io/badge/arXiv-2605.00797v1-b31b1b" alt="arXiv"></a>
    <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/mypy-strict-green.svg" alt="Checked with mypy"></a>
    <a href="https://github.com/sachncs/axiom/stargazers"><img src="https://img.shields.io/github/stars/sachncs/axiom" alt="Stars"></a>
  </p>
</p>

**axiom** is a pure-Python implementation of deterministic fully dynamic maximal matching based on *A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching* by Chuzhoy, Khanna, and Song (STOC 2026, [arXiv:2605.00797v1](https://arxiv.org/abs/2605.00797v1)). It maintains a **maximal matching** in an undirected graph under online edge insertions and deletions.

---

## Features

- **Two operating modes**
  - `basic` &mdash; the single-level z-subgraph implementation
  - `multilevel` &mdash; the recursive *k*-level z-subgraph implementation
- **Two canonical modes** &mdash; select `basic` or `multilevel` with the `mode=` string.
- **z-subgraph system** &mdash; the (*A*, *B*, *U*) partition, *S* = *A* &cup; *B* saturation, &Lambda;(*u*) and *L*(*a*) index lists, and their implemented validators.
- **Multi-level hierarchy** &mdash; the recursive hierarchy and I3 repair path are implemented and checked, without claiming the paper's complete dynamic theorem.
- **Deterministic edge colouring** &mdash; `basic` uses fan-based Vizing colouring; `multilevel` uses deterministic paper fan operations, Vizing activation, and checked u-edge reduction, with no silent fallback. The complete ABB+26 near-linear bound is not claimed.
- **Comprehensive invariant checks** &mdash; `Matcher.maximal()`, `System.check()`, and `Hierarchy.check()` expose the canonical state validators.
- **Empirical ledger** &mdash; explicit counters for phase/subphase rebuilds, rematch scan sizes, and stale cleanups. Useful for diagnosing where time is spent; **not** a proof of the amortised bound.
- **Reproducible simulation** &mdash; seeded random update sequences with replay utilities for stress tests and benchmarks.
- **Zero runtime dependencies** &mdash; pure Python with the standard library; only the optional `.[dev]` extras (`pytest`, `mypy`, `ruff`, `hypothesis`) are pulled in for development.
- **Strict type checking** &mdash; every public signature is annotated; the repository enables `mypy --strict`.

---

## Installation

### From source

```bash
git clone https://github.com/sachncs/axiom.git
cd axiom
pip install -e .
```

### With dev dependencies

```bash
pip install -e ".[dev]"
```

This pulls in `pytest`, `pytest-cov`, `mypy`, `ruff`, and `hypothesis`.

## Runtime model

Axiom supports CPython 3.10, 3.11, 3.12, and 3.13. Matcher instances are
stateful and are not thread-safe; protect an instance with an external lock if
multiple threads can access it. Independent matcher instances may be used
concurrently.

The live graph and its matching/index state use `O(n + m)` storage in the
single-level implementation. `multilevel` retains the recursive hierarchy and
phase snapshots; its auxiliary storage is `O(k(n + m))` in the worst case,
where `k` is the number of active levels (`O(log n)` in the dense schedule).
Returned matching and partner collections are copies and may be mutated by the
caller without changing matcher state.

The implementation reports empirical operation counters through `stats()`.
The theoretical amortized bounds from the paper assume its balanced-tree and
deterministic edge-coloring model; this repository does not claim those bounds
for Python hash-set adjacency or until the documented ABB+26 implementation
gates are complete.

---

## Quickstart

### Python API

```python
from axiom import Matcher

# Initialise on 100 vertices in basic mode
algo = Matcher(n=100, mode="basic")

# Insert edges
algo.insert(0, 1)
algo.insert(2, 3)

# Delete edges
algo.delete(0, 1)

# Query the maintained maximal matching
assert algo.maximal()
assert algo.size() == 1  # the (2, 3) edge remains
print(algo.matching())  # {(2, 3)}
print(algo.partners())  # {2: 3, 3: 2}
print(algo.stats())  # amortised bookkeeping
```

### Command-line interface

```bash
axiom --n 20 --mode basic --updates 200 --seed 42
```

Output:

```
=== Axiom Demo: n=20, mode=basic, updates=200 ===
Completed 200 updates in 0.001s
Final edges: 12
Matching size: 8
Maximal: True
```

### Replay a prepared sequence

```python
from axiom import Matcher
from axiom.simulation import random_updates, replay

algo = Matcher(50, mode="multilevel")
rng = __import__("random").Random(7)
seq = random_updates(50, 100, rng)
replay(algo, seq)
assert algo.maximal()
```

### Run a benchmark

```bash
python benchmarks/bench_axiom.py --n 200 --updates 5000 --mode multilevel
```

### Compare modes in parallel

```python
from axiom.parallel import compare

results = compare(n=100, updates=2000, seed=42, max_workers=2)
for mode, r in results.items():
    print(f"{mode}: {r.updates_per_sec:.0f} updates/sec, matching={r.matching_size}")
```

---

## Architecture

Each Axiom module owns one clear responsibility:

| Module | Responsibility |
|---|---|
| `axiom.core` | The `Matcher` orchestrator: graph, matching, z-system, augment, rebuild dispatch |
| `axiom.graph` | `Adjacency`: the dynamic undirected graph (BST-replacement: hash sets) |
| `axiom.system` | `System`: the single-level z-subgraph system + `build`, `promote`, `switch` |
| `axiom.hierarchy` | `Hierarchy`: the *k*-level system + `build_hierarchy` + (I3) `check_i3`, `maintain_i3` |
| `axiom.color` / `axiom.paper_coloring` | `Colorer` Protocol, classical utilities, and deterministic paper fan primitives |
| `axiom.matching` | Pure helpers: `greedy`, `partner`, `partners`, `canonical` |
| `axiom.core` | `Matcher`: insertion/deletion local handling and rematch dispatch (private `__handle_insertion`, `__handle_deletion`, `__rematch_*`) |
| `axiom.rebuild` | Internal `Basic` and `Multilevel` rebuild strategies |
| `axiom.augment` | `augment`, `flip`: alternating-path search over a matching |
| `axiom.ledger` | `Ledger`: explicit counters for amortised-cost diagnostics |
| `axiom.simulation` | `random_updates`, `replay`, `Update`: deterministic update sequences |
| `axiom.parallel` | `Benchmark`, `worker`, `run_parallel`, `compare`: parallel benchmarks |
| `axiom.visualize` | `visualize_system`, `visualize_matching`, `visualize_adjacency`: ASCII renderers |
| `axiom.types` | Type aliases (`Vertex`, `Edge`, `Matching`, `Color`, `Coloring`), Protocols, `canonical` |
| `axiom.cli` | `main(argv)`: command-line entry point |

---

## API

The full public surface is in [`axiom/__init__.py`](axiom/__init__.py). Highlights:

```python
# # Core
from axiom import Matcher

algo = Matcher(
    n=100,
    mode="basic",  # or "multilevel"
    graph=None,  # default Adjacency(100)
    colorer=None,  # optional basic-mode colorer; fixed PaperFanColorer for multilevel
)

algo.insert(u, v)  # insert edge (u, v)
algo.delete(u, v)  # delete edge (u, v)
algo.matching()  # copy of the maintained matching
algo.maximal()  # is the matching maximal?
algo.size()  # number of edges in the matching
algo.partner(v)  # partner of v, or None (O(1) via partner map)
algo.partners()  # full partner dict
algo.stats()  # bookkeeping counters

# # Construction helpers
from axiom import (
    Adjacency,  # graph
    System,
    Hierarchy,  # z-system / multi-level
    Greedy,
    Vizing,
    PaperFanColorer,  # edge colorers
    Ledger,  # accounting
    random_updates,
    replay,
    visualize_system,
    visualize_matching,
    visualize_adjacency,
    run_parallel,
    compare,  # parallel benchmarks
)

# # Construction primitives
from axiom.system import build, switch, promote
from axiom.hierarchy import build_hierarchy
```

---

## Invariants

The implementation tracks the seven invariants of the *z*-subgraph system from Section 2 of the paper:

1. Degree bounds in *M*: every *v* &isin; *S* has *z* incident *M*-edges; every *u* &isin; *U* has &le; *z*.
2. *U*-*U* degree bound: |*N*<sub>G</sub>(*u*) &cap; *U*| &le; *z* for *u* &isin; *U*.
3. (P1): |*N*<sub>G</sub>(*u*) &cap; *B*| &le; 2*z* for *u* &isin; *U*.
4. (P2): every *M*-edge incident to *a* &isin; *A* meets a vertex of *S*.
5. &Lambda;(*u*) = *N*<sub>G</sub>(*u*) &cap; (*B* &cup; *U*) for *u* &isin; *U*.
6. *L*(*a*) = *N*<sub>G</sub>(*a*) &cap; *U* for *a* &isin; *A*.
7. (Multi-level I3): &le; 2&tau; vertices of *A*<sub>1</sub> are matched by *M*<sup>*</sup> into *R*<sub>1</sub>.

All invariants are checked by the methods on `Matcher`, `System`, and `Hierarchy`:

```python
assert matcher.maximal()
assert system.check()
assert hierarchy.check_i3(matching, r=phase_length, z=level_z)
```

---

## Modes

### `basic`

A single-level *z*-system with:

- *z* = &lceil;*n*<sup>2/3</sup>&rceil;
- *r* = phase length = &lceil;*n*<sup>4/3</sup>&rceil;
- subphase length = *r* / *z*

Paper target: &Otilde;(*n*<sup>2/3</sup>) amortised in the paper's model. This
implementation does not claim that bound until the deferred paper-specific
colouring and update machinery is complete.

### `multilevel`

A density-sensitive construction with two phase regimes. When the phase-start
graph has at most *n*<sup>3/2</sup> edges it uses one level with
*z* = &lceil;&radic;*n*&rceil;. In the denser regime it chooses *z*<sub>1</sub>
as the least power of two at least the average degree, then derives
*z*<sub>*i*</sub> = *z*<sub>*i*-1</sub> / 2 down to the paper's
*&radic;*n* /(4 log *n*)* threshold. Each level-*i* phase has length
*z*<sub>*i*</sub>&middot;*eta*, where *eta* is the power of two in
[*&radic;*n*, 2&radic;*n*).

Paper target: *n*<sup>1/2+o(1)</sup> amortised in the paper's model. This
implementation exposes the recursive construction and validates its matching
and hierarchy invariants, but does not claim the paper's full bound yet.

Invariant (I3) is enforced after every update in multilevel mode: any *A*<sub>1</sub>-vertex matched into *R*<sub>1</sub> is broken and re-routed via the existing rematch dispatch.

### Mode selection

Use one of the two canonical mode strings:

```python
algo = Matcher(n=100, mode="basic")  # Basic policy
algo = Matcher(n=100, mode="multilevel")  # Multilevel policy
```

---

## Invariants, assumptions, edge cases

| Assumption | Notes |
|---|---|
| Vertex labels are dense integers in `[0, n)` | Enforced by `Adjacency.validate_vertex`.` |
| No self-loops | `Adjacency.add_edge` silently ignores; `strict=True` raises. |
| No parallel edges | `Adjacency.add_edge` silently ignores duplicates; `strict=True` raises. |
| Custom graphs | Must satisfy the full `Graph` protocol and expose a symmetric simple graph; invalid implementations are rejected during `Matcher` construction. |
| Empty graph | `n == 0` is supported; the empty matching is trivially maximal. |
| Single vertex | `n == 1` is supported; the matching is empty. |

### Limitations

- **Empirical counters vs asymptotic guarantees.** The `Ledger` reports what actually happened in Python. The paper's bounds rely on a specific model and construction; use the counters and benchmarks to evaluate this implementation independently.
- **ABB+26 colouring.** `multilevel` now uses the explicit paper fan-shift,
  alternating-path, activation, and deterministic u-edge reduction pipeline.
  The cited ABB+26 almost-linear type-sparsification construction is still not
  included, so its asymptotic bound and the paper's end-to-end theorem are not
  claimed.
- **Multi-level derivation.** Each multilevel rebuild recursively derives the next z-system from the previous level, retaining level partitions, regions, and inherited lists.

---

## Citation

This implementation is based on:

```
Chuzhoy, J., Khanna, S., Song, J. (2026).
A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching.
arXiv:2605.00797v1.
```

Please cite the paper when using Axiom in academic work.

---

## License

[MIT](LICENSE) &copy; 2026 Sachin.
