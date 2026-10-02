# Build, validation and publishing

Updated 2026-10-03. Astro is the only site build. Repository Markdown documents
are engineering references, not a second Jekyll website. There is no Ruby,
Bundler, Gemfile, Jekyll theme or Jekyll deployment job. Obsolete `.nojekyll`
markers and the unused duplicate social-preview generator/assets are removed;
historical changelog entries retain their original context.

## Separate responsibilities

| Workflow | Responsibility | Publication |
| --- | --- | --- |
| `ci.yml` | Lint/types, normal and optimized Python 3.10–3.13, native sanitizers, clean wheel/sdist installs, reproducibility/dependency checks, stress and actual Linux resource recovery | None |
| `pages.yml` | Astro type/build/link checks and real installed Python documentation examples, on PR and master | Deploy only master push/manual runs; PR builds have read-only permissions |
| `release.yml` | Tag/version and research-gap gates, quality checks, artifact validation/reproducibility, attestations/signatures | Explicit release tags only; no new release is made by a documentation push |

All workflows retain pinned action revisions, disabled checkout credentials,
explicit least-privilege permissions and bounded job timeouts. Shell steps use
Bash fail-fast/pipefail behavior. CI and site builds cancel superseded revisions
independently. Site validation is no longer duplicated across workflows; the
same validated Astro build is the deployed artifact.

Clean wheel and source installs call `scripts/verify_install.py` with isolated
Python rather than repeating long shell-embedded Python programs. It verifies
paper/native storage, native publication/rollback/image roundtrip, legacy
durability, checkpoint retirement, exact retries/recovery, bounded service drain,
coherent queries and backup restore. Full tests and sanitizers remain separate;
this script is an artifact integration gate, not their replacement.

## Local reproduction

```bash
python -m pytest -q
ruff check axiom tests scripts benchmarks examples
ruff format --check axiom tests scripts benchmarks examples
mypy axiom
cd site
npm ci
npm run check
npm run build
npm run check:links
cd ..
python scripts/verify_site_examples.py
```

Use the built wheel in a clean environment for `python -I scripts/verify_install.py`.
Do not run performance qualification alongside local tests/builds. Actual Linux
resource recovery needs the dedicated disposable filesystem used in CI; it is
not safe to emulate by filling the developer's working filesystem.

Passing CI is evidence for its exact source/artifacts, not a benchmark, physical
power-loss proof, completed paper migration or blanket production qualification.
