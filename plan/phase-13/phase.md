# Phase 13 — Packaging, release gates, and deferred engine boundaries

**Roadmap coverage:** objectives 14, 16, and 17.  
**Status:** Packaging is partially implemented and cross-platform CI is in progress; release gates remain open. Objective 16 is explicitly a future-engine boundary, not a current feature commitment.

## Goal

Ship reproducible supported artifacts only when each mode independently clears research, durability, performance, and deployment gates.

## Work

- Verify source/wheel installs across supported Python versions and Linux/macOS/Windows architectures; decide unsupported ARM64/musllinux targets explicitly.
- Pin and reproduce native storage builds; publish ABI/API compatibility and supported platform policy.
- Add container and readiness/health examples where they improve supported deployment.
- Maintain per-mode qualification manifests for invariants/adversarial tests, restart/rollback, workload/latency/memory budgets, and operations evidence.
- Make release tooling reject missing, stale, or cross-mode evidence. Publish exclusions and supported envelope with each release.
- Keep maximum, weighted, preference, constrained, and capacity matching as separate candidate engines requiring independent contracts and gates; do not change current maximal-matching semantics.

## Exit evidence

- Reproducible clean install and wheel tests pass on every claimed target, with retained artifacts and provenance.
- Release verifier rejects each missing/stale/mode-mismatched gate and accepts only fully evidenced candidates.
- Release notes and operations guide state supported limits, deferred hardware power-loss, and unsupported billion-node claims.

## Dependencies

All qualification phases feed this gate. Transport ships only after phase 12 and local service qualification.
