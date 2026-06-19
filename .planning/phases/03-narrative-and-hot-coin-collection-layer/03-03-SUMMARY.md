---
phase: 03-narrative-and-hot-coin-collection-layer
plan: 03
subsystem: narrative-dedup-cli
tags:
  - narrative
  - deduplication
  - jsonl
  - cli
key-files:
  created:
    - src/bfa/narrative/dedup.py
    - src/bfa/narrative/jsonl_writer.py
    - src/bfa/narrative/collector.py
    - tests/test_narrative_dedup.py
    - tests/test_narrative_collector.py
  modified:
    - src/bfa/narrative/__init__.py
    - src/bfa/config.py
    - src/bfa/cli.py
    - tests/test_config.py
    - tests/test_cli.py
metrics:
  tests: "python -m unittest discover -s tests"
  test_count: 76
  requirements:
    - NAR-01
    - NAR-02
    - NAR-03
    - NAR-04
requirements-completed:
  - NAR-01
  - NAR-02
  - NAR-03
  - NAR-04
---

# Summary: Plan 03 - Narrative Deduplication, JSONL, And CLI

## Result

Finished the Phase 3 narrative collection layer. Source adapter records can be
combined, deduplicated by source ID or deterministic fingerprint, written as
JSONL, and exercised through `python -m bfa.cli narrative collect`.

## Files Changed

| File | Change |
|------|--------|
| `src/bfa/narrative/dedup.py` | Added stable source-ID and fingerprint deduplication. |
| `src/bfa/narrative/jsonl_writer.py` | Added normalized narrative JSONL writer. |
| `src/bfa/narrative/collector.py` | Added composite `NarrativeCollectionRunner`. |
| `src/bfa/narrative/__init__.py` | Exported runner and dedup helpers. |
| `src/bfa/config.py` | Added `rss_feed_urls` and `telegram_channels` list helpers. |
| `src/bfa/cli.py` | Added `narrative collect` smoke command with injectable runner. |
| `tests/test_narrative_dedup.py` | Covered source-ID and fingerprint deduplication. |
| `tests/test_narrative_collector.py` | Covered runner composition and JSONL writing. |
| `tests/test_config.py` | Covered narrative source list parsing. |
| `tests/test_cli.py` | Covered fake-runner narrative CLI output and secret-safe summary. |

## Verification

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_narrative_dedup tests.test_narrative_collector tests.test_config tests.test_cli -v` | Passed, 25 tests |
| `python -m unittest discover -s tests` | Passed, 76 tests |
| `git diff --check` | Passed |
| `python -m bfa.cli narrative collect --env-file .env.example --output <temp>` | Passed; wrote an empty JSONL file without live feeds or secrets |
| `git grep -n "F:\\\\stock" -- . ":(exclude).planning/**"` | Only matched `AGENTS.md` and `README.md` isolation guidance |
| `git grep -nE "openai|OPENAI|account|order|listenKey|userData|sqlite|sqlite3|systemctl|ssh|scp" -- src tests` | Only matched existing config/test placeholders, Phase 2 private-stream rejection guards, and long/short market payload fields |
| `git grep -nE "SQUARE_COOKIE_FILE|X_BEARER_TOKEN|TELEGRAM_BOT_TOKEN|API_KEY|API_SECRET|SECRET|TOKEN|COOKIE" -- src tests .env.example` | Only matched documented placeholders, synthetic redaction/config tests, and symbol extractor token variable names; no committed secret values |

## Deviations

None.

## Issues Encountered

The config list helper originally only supported uppercase symbol lists. It was
split so market symbols remain uppercase while RSS URLs and Telegram channels
preserve caller-provided casing.

## Self-Check

PASSED. NAR-01 through NAR-04 are covered: Square has a manual/export path,
RSS/Atom fallback ingestion exists, records normalize to the shared narrative
shape, duplicates collapse before scoring, JSONL evidence can be written, and
CLI smoke tests are offline and secret-safe.

