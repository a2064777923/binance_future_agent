# Phase 3: Narrative And Hot-Coin Collection Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-19T12:10:00Z
**Phase:** 03-narrative-and-hot-coin-collection-layer
**Areas discussed:** Square access path, fallback source breadth, screenshot strategy interpretation, narrative normalization, deduplication boundary, secret/network safety

---

## Square Access Path

| Option | Description | Selected |
|--------|-------------|----------|
| Official read API first | Use a supported Square read endpoint if research finds one. | |
| Replaceable adapter with manual/export first | Treat Square access as uncertain and build manual/export ingestion as the reliable baseline. | ✓ |
| Browser automation first | Automate the web UI before proving manual/export value. | |

**User's choice:** Auto-selected based on earlier preference for many sources plus safety.
**Notes:** The project should not pretend there is a stable official Square read API. Research can add better adapters later.

---

## Fallback Source Breadth

| Option | Description | Selected |
|--------|-------------|----------|
| Square only | Keep Phase 3 narrowly focused on Binance Square. | |
| Square/manual/export plus RSS/news | Build low-secret fallback sources early. | ✓ |
| Full X/Telegram live integrations now | Require social tokens and live API access in Phase 3. | |

**User's choice:** Auto-selected from "希望越多數據源和方式去采集越好" while keeping Phase 3 controllable.
**Notes:** X/Telegram should have adapter/config seams, but live token use can wait.

---

## Screenshot Strategy Interpretation

| Option | Description | Selected |
|--------|-------------|----------|
| Copy the poster as a strategy | Hardcode one public trader's behavior. | |
| Use as qualitative signal design | Extract observable ideas: hot tickers, AI-agent automation, VPS/local bot, engagement, iterative tuning. | ✓ |
| Ignore the screenshot | Treat it as non-actionable. | |

**User's choice:** Auto-selected because the screenshot is incomplete but directionally useful.
**Notes:** "马拉龙巴子" should not become a trusted oracle; capture source/author for later evaluation.

---

## Narrative Normalization

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal symbol-only records | Store only extracted symbols. | |
| Auditable narrative records | Store source, author, text, symbols, URL, timestamps, engagement, raw, and quality flags. | ✓ |
| Strategy-ready scored records | Score heat and reliability immediately. | |

**User's choice:** Auto-selected to support later replay and AI auditability.
**Notes:** Scoring belongs to Phase 5.

---

## Deduplication Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| No deduplication | Let downstream phases handle duplicates. | |
| Source ID plus deterministic fingerprint | Collapse repeats while preserving audit fields. | ✓ |
| Fuzzy semantic clustering | Use heavier NLP/AI for duplicate detection now. | |

**User's choice:** Auto-selected for deterministic behavior and testability.
**Notes:** AI/semantic clustering can be revisited after the event store exists.

---

## Secret And Network Safety

| Option | Description | Selected |
|--------|-------------|----------|
| Live social APIs in unit tests | Exercise real sources during automated tests. | |
| Static fixtures and injected adapters | Unit tests stay offline and secret-free. | ✓ |
| Read local cookies/API key files during planning | Use provided local secrets to speed setup. | |

**User's choice:** Auto-selected from project secret hygiene and isolation constraints.
**Notes:** Do not read `F:\币安API密鈅.txt` or source cookies/tokens in Phase 3 tests/planning.

---

## the agent's Discretion

- Choose standard-library-first parsers unless research proves a dependency is worthwhile.
- Choose exact module names, but keep narrative source code isolated under `src/bfa/narrative/`.
- Keep browser automation optional and replaceable.

## Deferred Ideas

- Narrative heat scoring and source reliability weighting: Phase 5.
- OpenAI prompt/decision layer: Phase 6.
- SQLite durable store/replay: Phase 4.
- Live X/Telegram token integrations: after explicit credentials/access are available.
