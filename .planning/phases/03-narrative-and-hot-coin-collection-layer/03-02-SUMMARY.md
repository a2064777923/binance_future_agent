---
phase: 03-narrative-and-hot-coin-collection-layer
plan: 02
subsystem: narrative-source-adapters
tags:
  - narrative
  - square
  - manual-export
  - rss
key-files:
  created:
    - src/bfa/narrative/adapters.py
    - src/bfa/narrative/manual.py
    - src/bfa/narrative/rss.py
    - tests/fixtures/narrative/rss_feed.xml
    - tests/fixtures/narrative/atom_feed.xml
    - tests/test_narrative_manual.py
    - tests/test_narrative_rss.py
metrics:
  tests: "python -m unittest tests.test_narrative_manual tests.test_narrative_rss -v"
  test_count: 7
  requirements:
    - NAR-01
    - NAR-02
    - NAR-03
requirements-completed:
  - NAR-01
  - NAR-02
  - NAR-03
---

# Summary: Plan 02 - Manual/Export And RSS Source Adapters

## Result

Implemented the first narrative source adapters. Binance Square-style content
can now be ingested through manual/export files without cookies or hardcoded
secrets, and RSS/Atom feeds can be parsed through fixture-tested XML helpers
with injectable fetchers.

## Files Changed

| File | Change |
|------|--------|
| `src/bfa/narrative/adapters.py` | Added `NarrativeCollector` protocol. |
| `src/bfa/narrative/manual.py` | Added `.json`, `.jsonl`, and `.txt` manual/export collector. |
| `src/bfa/narrative/rss.py` | Added RSS/Atom parser and feed collector with injectable fetcher. |
| `tests/fixtures/narrative/rss_feed.xml` | Added RSS fixture. |
| `tests/fixtures/narrative/atom_feed.xml` | Added Atom fixture. |
| `tests/test_narrative_manual.py` | Covered JSON, JSONL, text, missing directory, and malformed export behavior. |
| `tests/test_narrative_rss.py` | Covered RSS, Atom, empty URL list, and fake fetcher behavior. |

## Verification

| Command | Result |
|---------|--------|
| `python -m unittest tests.test_narrative_manual tests.test_narrative_rss -v` | Passed, 7 tests |
| `git diff --check` | Passed |

## Deviations

None.

## Issues Encountered

None.

## Self-Check

PASSED. Plan 03-02 satisfies the source-adapter layer: Binance Square has a
manual/export path, RSS/Atom fallback ingestion works offline, and no live X,
Telegram, cookie, token, OpenAI, Binance private API, order, SQLite, deployment,
or stock-repository behavior was added.

