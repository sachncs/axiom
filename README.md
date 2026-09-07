<p align="center">
  <h1 align="center">axiom</h1>
  <p align="center">A Faster Deterministic Fully Dynamic Maximal Matching Algorithm &mdash; pure-Python reproduction of Chuzhoy, Khanna, and Song (arXiv:2605.00797v1, STOC 2026).</p>
  <p align="center">
    <a href="#installation"><img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue" alt="Python"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
    <a href="https://github.com/sachncs/fully-dynamic-maximal-matching/actions"><img src="https://img.shields.io/github/actions/workflow/status/sachncs/fully-dynamic-maximal-matching/ci.yml?branch=master" alt="CI"></a>
    <a href="https://github.com/sachncs/fully-dynamic-maximal-matching"><img src="https://img.shields.io/badge/arXiv-2605.00797v1-b31b1b" alt="arXiv"></a>
    <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/mypy-strict-green.svg" alt="Checked with mypy"></a>
    <a href="https://github.com/sachncs/fully-dynamic-maximal-matching/stargazers"><img src="https://img.shields.io/github/stars/sachncs/fully-dynamic-maximal-matching" alt="Stars"></a>
  </p>
</p>

**axiom** is a pure-Python reproduction of *A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching* by Chuzhoy, Khanna, and Song (STOC 2026, [arXiv:2605.00797v1](https://arxiv.org/abs/2605.00797v1)). It maintains a **maximal matching** in an undirected graph under online edge insertions and deletions in amortised &Otilde;(*n*<sup>1/2+o(1)</sup>) update time.

---

## Features

- **Two operating modes**
  - `basic` &mdash; the single-level &Otilde;(*n*<sup>2/3</sup>) algorithm
  - `tiered` &mdash; the *n*<sup>1/2+o(1)</sup> *k*-level recursive version with *k* = &Theta;(log *n*)
- **Strategy pattern** &mdash; pick `Basic()` or `Tiered()` explicitly, or use the `mode=` string for backwards compatibility.
- **z-subgraph system** &mdash; full implementation of the (*A*, *B*, *U*) partition, the *S* = *A* &cup; *B* saturation, the &Lambda;(*u*) and *L*(*a*) index lists, and the seven invariants from Section 2 of the paper.
- **Multi-level hierarchy** &mdash; Invariant (I3) of the multi-level system is **implemented and maintained** (not stubbed): &le; 2&tau; vertices of *A*<sub>1</sub> may be matched by *M*<sup>*</sup> into *R*<sub>1</sub>, where &tau; = 32 *r* / *z*.
- **Deterministic edge colouring** &mdash; Vizing's classical alternating-path recolouring for (&Delta;+1)-colourings, plus the faster degree-ordered greedy colourer used to partition *M* into colour classes.
- **Augmenting-path API** &mdash; `Matcher.augment()`, `Matcher.try_augment()`, `Matcher.flip()` are first-class public methods (no name-mangled privates).
- **Comprehensive invariant checks** &mdash; independent checkers for maximality, every *z*-system property, and the multi-level (I3) bound; callable from tests or debugging scripts.
- **Empirical ledger** &mdash; explicit counters for the number of rebuilds, rematch scan sizes, stale cleanups, and greedy fallbacks. Useful for diagnosing where time is spent; **not** a proof of the amortised bound.
- **Reproducible simulation** &mdash; seeded random update sequences with replay utilities for stress tests and benchmarks.
- **Zero runtime dependencies** &mdash; pure Python with the standard library; only the optional `.[dev]` extras (`pytest`, `mypy`, `ruff`, `hypothesis`) are pulled in for development.
- **Strict type checking** &mdash; every public signature is annotated; the repository enables `mypy --strict`.

---

## Installation

### From source

```bash
git clone https://github.com/sachncs/fully-dynamic-maximal-matching.git
cd fully-dynamic-maximal-matching
pip install -e .
```

### With dev dependencies

```bash
pip install -e ".[dev]"
```

This pulls in `pytest`, `pytest-cov`, `mypy`, `ruff`, and `hypothesis`.

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
print(algo.matching())   # {(2, 3)}
print(algo.partners())   # {2: 3, 3: 2}
print(algo.stats())      # amortised bookkeeping
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

algo = Matcher(50, mode="tiered")
rng = __import__("random").Random(7)
seq = random_updates(50, 100, rng)
replay(algo, seq)
assert algo.maximal()
```

### Run a benchmark

```bash
python benchmarks/bench_axiom.py --n 200 --updates 5000 --mode tiered
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
| `axiom.color` | `Colorer` Protocol + `Greedy` and `Vizing` implementations + alternating-path helpers |
| `axiom.matching` | Pure helpers: `greedy`, `partner`, `partners`, `canonical` |
| `axiom.repair` | `Repair`: encapsulates insertion/deletion local handling and rematch dispatch |
| `axiom.rebuild` | `Rebuild` Protocol + `Basic` and `Tiered` strategy implementations |
| `axiom.augment` | `augment`, `flip`: alternating-path search over a matching |
| `axiom.ledger` | `Ledger`: explicit counters for amortised-cost diagnostics |
| `axiom.invariant` | `is_maximal_matching`, `valid`, `check_i3`: read-only validators |
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
    mode="basic",                  # or "tiered"
    graph=None,                    # default Adjacency(100)
    colorer=None,                  # default Greedy()
    policy=None,                   # default Basic() or Tiered() by mode
)

algo.insert(u, v)                 # insert edge (u, v)
algo.delete(u, v)                 # delete edge (u, v)
algo.matching()                   # copy of the maintained matching
algo.maximal()                    # is the matching maximal?
algo.size()                       # number of edges in the matching
algo.partner(v)                   # partner of v, or None (O(1) via partner map)
algo.partners()                   # full partner dict
algo.stats()                      # bookkeeping counters

# # Augmenting-path API (public, promoted from private in v0.5.0)
algo.augment()                    # run subphase-boundary augmentation; returns count
algo.try_augment(start, matched)  # try augmenting along an alternating path
algo.flip(path)                   # flip alternating edges in a path

# # Construction helpers
from axiom import (
    Adjacency,                    # graph
    System, Hierarchy,            # z-system / multi-level
    Basic, Tiered,                # rebuild policies
    Greedy, Vizing,               # edge colorers
    Ledger,                       # accounting
    is_maximal_matching, valid, check_i3,  # invariant checkers
    random_updates, replay, Update,       # simulation
    visualize_system, visualize_matching, visualize_adjacency,
    Benchmark, run_parallel, compare,      # parallel benchmarks
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

All invariants are checked by the methods on `System` / `Hierarchy`, and the standalone helpers in `axiom.invariant`:

```python
from axiom.invariant import is_maximal_matching, valid, check_i3

assert is_maximal_matching(graph, matching)
assert valid(system)
assert check_i3(hierarchy, matching, r=phase_length, z=level_z)
```

---

## Modes

### `basic`

A single-level *z*-system with:

- *z* = &lceil;*n*<sup>2/3</sup>&rceil;
- *r* = phase length = &lceil;*n*<sup>4/3</sup>&rceil;
- subphase length = *r* / *z*

Per-update cost: &Otilde;(*n*<sup>2/3</sup>) amortised.

### `tiered`

A *k*-level recursive construction with:

- *z*<sub>1</sub> = *n*, *z*<sub>*i*</sub> = *z*<sub>*i*-1</sub> / 2
- *k* = &lceil;log<sub>2</sub> &radic;*n*&rceil; &asymp;; &half; log *n*
- level *k*'s *z*<sub>*k*</sub> &asymp;; &radic;*n*

Per-update cost: *n*<sup>1/2+o(1)</sup> amortised (Theorem 1.1 of the paper).

Invariant (I3) is enforced after every update in tiered mode: any *A*<sub>1</sub>-vertex matched into *R*<sub>1</sub> is broken and re-routed via the existing rematch dispatch.

### Mode selection

Use the `mode` string for backwards compatibility:

```python
algo = Matcher(n=100, mode="basic")    # Basic policy
algo = Matcher(n=100, mode="tiered")    # Tiered policy
```

Or pass a policy directly (recommended for new code):

```python
from axiom.rebuild import Basic, Tiered

algo = Matcher(n=100, policy=Basic())
algo = Matcher(n=100, policy=Tiered())
```

---

## Invariants, assumptions, edge cases

| Assumption | Notes |
|---|---|
| Vertex labels are dense integers in `[0, n)` | Enforced by `Adjacency.validate_vertex`.` |
| No self-loops | `Adjacency.add_edge` silently ignores; `strict=True` raises. |
| No parallel edges | `Adjacency.add_edge` silently ignores duplicates; `strict=True` raises. |
| Empty graph | `n == 0` is supported; the empty matching is trivially maximal. |
| Single vertex | `n == 1` is supported; the matching is empty. |

### Limitations

- **Empirical counters vs asymptotic guarantees.** The `Ledger` reports what actually happened in Python. The paper's amortised bounds assume a BST-based adjacency layer; the Python reproduction uses hash sets (amortised *O*(1) per op). The constants differ; the asymptotic shape is the same.
- **ABB+26 colouring.** The paper cites Theorem 2.4 (deterministic (&Delta;+1)-colouring in *O*(*m*<sup>1+o(1)</sup>) time). The implementation substitutes Vizing's theorem plus a degree-ordered greedy colourer, both of which run in *O*(*m* &middot; &Delta;) worst case. This is **less efficient** than the paper's colouring but matches its correctness contract.
- **Multi-level derivation.** The paper derives a *z*<sub>*i*</sub>-system from a *z*<sub>*i*-1</sub>-system in *O*(*n*<sup>1+o(1)</sup>*z*<sub>1</sub>) time, faster than rebuilding when the graph is dense. The implementation rebuilds each level independently from the current graph (clearer, empirically sufficient for the stress tests). The recursive derivation mechanics (*E*'<sub>*D*</sub> edge-set selection, list inheritance) are documented as DEFERRED-OPEN-PROBLEMS in `docs/paper_restatement.md`.

---

## Citation

This implementation is a paper-faithful reproduction of:

```
Chuzhoy, J., Khanna, S., Song, J. (2026).
A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching.
arXiv:2605.00797v1.
```

Please cite the paper when using Axiom in academic work.

---

## License

[MIT](LICENSE) &copy; 2026 Sachin.