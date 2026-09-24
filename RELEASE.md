# Release Notes and Maintainer Handoff

## 1.0.0 readiness target

The 1.0.0 release is intentionally breaking. The only supported matcher
modes are `basic` and `multilevel`; legacy names, aliases, shims, and wrapper
APIs are not supported.

The current package version is `0.6.0.dev0`. The 1.0.0 tag must not be
created until the paper-faithful multilevel update pipeline, deterministic
coloring implementation, and their acceptance tests are complete.

## Architecture

The package is organized around these components:

- `axiom.core.Matcher`: public dynamic matching API and update orchestration.
- `axiom.system`: single-level z-system construction and validation.
- `axiom.hierarchy`: recursive multi-level refinement and hierarchy checks.
- `axiom.rebuild`: `Basic` and `Multilevel` rebuild policies.
- `axiom.color`: deterministic edge coloring implementations.
- `axiom.matching`, `System`, and `Hierarchy`: canonical matching and
  invariant operations.

Multilevel construction starts with a base z-system, selects color classes from
the preceding level, inherits prior regions and lists, and runs the promotion
pass required to establish the next level's bounds.

## Runtime contract

- `Matcher` maintains a deterministic maximal matching after every accepted
  update.
- The current implementation does not claim the paper's asymptotic update
  bound; the release gate requires the complete dynamic hierarchy repair
  pipeline before making that claim.
- Vertex labels are dense integers in `[0, n)`.
- Instances are not thread-safe and must be externally synchronized.
- Removed mode names, legacy imports, and deprecated compatibility aliases fail
  instead of being silently translated.

## Release gates

- `pytest` passes, including recursive hierarchy and small-graph termination
  tests.
- Ruff linting and formatting pass.
- `mypy --strict axiom` passes.
- The documentation site builds successfully.
- Source and wheel artifacts build and pass package metadata validation.
- Release artifacts are reproducible under a fixed `SOURCE_DATE_EPOCH`.
- Wheel and source artifacts receive signed provenance attestations, and the
  tagged GitHub release publishes a `SHA256SUMS` manifest.
- Clean-install smoke tests pass for Python 3.10 through 3.13.
- CI dependency and workflow security checks pass.
- README, API docs, website copy, and changelog describe only the canonical
  API and implemented behavior.
