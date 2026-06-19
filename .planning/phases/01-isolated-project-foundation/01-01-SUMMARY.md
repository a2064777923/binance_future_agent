---
phase: 01-isolated-project-foundation
plan: 01
subsystem: project-foundation
tags:
  - scaffold
  - isolation
  - git-hygiene
key-files:
  created:
    - pyproject.toml
    - src/bfa/__init__.py
    - tests/__init__.py
  modified:
    - .gitignore
    - README.md
metrics:
  tests: "python -m unittest discover -s tests"
  test_count: 0
  requirements:
    - ISO-01
    - ISO-02
---

# Summary: Plan 01 - Project Scaffold

## Result

Implemented the independent Python project scaffold for Binance Futures Agent.
The repository now has a `src/bfa` package root, test package, editable
packaging metadata, expanded git hygiene exclusions, and README local
development instructions scoped to `F:\binance_futures_agent`.

## Commits

| Commit | Description |
|--------|-------------|
| `fb472ee` | Scaffold isolated Python project with package metadata, git exclusions, README workflow, and importable package root. |

## Files Changed

| File | Change |
|------|--------|
| `.gitignore` | Added Python, secret, runtime, data, raw export, coverage, egg-info, and editor exclusions. |
| `pyproject.toml` | Added Python 3.11+ setuptools project metadata using `src` package discovery. |
| `README.md` | Added local development workflow and explicit project isolation notes. |
| `src/bfa/__init__.py` | Added importable package root with version metadata. |
| `tests/__init__.py` | Added unittest-discoverable test package. |

## Verification

| Command | Result |
|---------|--------|
| `python -m pip install -e .` | Passed |
| `python -m unittest discover -s tests` | Passed, 0 tests discovered |
| `git check-ignore -- .env` | Passed |
| `git check-ignore -- logs/app.log` | Passed |
| `git check-ignore -- runtime/state.json` | Passed |
| `git check-ignore -- data/local.db` | Passed |
| `git check-ignore -- raw_exports/sample.csv` | Passed |
| `git diff --check` | Passed |

## Deviations

- The initial plan reserved a console-script entry point for `bfa.cli:main`, but
  Plan 04 owns CLI implementation. Declaring that entry point in Plan 01 caused
  an editable-install script generation failure on Windows because `bfa.cli`
  does not exist yet and pip attempted to manage `bfa.exe`. The entry point was
  deferred to Plan 04, preserving the phase boundary.

## Self-Check

PASSED. ISO-01 and ISO-02 are covered: the repo is independently installable,
package imports resolve from `src/bfa`, runtime/secret artifacts are ignored,
and local development instructions avoid `F:\stock`.
