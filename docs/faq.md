# FAQ

## What is Axiom?

Axiom is a pure-Python implementation of deterministic fully dynamic
maximal matching algorithms based on the Chuzhoy–Khanna–Song paper.

## How do I install it?

```bash
pip install axiom
```

For development:

```bash
pip install -e ".[dev]"
```

## Which modes are supported?

`basic` provides the single-level algorithm. `multilevel` provides the
recursive hierarchy. These are the only supported mode names.

## How do I run the tests?

```bash
pytest
ruff check axiom tests scripts benchmarks examples
mypy --strict axiom
```

## What happens with invalid input?

Vertices outside `[0, n)` raise `ValueError`. Self-loops, duplicate
insertions, and missing deletions are ignored by default by `Adjacency`;
strict graph operations raise `ValueError`.

Custom graph implementations are validated when passed to `Matcher`: they
must implement the complete `Graph` protocol and expose a symmetric simple
graph whose edge, neighbor, degree, and edge-count views agree.

## How do I cite Axiom?

```text
Chuzhoy, J., Khanna, S., Song, J. (2026).
A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching.
arXiv:2605.00797.
```

## What is the license?

MIT. See [`LICENSE`](../LICENSE).
