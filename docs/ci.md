# Build, validation and publishing

Updated 2026-10-03. Astro is the only site build. Repository Markdown documents
are engineering references, not a second Jekyll website. There is no Ruby,
Bundler, Gemfile, Jekyll theme or Jekyll deployment job. Obsolete `.nojekyll`
markers and the unused duplicate social-preview generator/assets are removed;
historical changelog entries retain their original context.

## Separate responsibilities

| Workflow | Responsibility | Publication |
| --- | --- | --- |
| `ci.yml` | Lint/types, normal and optimized Python 3.10–3.13, native sanitizers, clean wheel/sdist installs, Linux/macOS/Windows native-wheel matrix, reproducibility/dependency checks, stress and actual Linux resource recovery | None |
| `pages.yml` | Astro type/build/link checks and real installed Python documentation examples, on PR and master | Deploy only master push/manual runs; PR builds have read-only permissions |
| `release.yml` | Tag/version and research-gap gates, quality checks, native release-wheel matrix, completeness validation, source reproducibility, attestations/signatures | Explicit version tags only; no publication from ordinary CI |

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

The `cross-platform-wheels` CI job builds CPython 3.10–3.13 wheels on native
Linux x86_64/ARM64, macOS x86_64/ARM64 and Windows x86_64 runners with pinned
`cibuildwheel`. The release workflow independently builds the same five-platform
matrix from the tagged source revision. Each wheel runs the installed-package
verifier, is uploaded as a platform-scoped workflow artifact, then downloaded by
the publish job only after every matrix leg succeeds. Before signing or
publishing, that job requires all 20 platform/CPython combinations and exactly
one source distribution; a missing platform wheel fails closed. The sdist is
built and reproducibility-checked in the aggregation job. Attestation, Sigstore
signing, PyPI trusted publishing and GitHub Release creation all operate only
after this check. The workflow trigger and job guards are version-tag-only;
ordinary CI has no publishing credentials or publication path.

Linux wheels use manylinux repair; musllinux is intentionally excluded. No
Windows ARM64 support is claimed. The release matrix is configured in
`.github/workflows/release.yml`; its artifact completeness is validated at
runtime because the authoritative wheel filenames are produced by the native
builders.

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
