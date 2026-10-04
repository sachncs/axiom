# FAQ

## What is Axiom?

Axiom maintains deterministic maximal matching through online edge changes.
Its only matching methods are paper-derived `basic` and `multilevel`, both
available through SQLite-backed `Durable` and thread-safe local `Service`.
`Packed` is compact graph storage only. See [current status](status.md) for
qualification and active/deferred work; no mode promises maximum-cardinality
matching.

## Why C++ and SQLite, rather than replacing one with the other?

C++ provides compact mutable adjacency in `Packed`; the Basic/Multilevel paper
algorithms maintain matching state. SQLite FULL-WAL operation history is the
durable authority, and `Durable`/`Service` provide recovery/publication and
bounded concurrency. Storage and matching are separate responsibilities.

## Can I scale to a million or billion vertices?

Scoped million-vertex degree-four full-ring, growth/drain and first indexed-hub
stages exceed 10k real durable changes/s with coherent queries and exact recovery.
This is not arbitrary degree support: degree-64 throughput failed the target.
Billion-vertex qualification and deployment integration are explicitly deferred,
not supported promises. See [evidence and limitations](status.md).

## How do I install it today?

```bash
pip install git+https://github.com/sachncs/axiom.git
```

This installs the current development build directly from source. A published
package install is intentionally not documented yet; the future distribution
name is `axiom-matching` because the unqualified PyPI name `axiom` belongs to
another project. The release gate still includes the remaining multilevel and
coloring validation. The Python import remains `from axiom import Matcher`.

For development:

```bash
pip install -e ".[dev]"
```

## Which modes are supported?

`basic` provides the single-level algorithm. `multilevel` provides the
recursive hierarchy. These are the only paper `Matcher` mode names; the native
`Service` is selected separately, not through a hidden paper-mode alias.

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
