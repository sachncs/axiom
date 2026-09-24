export const SITE = {
  title: "Axiom",
  tagline: "Fully dynamic maximal matching — made deterministic",
  description:
    "Axiom is a pure-Python implementation of deterministic fully dynamic maximal matching with basic and recursive multilevel modes.",
  repo: "https://github.com/sachncs/axiom",
  paper: "https://arxiv.org/abs/2605.00797v1",
  readme: "https://github.com/sachncs/axiom/blob/master/README.md",
  docs: "https://github.com/sachncs/axiom/tree/master/docs",
  changelog: "https://github.com/sachncs/axiom/blob/master/CHANGELOG.md",
  license: "https://github.com/sachncs/axiom/blob/master/LICENSE",
  citation: `Chuzhoy, J., Khanna, S., Song, J. (2026).\n  A Faster Deterministic Algorithm for Fully Dynamic Maximal Matching.\n  arXiv:2605.00797v1 (STOC 2026).`,
} as const;

export const NAV = [
  { label: "Get started", href: "get-started/" },
  { label: "Playground", href: "playground/" },
  { label: "Concepts", href: "concepts/" },
  { label: "Modes", href: "modes/" },
  { label: "API", href: "api/" },
  { label: "Examples", href: "examples/" },
] as const;

export const METRICS = [
  {
    value: "2",
    label: "canonical modes",
    note: "basic · multilevel",
  },
  {
    value: "Θ(log n)",
    label: "hierarchy levels",
    note: "k-level recursive partition",
  },
  {
    value: "core",
    label: "invariants verified",
    note: "z-system + multilevel checks",
  },
  {
    value: "0",
    label: "runtime dependencies",
    note: "pure Python · stdlib only",
  },
] as const;

export const PROBLEM = [
  {
    step: "01",
    title: "The stream",
    body: "Edges arrive and depart one at a time — insertions, deletions, insertions again. The graph never sleeps, and the matching must keep up without ever rebuilding from scratch.",
  },
  {
    step: "02",
    title: "The invariant",
    body: "A maximal matching is a local proof of coverage: every edge touches at least one matched vertex. Axiom restores it deterministically after every accepted update.",
  },
  {
    step: "03",
    title: "The cost",
    body: "The z-subgraph system localises update damage while preserving maximality after every accepted operation.",
  },
] as const;

export const FEATURES = [
  {
    icon: "layers",
    title: "Two operating modes",
    body: "basic runs the single-level algorithm; multilevel recursively refines z-systems through k ≈ ½ log n levels.",
  },
  {
    icon: "graph",
    title: "z-subgraph system",
    body: "The implemented (A, B, U) partition, S = A ∪ B saturation, Λ(u) and L(a) index lists, with explicit state validators.",
  },
  {
    icon: "palette",
    title: "Deterministic colouring",
    body: "Basic uses deterministic Vizing colouring; multilevel uses the paper-oriented recursive fan colourer with explicit failure diagnostics. The ABB+26 asymptotic bound is not claimed.",
  },
  {
    icon: "invariant",
    title: "Invariant checks",
    body: "Independent read-only validators prove maximality, every z-system property, and the multi-level (I3) bound at any moment. Call them from tests or debug scripts.",
  },
  {
    icon: "path",
    title: "Augmenting-path maintenance",
    body: "Deterministic alternating-path augmentation is applied internally at subphase boundaries; the low-level primitives remain available in axiom.augment.",
  },
  {
    icon: "ledger",
    title: "Empirical ledger",
    body: "Explicit counters track phase and subphase rebuilds, rematch scan sizes, and cleanup work — an account of where every update spends its time.",
  },
] as const;

export const MODES = [
  {
    name: "Basic",
    tag: "single-level · deterministic",
    complexity: "single-level",
    period: "deterministic maximality",
    points: [
      "z = ⌈n^2/3⌉ saturation threshold",
      "phase length r = ⌈n^4/3⌉",
      "subphase length r / z",
      "ideal for mid-size graphs & teaching",
    ],
    accent: "cobalt",
    cta: 'mode="basic"',
  },
  {
    name: "Multilevel",
    tag: "multi-level · k = Θ(log n)",
    complexity: "recursive",
    period: "deterministic maximality",
    points: [
      "z₁ ≈ n (power of two), zᵢ = zᵢ₋₁ / 2 recursive levels",
      "k = ⌈log₂ √n⌉ hierarchy depth",
      "level-k threshold z_k ≈ √n",
      "Invariant (I3) enforced after every update",
    ],
    accent: "violet",
    cta: 'mode="multilevel"',
  },
] as const;

export const API_SNIPPET = `from axiom import Matcher

algo = Matcher(n=100, mode="multilevel")

algo.insert(0, 1)      # edge arrives
algo.insert(2, 3)
algo.delete(1, 0)      # edge leaves

assert algo.maximal()  # still maximal — instantly
print(algo.matching()) # {(2, 3)}
print(algo.size())     # 1
print(algo.stats())    # amortised ledger`;

export const CLI_SNIPPET = `$ axiom --n 20 --mode basic --updates 200 --seed 42

=== Axiom Demo: n=20, mode=basic, updates=200 ===
Completed 200 updates in 0.001s
Final edges: 12
Matching size: 8
Maximal: True`;

export const REBUILD_SNIPPET = `# Strobes of work land on a dark chart —
# matching size stays maximal through every
# update, while the ledger explains the cost.

n=200 · updates=5000 · mode=multilevel   ───■── 6.2k upd/s
rebuilds          827
rematch scans     12,913
cleanup work      31`;

export const INSTALL = {
  pip: "pip install git+https://github.com/sachncs/axiom.git",
  dev: "pip install -e \".[dev]\"",
} as const;

export const FOOTER_LINKS = [
  {
    group: "Project",
    links: [
      { label: "Get started", href: "get-started/" },
      { label: "Examples", href: "examples/" },
      { label: "Changelog", href: "changelog/" },
      { label: "Contributing", href: "contributing/" },
    ],
  },
  {
    group: "Engineering",
    links: [
      { label: "Concepts", href: "concepts/" },
      { label: "API reference", href: "api/" },
      { label: "Modes deep-dive", href: "modes/" },
      { label: "Architecture", href: "architecture/" },
    ],
  },
] as const;
