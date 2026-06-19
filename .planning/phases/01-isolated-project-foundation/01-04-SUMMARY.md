---
phase: 01-isolated-project-foundation
plan: 04
subsystem: cli-and-deployment-isolation
tags:
  - cli
  - config-check
  - deployment-isolation
  - secret-scan
key-files:
  created:
    - src/bfa/cli.py
    - tests/test_cli.py
    - docs/deployment_isolation.md
  modified:
    - src/bfa/config.py
    - tests/test_config.py
metrics:
  tests: "python -m unittest discover -s tests"
  test_count: 19
  requirements:
    - ISO-03
    - CFG-01
    - CFG-02
    - CFG-03
requirements-completed:
  - ISO-03
  - CFG-01
  - CFG-02
  - CFG-03
---

# Summary: Plan 04 - Config Check CLI and Deployment Isolation

## Result

Added a secret-safe `config-check` CLI via `python -m bfa.cli`, CLI tests for
exit codes and redaction, and deployment isolation notes for the future server
phase. The final gates now cover installability, unit tests, example config
validation, whitespace hygiene, and secret-pattern scanning.

## Commits

| Commit | Description |
|--------|-------------|
| `5885bac` | Added CLI contract tests for dry-run config, invalid live config, JSON output, and secret absence. |
| `613c6ff` | Implemented `python -m bfa.cli config-check` and restricted diagnostics to known redacted config keys. |
| `7d00b43` | Documented isolated deployment paths, server service name, Phase 1 non-deployment boundary, and final gates. |

## Files Changed

| File | Change |
|------|--------|
| `src/bfa/cli.py` | Added argparse CLI with `config-check` JSON output and exit codes. |
| `tests/test_cli.py` | Added four tests for valid dry-run, invalid live config, redaction, and unrelated-env suppression. |
| `docs/deployment_isolation.md` | Added future deployment path contract and local verification commands. |
| `src/bfa/config.py` | Added optional source config keys and filtered loaded values to the known config contract. |
| `tests/test_config.py` | Added coverage proving unknown environment keys are ignored. |

## Verification

| Command | Result |
|---------|--------|
| `python -m pip install -e .` | Passed |
| `python -m unittest tests.test_cli -v` | Passed, 4 tests |
| `python -m unittest tests.test_config -v` | Passed, 9 tests |
| `python -m unittest discover -s tests` | Passed, 19 tests |
| `python -m bfa.cli config-check --env-file .env.example` | Passed, exited 0 with dry-run JSON |
| `git diff --check` | Passed |
| Secret-pattern scan over tracked and pending non-ignored files | Passed, no findings |

## Deviations

- A console-script entry point was not added. Re-adding `bfa = "bfa.cli:main"`
  caused Windows editable install to fail while replacing `bfa.exe`. The stable
  Phase 1 entry point is `python -m bfa.cli config-check`, which satisfies the
  local validation workflow without breaking `python -m pip install -e .`.
- Initial CLI output included every inherited OS environment key in the redacted
  summary. This was auto-fixed by filtering config loading to the documented
  environment contract before validation output is produced.

## Self-Check

PASSED. ISO-03 is covered by explicit server path, env file, runtime directory,
log directory, and service-name isolation notes. CFG-01 through CFG-03 remain
covered: config values are loadable from env files, runtime modes validate with
structured errors, and CLI diagnostics expose only redacted known config keys.
