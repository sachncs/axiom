# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — engineering through 2026-10-03

- Matcher update transactions now contain no recursive `deepcopy`: shallow root
  references combine with bounded undo for indexes and phase-clock cells. Failure
  tests patch `copy.deepcopy` to raise and verify exact rollback/retry. This removes
  a global recursive allocation but does not finish durable paper integration.
- The built-in `Adjacency` backend now journals only touched edges and uses local
  endpoint/count certificates during Matcher updates, removing the remaining
  whole-edge-set snapshots from its ordinary rollback path. Custom graph fallbacks,
  phase snapshots, state-sized certificates elsewhere, and durable paper modes
  remain open; see [ADR 0037](docs/adrs/0037-adjacency-edge-journal.md).
- `Matcher` now defaults to budgeted `Packed` graph storage; pass
  `graph=Adjacency(n)` for the Python reference backend. An empty one-million-
  vertex graph-only sample used about 9.5× less peak RSS with `Packed`; this is
  not an end-to-end Matcher scalability qualification. See
  [ADR 0038](docs/adrs/0038-default-packed-matcher-storage.md).
- Empty outgoing rows in the paper engine's directed H index are now implicit;
  this removes one empty Python set per unmatched vertex. One 100k empty basic
  Matcher trace reduced retained/peak traced allocations by about 59%/46%; this
  is not broad workload qualification. See
  [ADR 0039](docs/adrs/0039-sparse-empty-auxiliary-rows.md).
- `System` now stores only nonempty Lambda/L cache rows. Last-entry deletions
  prune rows, with the `Systems` journal restoring exact row aliases and contents
  on rollback. One empty 100k Matcher sample peaked at 40.5 MB RSS; the remaining
  dominant Python allocation is the `U` partition set. See
  [ADR 0040](docs/adrs/0040-sparse-system-cache-rows.md).
- Dense paper `U` partitions now use indexed packed membership/member arrays,
  while sparse partitions remain Python sets. `System.build()` also stores
  per-vertex matching degrees in unsigned integer arrays instead of a Python
  dictionary. An isolated million-counter allocation fell from 73.9 MB to
  4.0 MB; this is component memory evidence, not end-to-end paper qualification.
  See [ADR 0041](docs/adrs/0041-compact-paper-system-vertices.md).
- The paper System builder streams built-in `Adjacency`/`Packed` graph edges in
  their guaranteed deterministic order instead of retaining and sorting a
  global Python edge list. Custom graph iterators keep the sorted compatibility
  path. A 200k-vertex path enumeration sample reduced traced peak from 27.2 MB
  to 432 bytes; full rebuild performance remains unqualified. See
  [ADR 0042](docs/adrs/0042-stream-paper-builder-edges.md).
- System phase copies and hierarchy `R` regions preserve dense compact vertex
  partitions instead of expanding them into Python sets. An isolated million-
  member copy measured 8.0 MB vs 65.5 MB (87.8% lower); phase graph snapshots
  and remaining hierarchy state still contribute. See
  [ADR 0043](docs/adrs/0043-preserve-compact-paper-partition-copies.md).
- Multilevel refinement/audits now use packed degree counters, allocate
  incident-color rows only for matched endpoints, avoid redundant universe
  sets, and build one live-edge set instead of a phase set plus a derived copy.
  Existing hierarchy invariant, adversarial, rollback and replay tests gate the
  change; process-memory and rate qualification remain open. See
  [ADR 0044](docs/adrs/0044-compact-hierarchy-refinement-state.md).
- 1,206 local tests pass after sparse System/H rows, compact Matcher defaults,
  adjacency-journal integration and prior no-copy
  transaction/collision-routing regressions.

- Bounded full paper-state diagnostic comparison, replay-prefix and rollback
  qualification across both modes/storage backends, including shared references
  and redundant fan indexes. This is a migration oracle, not durable paper storage.

- Separate native deterministic incremental maximal matcher, compact blocked
  adjacency, bounded joint undo, immediate local certificates and exact images.
- SQLite FULL-WAL `Durable` owner with atomic checkpoint/history retirement,
  retained request deduplication, exact recovery and fail-stop uncertainty.
- Thread-safe bounded `Service`, group commit, reserved read admission,
  committed version/partner queries, bounded maintenance and local ownership.
- Independent paced/burst/full-ring/growth/drain/hub qualification harnesses,
  explicit offer-loss accounting, long-run recovery evidence and Linux hard
  allocation/disk-exhaustion drills. Earlier scoped milestone recorded 1,155 tests.
- Architecture decision records and operations guidance explaining production
  alternatives to whole-state copying and the limits of current guarantees.

### Fixed

- Real opposing Vizing chains could collide on an edge that both subsequent
  activations tried to flip after it had been uncolored; this rejected valid
  reductions and rolled back the collision. The resolver now selects the first
  shared edge in synchronized chain order and activates only the disjoint
  prefixes. Deterministic end-to-end tests force two such collisions, certify
  the final coloring, and inject failure to verify exact color/fan-index rollback.

- At the System-journal milestone, System objects retained their original root references through failures.
  Bounded first-write cells restore aliased Lambda/L rows and deleted matching
  edges; incremental basic/multilevel cache paths share this owner-bound journal.
  System alias memoization avoids copying its original cache rows. Remaining
  Hierarchy/auxiliary snapshots and state-sized admission/certificates remain;
  this is not yet durable paper integration.

- Basic/multilevel installed-wheel diagnostics after System journaling preserve
  identical certificates and every full-state update prefix; measurements and
  qualifications are recorded in `benchmarks/results/paper/systems.json`. These
  small nondurable runs are not production throughput claims.

- At the Hierarchy-journal milestone, multilevel Matcher transactions retained the prior Hierarchy root and its
  unchanged partition/index containers instead of recursively copying them.
  Deferred-edge mutations use bounded first-write undo; graph and System journals
  continue to own topology and shared cache rows. This was followed by the complete
  Matcher recursive-copy removal described above; neither milestone is durable paper integration.

- Basic/multilevel share class-owned System endpoint-cache deltas. Sorted rows
  use binary-search insert/remove rather than whole-row sorting; point-membership
  checks no longer construct partition unions inside endpoint/edge/neighbor loops.
  Invalid or unapplied graph deltas reject before cache edits. System/Hierarchy
  snapshots and full certificates remain; this is not durable paper integration.

- Paper color classes and seed removals now use bounded first-write membership
  undo. Failed subphase/rebuild candidates retain original list/set identity and
  seed/class sharing. A GIL-enabled CPython ownership proof accounts for intentional
  sharing; aliases/other runtimes retain global admission. Remaining System/Hierarchy
  snapshots still run; this is not durable paper integration or a throughput claim.

- Paper matching views now use first-write edge/endpoint undo, not full set/map
  copies. Failed local repair or rebuilt candidates retain original container
  identity. GIL-enabled CPython uses a reference-count uniqueness proof to avoid
  unnecessary alias walks; shared views/other runtimes retain conservative
  admission. Remaining snapshots/certificates still run; this does not establish
  million-vertex paper throughput or durability.

- Paper accounting now journals first writes instead of copying/replacing the
  Ledger. Failed absent-edge deletions restore exact counters. Uncertain graph
  publication cleanup or failed rollback fail-stops the Matcher and rejects
  future updates/queries. Wider snapshot removal and durable paper integration
  remain required; this partial migration carries no throughput claim.

- Reconciled the Astro site, README, changelog and documentation with the native
  durable service and current measured evidence; active and deferred scope is
  explicit. Removed unused site components, legacy preview duplicates/generator
  and Jekyll-disable markers. Astro is the only publishing path.
- Consolidated Astro PR/build/deploy checks and executable documentation examples;
  removed duplicate CI site builds and repeated shell-embedded install programs.
  Retained all normal/optimized, sanitizer, artifact and recovery gates.

- Fan-pruning collision/chain/precondition rollback regression coverage.
- Rounded paced-arrival deadline inversion and bounded IPC drain/loss accounting.
- Moderate-degree index allocation cliff, retaining indexed hub lookups with an
  explicit memory/compute tradeoff; degree-64 throughput remains below target.
- Growth/drain backup restore ENOSPC: compact private staged backups without
  vacuuming the live authority, weakening durability, or raising resource caps.

### Qualification and boundaries

- Fresh installed-wheel million-vertex burst-plus-indexed-hub stage delivers
  10,431 real durable changes/s with 1.80m exact queries, 59 checkpoints and exact
  recovery. Retains all losses, including 56,554 rejections and twelve accepted
  scheduled-offer-to-ack tails over one second; not a no-loss latency guarantee.

- Million-vertex degree-four full-ring 30-minute and growth/drain 10-minute
  stages exceed 10k real durable changes/s with queries and exact recovery.
  First independently paced degree-65,536 hub stage also passes; broader
  repeatability/skew and durable paper-engine integration remain active.
- Deployment integration/aggregate quotas, tighter latency, physical power-loss
  and billion-vertex qualification are deferred by user, not delivered promises.
- Durable `basic`/`multilevel` integration through the production service is now
  required active work, alongside paper journal migration. The current Matcher
  API still lacks persistence; integration is not delivered or performance-qualified
  yet. Native matching does not inherit the paper's theorem. No 1.0 release is claimed.
- Replaced the animated browser simulation with an executable native
  deletion/insertion/query/reopen trace. Removed demo/reveal scripts, switched
  the default palette to ivory/charcoal/teal and fixed hidden-menu spacing.
- Redesigned the logo as a shared paired-rail mark; aligned header/footer,
  README vector, SVG/16px/32px favicons, touch icon and cache-versioned social
  preview. Build checks reject missing or divergent brand geometry.

Historical releases below describe their original scope. Current contracts and
evidence are indexed in [status](docs/status.md) and [engineering](docs/engineering.md).

## [0.6.0.dev0] - 2026-09-23

### Breaking changes

- `multilevel` is the canonical recursive hierarchy mode.
- Removed the historical recursive-mode spelling, `from_mode`, and all
  compatibility aliases.
- Multilevel rebuilds now recursively refine each level from its predecessor.

### Added

- Recursive hierarchy validation through `Hierarchy.check()`.
- Small-graph termination and recursive-construction regression tests.
- Wheel validation, dependency auditing, and release automation in CI.

### Added

- `docs/assets/social-preview.png` (1280x640) for the GitHub social
  preview slot, generated by `scripts/render_social_preview.py`.
  The image is also mirrored at `.github/social-preview.png`.
- `assets/logo.svg` is now referenced from the README hero.
- Tests for `axiom.cli` (was 0% covered) and additional paths in
  `axiom.parallel` (was 66%). `cli.py` now at 91% and `parallel.py`
  at 90%.

### Changed

- GitHub repository description expanded from "Fully Dynamic Maximal
  Matching" to a value-proposition sentence naming the paper,
  language, and operating modes.
- Repository topics set to: `algorithm`, `complexity`,
  `data-structures`, `deterministic-algorithm`, `dynamic-algorithms`,
  `graph`, `matching`, `maximal-matching`, `python`,
  `theoretical-computer-science`.
- `pyproject.toml [project.urls].Documentation` now points to the
  rendered GitHub Pages site at https://sachncs.github.io/axiom/.

### Fixed

- Documentation references to a non-existent `axiom.repair` module
  (`README.md`, `docs/index.md`, `docs/architecture.md`) now point to
  `axiom.core`, where the local insertion/deletion/rematch logic
  actually lives.
- `Matcher` class docstring updated to reference the renamed public
  methods (`insert`, `delete`, `accountant`/`stats`) and the
  post-refactor field names.
- README badges and `pyproject.toml` `[project.urls]` no longer point
  to the legacy `sachncs/fully-dynamic-maximal-matching` slug.
- `CONTRIBUTING.md`, `docs/getting-started.md`, `docs/faq.md`, and
  the README install snippet now use `sachncs/axiom.git`.
- `docs/architecture.md` closing paragraph rewritten to fix the
  "besitself" word-processing artifact.
- `docs/api.md` Protocol snippets fixed: `num_count` -> `num_edges`,
  duplicate `class` keyword and phantom `Vector` protocol removed.
- `Matcher.__handle_insertion` refactored into a small helper
  (`__try_fast_insert`) with explicit (A, U) endpoint detection.
- `axiom.parallel.worker` `updates_per_sec` now returns `inf` when
  `updates == 0` (previously returned `0.0`).

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
- The canonical recursive mode is `"multilevel"`; the breaking release does
  not retain the historical mode spelling.
- The free function `check_multi_level_i3` is renamed to `check_i3` to match the `Hierarchy.check_i3` method.

### Added

- **Strategy pattern for phase rebuilds.** `axiom.rebuild` exposes a `Rebuild` Protocol with two implementations: `Basic` (single-level) and `Multilevel` (multi-level). The `Matcher` holds one and delegates configuration and rebuilding.
- The historical `Matcher.augment()`, `Matcher.try_augment()`, and
  `Matcher.flip()` methods are not part of the current API; the current
  release keeps augmenting-path operations in `axiom.augment` and the
  dynamic update pipeline private.
- **Invariant (I3) is implemented.** `Hierarchy.check_i3(matching, r, z)` returns whether at most `2 * tau = 64 r / z` edges of `matching` cross between `A1` and `R1`. `Hierarchy.maintain_i3` repairs violations; the matcher invokes that repair path internally after recursive-mode updates.
- The current API exposes `Matcher.partner()` and `Matcher.partners()` for
  partner queries; `partner_map` is internal state and is maintained in
  lockstep with the matching.
- **`axiom.augment`** &mdash; free-function BFS over alternating paths and alternating-path flip.
- The former `axiom.repair`, `axiom.modes`, and `axiom.api` refactor artifacts
  were subsequently consolidated into the current package modules and docs.

### Removed

- Dead state field `Matcher.aux_graph` and dead method `__rebuild_aux_graph` (no code path ever read it).
- Trivial private wrapper `__repair_matching` (inlined at the two call sites).
- Deprecated module `fdmm.updates` (logic merged into `axiom.core`).
- Documentation file `docs/audit_report.md` (audited the pre-refactor `fdmm/` layout, now invalid).

### Fixed

- `Adjacency.remove_edge` self-loop handling is now symmetric with `add_edge`: silent no-op in default mode, `ValueError` in `strict` mode.
- `refresh()` rejects conflicting seed edges instead of silently dropping them,
  so coloring errors cannot be hidden by a fallback matching.
- The two pre-existing test failures (`test_rematch_u_no_phantom_edge_from_stale_list` and `test_partition_m_color_range_error`) are fixed; both were stale references to private `__rebuild_basic` and the deleted `axiom.dynamic_matching` module.
- Two `Security.md` / `CODE_OF_CONDUCT.md` placeholder strings are replaced with the actual contact email.

### Internal

- `mypy --strict` continues to pass on `axiom/`.
- Test count: 33 &rarr; 108 (+ 75) across 9 test classes.
- All 108 tests pass on Python 3.10, 3.11, 3.12, 3.13.

## [0.4.1] - 2026-05-18

### Fixed

- Bug fixes and stability improvements
