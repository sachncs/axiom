# Release Notes & Maintainer Handoff

This document captures the post-refactor state of Axiom (v0.5.0) for
the next maintainer.

## What changed in v0.5.0

Axiom is a major rebrand + architectural refactor of the previous
`maxmatch` (formerly `fdmm`) package.

| Aspect | Before | After |
|---|---|---|
| Brand | maxmatch / fdmm | **axiom** |
| Main class | MaximalMatcher | **Matcher** |
| Graph | DynamicGraph | **Adjacency** |
| z-system | ZSubgraphSystem | **System** |
| Hierarchy | MultiLevelSystem | **Hierarchy** |
| Colourer class | GreedyColorer / VizingColorer | **Greedy** / **Vizing** |
| Protocol | EdgeColorer | **Colorer** |
| Ledger | UpdateAccountant | **Ledger** |
| Module count | 12 | 16 (single-responsibility split) |
| Strategy pattern | none | **Rebuild** Protocol with **Basic** + **Tiered** |
| Private helpers | name-mangled | public: `add_match`, `drop_match`, `partition`, `refresh`, `maintain_i3`, `augment`, `try_augment`, `flip` |
| Partner lookup | O(\|M*\|) linear scan | O(1) via partner dict |
| Invariant (I3) | NotImplementedError stub | **Implemented** with paper's 2τ constant + maintained per update in tiered mode |
| Dead code | aux_graph state (never read) | removed |

## Module map

```
axiom/
├── __init__.py     public exports
├── core.py         Matcher orchestrator
├── graph.py        Adjacency (graph)
├── system.py       System (single-level z-subgraph) + build/promote/switch
├── hierarchy.py    Hierarchy (k-level) + check_i3 / maintain_i3
├── color.py        Colorer Protocol + Greedy + Vizing + helpers
├── matching.py     greedy, partner_in, partners, canonical
├── rebuild.py      Rebuild Protocol + Basic + Tiered
├── augment.py      augment (BFS) + flip (alternating-path)
├── repair.py       local insert/delete handler (extracted)
├── ledger.py Ledger (counters)
├── invariant.py    is_maximal_matching, valid, check_i3
├── simulation.py   random_updates, replay, Update
├── parallel.py     Benchmark, worker, run_parallel, compare
├── visualize.py    visualize_system, visualize_matching, visualize_adjacency
├── trace.py        (dropped; use sequence + replay)
├── types.py        Vertex, Edge, Matching, Color, Coloring, Graph, Colorer
└── cli.py          main(argv)
```

## Algorithm pipeline (post-refactor)

```
init:    policy.configure(self)
         policy.rebuild(self)
              ├── Basic: build System, partition M, refresh()
              └── Tiered: build k levels, split A1/A2, derive N1/R1,
                          set system to innermost, partition, refresh()

insert:  graph.add_edge → handle_insertion (A,U fast path) →
         advance_counter:
            augment()      (subphase boundary)
            maintain_i3()  (tiered mode)
            policy.rebuild (phase boundary)

delete:  graph.remove_edge → handle_deletion:
            drop_match if deleted edge was in M*
            cleanup_stale_edges
            rematch_vertex (U/B/A dispatch)
            cleanup_stale_edges
            refresh() if not maximal
         advance_counter (same as insert)
```

## Invariant enforcement

| Invariant | Enforced by |
|---|---|
| Maximality | Verified by `is_maximal_matching()` after every delete |
| z-system invariants 1-6 | Constructed by `build(graph, z)`; checked by `System.check()` |
| Multi-level I3 | Constructed; checked by `Hierarchy.check_i3(matching, r, z)`; repaired by `Hierarchy.maintain_i3` after every tiered update |

## Deferred open problems

Per `docs/paper_restatement.md`, the following are still DEFERRED or
ACCEPTED-HEURISTIC:

- **Theorem 2.4 (ABB+26 colouring).** DEFERRED. The paper's *O*(*m*<sup>1+o(1)</sup>) bound is not implemented; we use Vizing's theorem and degree-ordered greedy instead.
- **Multi-level recursive derivation.** DEFERRED. Each level is rebuilt independently from the graph; the paper's recursive *z*<sub>*i*</sub>-from-*z*<sub>*i*-1</sub> derivation is documented but not implemented.
- **Exact $E'_D$ edge-set selection.** DEFERRED. The paper's small-subset selection for deriving a finer level from a coarser one is not specified in the excerpt.

## Compatibility

- `mode="multilevel"` still works as a deprecated alias for `mode="tiered"`.
- `mode="basic"` is unchanged.
- All public names use single-word naming; no semi-private `_*` or `__*` names are exported.
- Drop-in replacements for the most common v0.4.x imports are documented in `docs/api.md`.

## Performance expectations

The Python reproduction runs slower than the asymptotic shape would suggest because:

- Adjacency layer is hash sets, not BSTs (faster in practice, worse in the paper's model).
- Colouring is Vizing + greedy, not ABB+26.
- Multi-level rebuilds each level independently.

The asymptotic shape (per-update cost) is preserved.

## Validation checklist for future maintainers

- [ ] `pip install -e .` succeeds.
- [ ] `axiom --n 20 --mode basic --updates 200 --seed 42` exits 0.
- [ ] `axiom --n 20 --mode tiered --updates 200 --seed 42` exits 0.
- [ ] `pytest tests/` passes (target: ≥ 95% coverage, 108 tests).
- [ ] `ruff check axiom/ tests/ scripts/ benchmarks/ examples/` clean.
- [ ] `ruff format --check axiom/ tests/ scripts/ benchmarks/ examples/` clean.
- [ ] `mypy --strict axiom/` clean.
- [ ] CI matrix passes on Python 3.10, 3.11, 3.12, 3.13.
- [ ] `__version__ == "0.5.0"` and `pyproject.toml` version match.
- [ ] CHANGELOG.md has the [0.5.0] dated entry.

## Where to look for what

- **Algorithm correctness**: `tests/test_axiom.py::TestMatcher::test_random_stress_*` and the `maximal()` checks after every op.
- **z-system invariants**: `axiom/system.py` (`check_*` methods) and `tests/test_axiom.py::TestSystem`.
- **Multi-level invariants**: `axiom/hierarchy.py::check_i3`, `tests/test_axiom.py::TestHierarchy::test_check_i3_*`.
- **Refactor regression**: `tests/test_axiom.py::TestRefactor::test_*`.
- **Performance**: `benchmarks/bench_axiom.py` and `axiom/parallel.py::compare`.