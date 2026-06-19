---
phase: 08
slug: isolated-server-deployment
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-20
---

# Phase 08 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Python unittest |
| Config file | none |
| Quick run command | `python -m unittest tests.test_ops_health tests.test_deploy_assets tests.test_cli` |
| Full suite command | `python -m unittest discover -s tests` |
| Estimated runtime | under 1 second locally |

## Sampling Rate

- After each implementation plan: run focused tests.
- Before server checkpoint: run full suite, `git diff --check`, and sensitive
  boundary grep.
- Server smoke must start in dry-run mode.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-T1 | 08-01 | 1 | DEP-01, DEP-02, DEP-03 | static | `python -m unittest tests.test_deploy_assets` | present | passed |
| 08-02-T1 | 08-02 | 2 | DEP-04 | unit/CLI | `python -m unittest tests.test_ops_health tests.test_cli` | present | passed |
| 08-03-T1 | 08-03 | 3 | DEP-01, DEP-02, DEP-03 | static | `python -m unittest tests.test_deploy_assets` | present | passed |
| 08-04-T1 | 08-04 | 4 | DEP-01, DEP-04 | manual/server | `python -m unittest discover -s tests` plus server smoke | present | passed |

## Manual-Only Verifications

Actual server deployment requires a secure SSH/authentication path. If no
non-interactive safe auth is available, stop at a human-action checkpoint and
ask the user to run or authorize the apply step.

## Validation Sign-Off

- [x] All local implementation tasks have automated verification.
- [x] Server mutation is isolated behind an explicit checkpoint.
- [x] Secrets are excluded from generated artifacts.
- [x] `nyquist_compliant: true` set in frontmatter.
