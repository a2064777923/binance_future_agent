---
phase: 03-narrative-and-hot-coin-collection-layer
plan: 01
subsystem: narrative-models-symbols
tags:
  - narrative
  - normalization
  - symbols
key-files:
  created:
    - src/bfa/narrative/__init__.py
    - src/bfa/narrative/models.py
    - src/bfa/narrative/symbols.py
    - tests/fixtures/narrative/manual_records.json
    - tests/test_narrative_models.py
    - tests/test_narrative_symbols.py
metrics:
  tests: "python -m unittest tests.test_narrative_models tests.test_narrative_symbols -v"
  test_count: 8
  requirements:
    - NAR-03
requirements-completed:
  - NAR-03
---

# Summary: Plan 01 - Narrative Models And Symbol Extraction

## Result

Created the `bfa.narrative` package foundation with a normalized narrative
record dataclass and conservative futures-aware symbol extraction. Records now
preserve source, source ID, author, symbols, text, URL, timestamps,
engagement, raw context, and quality flags for later audit.

## Files Changed

| File | Change |
|------|--------|
| `src/bfa/narrative/__init__.py` | Exported narrative model and symbol helpers. |
| `src/bfa/narrative/models.py` | Added `NormalizedNarrativeRecord` and `normalize_narrative_record`. |
| `src/bfa/narrative/symbols.py` | Added explicit pair, slash/dash pair, cashtag, and allowlisted bare-base extraction. |
| `tests/fixtures/narrative/manual_records.json` | Added representative manual narrative records. |
| `tests/test_narrative_models.py` | Covered record serialization, normalization, optional fields, and validation. |
| `tests/test_narrative_symbols.py` | Covered explicit symbols, allowlisted bases, duplicates, and no-symbol flags. |

## Verification

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_narrative_models tests.test_narrative_symbols -v` | Passed, 8 tests |
| `git diff --check` | Passed |

## Deviations

None.

## Issues Encountered

Initial extraction flagged ordinary uppercase words after already mapping
explicit symbols. The extractor was tightened so bare uppercase bases only map
through a known-symbol allowlist, while no-allowlist bare tokens are flagged as
ambiguous rather than traded.

## Self-Check

PASSED. Plan 03-01 satisfies the NAR-03 foundation and respects Phase 3
boundaries: no OpenAI calls, Binance private APIs, account/order endpoints,
SQLite storage, deployment actions, or stock-repository access were added.

