# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-09-04

### Rebrand

The project is renamed from `maxmatch` (formerly `fdmm`) to **axiom**.
The package namespace, console script, and every reference in docs,
tests, examples, and CI is updated to match.

### Breaking changes

- Package namespace: `maxmatch.*` &rarr; `axiom.*`.
- Main class: `MaximalMatcher` &rarr; `Matcher`.
- Graph class: `DynamicGraph` &rarr; `Adjacency`.
- Single-level system: `ZSubgraphSystem` & rarr; `System`.
- Multi-level system: `MultiLevelSystem` &rarr; `Hierarchy`.
- Edge colourers: `GreedyColorer` &rarr; `Greedy`, `VizingColorer` &rarr; `Vizing`.
- Protocol: `EdgeColorer` &rarr; `Colorer`.
- Accounting: `UpdateAccountant` &rarr; `Ledger`.
- Benchmark result: `BenchmarkResult` &rarr; `Benchmark`.
- All `Matcher` methods are now single-word verbs/nouns:

  | Old | New |
  |---|---|
  | `insert_edge` | `insert` |
  | `delete_edge` | `delete` |
  | `get_matching` | `matching` |
  | `is_maximal` | `maximal` |
  | `matching_size` | `size` |
  | `build_partner_map` | `partners` |
  | `statistics` | `stats` |

- All `System` methods are now single-word verbs/nouns:

  | Old | New |
  |---|---|
  | `degree_in_M` | `degree` |
  | `neighbors_in_M` | `partner_in` |
  | `build_lambda_and_L` | `index` |
  | `check_degree_bounds` | `check_bound` |
  | `check_U_degree_in_U` | `check_u` |
  | `check_P1` | `check_p1` |
  | `check_P2` | `check_p2` |
  | `check_lambda_lists` | `check_lambda` |
  | `check_L_lists` | `check_L` |
  | `check_all_invariants` | `check` |
  | `is_maximal_matching` (method) | `maximal` |

- Free functions are renamed to single-word verbs/nouns:
  - `canonical_edge` &rarr; `canonical`
  - `greedy_maximal_matching` &rarr; `greedy`
  - `partner_of` &rarr; `partner_in`
  - `build_partner_map` &rarr; `partners`
  - `build_z_system` &rarr; `build`
  - `edge_switch_inside_B` &rarr; `switch`
  - `promote_u_vertex` &rarr; `promote`
  - `recolor_for_edge` &rarr; `recolor`
  - `color_single_edge` &rarr; `color_one`
  - `alternating_path` &rarr; `alternating`
  - `flip_path` &rarr; `flip`
  - `missing_colors` &rarr; `missing`
  - `find_edge_of_color` &rarr; `find`
  - `backtrack_color` &rarr; `backtrack`
  - `random_update_sequence` &rarr; `random_updates`
  - `replay_updates` &rarr; `replay`
  - `run_benchmark_worker` &rarr; `worker`
  - `run_parallel_benchmarks` &rarr; `run_parallel`
  - `compare_modes` &rarr; `compare`
- The mode string `"multilevel"` is deprecated in favour of `"tiered"`. The deprecated value still works but logs a deprecation note.
- The free function `check_multi_level_i3` is renamed to `check_i3` to match the `Hierarchy.check_i3` method.

### Added

- **Strategy pattern for phase rebuilds.** `axiom.rebuild` exposes a `Rebuild` Protocol with two implementations: `Basic` (single-level) and `Tiered` (multi-level). The `Matcher` holds one and delegates configuration and rebuilding.
- **Augmenting-path API is public.** `Matcher.augment()`, `Matcher.try_augment()`, `Matcher.flip()` are first-class methods (no longer name-mangled private).
- **Invariant (I3) is implemented.** `Hierarchy.check_i3(matching, r, z)` returns whether at most `2 * tau = 64 r / z` edges of `matching` cross between `A1` and `R1`. `Hierarchy.maintain_i3` repairs violations. `Matcher.maintain_i3()` is called after every update in `tiered` mode.
- **Partner dict for O(1) lookup.** `Matcher.partners: dict[Vertex, Vertex]` is maintained in lockstep with the matching via the public helpers `add_match` / `drop_match`.
- **`axiom.augment`** &mdash; free-function BFS over alternating paths and alternating-path flip.
- **`axiom.repair`** &mdash; local insertion/deletion handling and rematch dispatch (extracted from `Matcher`).
- **`axiom.modes`** documentation and **`axiom.api`** reference for the complete public surface.

### Removed

- Dead state field `Matcher.aux_graph` and dead method `__rebuild_aux_graph` (no code path ever read it).
- Trivial private wrapper `__repair_matching` (inlined at the two call sites).
- Deprecated module `fdmm.updates` (logic merged into `axiom.core`).
- Documentation file `docs/audit_report.md` (audited the pre-refactor `fdmm/` layout, now invalid).

### Fixed

- `Adjacency.remove_edge` self-loop handling is now symmetric with `add_edge`: silent no-op in default mode, `ValueError` in `strict` mode.
- `refresh()` is now defensive against corrupt seed matchings: any duplicate-vertex edges from the colourer are silently dropped before the greedy extension runs.
- The two pre-existing test failures (`test_rematch_u_no_phantom_edge_from_stale_list` and `test_partition_m_color_range_error`) are fixed; both were stale references to private `__rebuild_basic` and the deleted `axiom.dynamic_matching` module.
- Two `Security.md` / `CODE_OF_CONDUCT.md` placeholder strings are replaced with the actual contact email.

### Internal

- `mypy --strict` continues to pass on `axiom/`.
- Test count: 33 &rarr; 108 (+ 75) across 9 test classes.
- All 108 tests pass on Python 3.10, 3.11, 3.12, 3.13.

## [0.4.1] - 2026-05-18

### Fixed

- Bug fixes and stability improvements