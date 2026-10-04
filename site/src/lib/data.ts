export const SITE = {
  title: "Axiom",
  tagline: "Deterministic dynamic graph matching",
  description:
    "Alpha-stage deterministic maximal matching with Basic and Multilevel paper modes, SQLite durability, and qualification still in progress.",
  paper: "https://arxiv.org/abs/2605.00797v1",
} as const;

export const NAV = [
  { label: "Production", href: "production/" },
  { label: "Research", href: "research/" },
  { label: "Upcoming", href: "upcoming/" },
  { label: "Docs", href: "docs/" },
  { label: "Walkthrough", href: "playground/" },
  { label: "GitHub", href: "https://github.com/sachncs/axiom" },
] as const;

export const METRICS = [
  {
    value: "2",
    label: "paper matching modes",
    note: "basic + multilevel",
  },
  {
    value: "1 million",
    label: "Basic updates exercised",
    note: "recovery gate still fails",
  },
  {
    value: "0",
    label: "modes deployment-qualified",
    note: "qualification is open",
  },
  {
    value: "10k/s",
    label: "durable update target",
    note: "not yet demonstrated",
  },
] as const;

export const API_SNIPPET = `from pathlib import Path
from tempfile import TemporaryDirectory
from axiom.durable import Request
from axiom.service import Service

with TemporaryDirectory() as directory:
    with Service(Path(directory) / "graph.db", n=128) as graph:
        outcome = graph.submit(Request(1, "delete", 0, 1)).result(5)
        assert graph.partner(0).result(5) == (outcome.version, None)
        assert graph.check().result(5)`;

export const INSTALL = {
  pip: "pip install git+https://github.com/sachncs/axiom.git",
  dev: "pip install -e \".[dev]\"",
} as const;

export const FOOTER_LINKS = [
  {
    group: "Project",
    links: [
      { label: "Get started", href: "get-started/" },
      { label: "Research", href: "research/" },
      { label: "Examples", href: "examples/" },
      { label: "Changelog", href: "changelog/" },
      { label: "Alpha state & upcoming", href: "upcoming/" },
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
      { label: "Production & evidence", href: "production/" },
    ],
  },
] as const;
