"""One-cycle automated trading runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Any

from bfa.ai.client import OpenAIAPIError
from bfa.ai.decision import run_ai_decision
from bfa.ai.journal import AiDecisionJournal
from bfa.ai.providers import ai_source, build_ai_client
from bfa.ai.schema import RiskLimits, context_from_candidate
from bfa.config import AppConfig, RuntimeMode, market_symbols, rss_feed_urls, validate_config
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.execution.executor import ExecutionEngine
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import RiskState
from bfa.execution.sizing import compute_position_sizing, dynamic_sizing_enabled, sizing_input_from_config
from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.market.collector import MarketDataCollector
from bfa.narrative.collector import NarrativeCollectionRunner
from bfa.narrative.manual import ManualExportCollector
from bfa.narrative.market_heat import MarketHeatNarrativeCollector
from bfa.narrative.rss import RssFeedCollector
from bfa.strategy.candidates import StrategyConfig, generate_candidates
from bfa.strategy.store import persist_candidates


@dataclass(frozen=True)
class AgentRunResult:
    status: str
    mode: str
    started_at: str
    market_snapshot_count: int = 0
    narrative_record_count: int = 0
    candidate_count: int = 0
    rejected_count: int = 0
    selected_symbol: str | None = None
    ai_accepted: bool = False
    execution_status: str | None = None
    submitted: bool = False
    validation_errors: list[str] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)
    persisted: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {
            "submitted",
            "dry_run",
            "test_order_checked",
            "no_candidate",
            "ai_pass",
            "ai_rejected",
            "ai_error",
            "openai_backoff",
            "rejected",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "started_at": self.started_at,
            "market_snapshot_count": self.market_snapshot_count,
            "narrative_record_count": self.narrative_record_count,
            "candidate_count": self.candidate_count,
            "rejected_count": self.rejected_count,
            "selected_symbol": self.selected_symbol,
            "ai_accepted": self.ai_accepted,
            "execution_status": self.execution_status,
            "submitted": self.submitted,
            "validation_errors": list(self.validation_errors),
            "risk_reasons": list(self.risk_reasons),
            "persisted": dict(self.persisted),
        }


def run_agent_once(
    *,
    config: AppConfig,
    db_path: str | None = None,
    journal_path: str | None = None,
    top_n: int = 3,
    market_client=None,
    collector=None,
    narrative_runner=None,
    ai_client=None,
    signed_client=None,
) -> AgentRunResult:
    started_at = _now_iso()
    validation = validate_config(config)
    if not validation.valid:
        return AgentRunResult(
            status="invalid_config",
            mode=config.get("BFA_MODE"),
            started_at=started_at,
            validation_errors=list(validation.errors),
        )
    if not _truthy(config.get("BFA_OPENAI_ENABLED")):
        return AgentRunResult(
            status="openai_disabled",
            mode=config.get("BFA_MODE"),
            started_at=started_at,
            validation_errors=["BFA_OPENAI_ENABLED must be true for automated trading"],
        )

    mode = RuntimeMode(config.get("BFA_MODE"))
    backoff = _openai_backoff(config)
    if backoff.active:
        return AgentRunResult(
            status="openai_backoff",
            mode=mode.value,
            started_at=started_at,
            validation_errors=[f"openai_retry_after:{backoff.retry_after_iso}"],
        )

    market = market_client or BinanceFuturesRestClient(base_url=config.get("BINANCE_FUTURES_BASE_URL"))
    collector = collector or MarketDataCollector(
        client=market,
        symbols=market_symbols(config),
        received_at=started_at,
    )
    narrative_runner = narrative_runner or _build_narrative_runner(config, collected_at=started_at)
    ai_client = ai_client or build_ai_client(config)
    signed_client = signed_client or _build_signed_client(config, mode)

    connection = connect(db_path or config.get("BFA_DB_PATH"))
    try:
        store = EventStore(connection)
        market_snapshots = collector.collect_rest_snapshots()
        market_event_ids = [store.insert_market_snapshot(snapshot) for snapshot in market_snapshots]
        narrative_records = narrative_runner.collect()
        if not narrative_records and _truthy(config.get("BFA_MARKET_HEAT_NARRATIVE_ENABLED")):
            narrative_records = _collect_market_heat_narratives(config, market_snapshots, started_at)
        narrative_event_ids = [store.insert_narrative(record) for record in narrative_records]

        replay_packet = {
            "start": started_at,
            "end": started_at,
            "symbol": None,
            "event_count": len(market_event_ids) + len(narrative_event_ids),
            "symbols": market_symbols(config),
            "records": [
                *_market_records(market_event_ids, market_snapshots),
                *_narrative_records(narrative_event_ids, narrative_records),
            ],
        }
        base_sizing = compute_position_sizing(
            sizing_input_from_config(config),
            enabled=dynamic_sizing_enabled(config),
        )
        candidates = generate_candidates(
            replay_packet,
            StrategyConfig(
                allowed_symbols=market_symbols(config),
                generated_at=started_at,
                top_n=top_n,
                max_position_notional_usdt=base_sizing.max_position_notional_usdt,
            ),
        )
        persisted_candidate_count = len(persist_candidates(store, candidates.candidates))
        if not candidates.candidates:
            return AgentRunResult(
                status="no_candidate",
                mode=mode.value,
                started_at=started_at,
                market_snapshot_count=len(market_snapshots),
                narrative_record_count=len(narrative_records),
                candidate_count=0,
                rejected_count=len(candidates.rejected),
                persisted={"candidates": persisted_candidate_count},
            )

        candidate = candidates.candidates[0]
        candidate_sizing = compute_position_sizing(
            sizing_input_from_config(config, candidate=candidate.to_dict()),
            enabled=dynamic_sizing_enabled(config),
        )
        try:
            ai_run = run_ai_decision(
                client=ai_client,
                context=context_from_candidate(
                    candidate,
                    risk_limits=RiskLimits.from_config(config, sizing_result=candidate_sizing),
                    decided_at=started_at,
                ),
                journal=AiDecisionJournal(journal_path) if journal_path else None,
                store=store,
                source=ai_source(config),
            )
        except Exception as exc:
            _record_openai_backoff(config, exc)
            return AgentRunResult(
                status="ai_error",
                mode=mode.value,
                started_at=started_at,
                market_snapshot_count=len(market_snapshots),
                narrative_record_count=len(narrative_records),
                candidate_count=len(candidates.candidates),
                rejected_count=len(candidates.rejected),
                selected_symbol=candidate.symbol,
                validation_errors=[_safe_ai_error(exc)],
                persisted={"candidates": persisted_candidate_count},
            )
        _clear_openai_backoff(config)
        if not ai_run.validation.accepted:
            status = "ai_pass" if ai_run.validation.decision and ai_run.validation.decision.decision == "pass" else "ai_rejected"
            return AgentRunResult(
                status=status,
                mode=mode.value,
                started_at=started_at,
                market_snapshot_count=len(market_snapshots),
                narrative_record_count=len(narrative_records),
                candidate_count=len(candidates.candidates),
                rejected_count=len(candidates.rejected),
                selected_symbol=candidate.symbol,
                ai_accepted=False,
                validation_errors=list(ai_run.validation.validation_errors),
                persisted={"candidates": persisted_candidate_count, "ai_decisions": ai_run.persisted},
            )

        exchange_info = market.exchange_info().payload
        filters = SymbolExecutionFilters.from_exchange_info(exchange_info, candidate.symbol)
        risk_state = _risk_state_from_exchange(signed_client) if mode is RuntimeMode.LIVE else RiskState()
        if risk_state is None:
            return AgentRunResult(
                status="position_risk_failed",
                mode=mode.value,
                started_at=started_at,
                market_snapshot_count=len(market_snapshots),
                narrative_record_count=len(narrative_records),
                candidate_count=len(candidates.candidates),
                rejected_count=len(candidates.rejected),
                selected_symbol=candidate.symbol,
                ai_accepted=True,
                validation_errors=["unable to read live position risk"],
                persisted={"candidates": persisted_candidate_count, "ai_decisions": ai_run.persisted},
            )

        execution = ExecutionEngine(
            config=config,
            signed_client=signed_client,
            store=store,
            risk_limits=RiskLimits.from_config(config, sizing_result=candidate_sizing),
        ).run(
            symbol=candidate.symbol,
            validation=ai_run.validation,
            decided_at=started_at,
            risk_state=risk_state,
            filters=filters,
            now=started_at,
        )
        return AgentRunResult(
            status=execution.status,
            mode=mode.value,
            started_at=started_at,
            market_snapshot_count=len(market_snapshots),
            narrative_record_count=len(narrative_records),
            candidate_count=len(candidates.candidates),
            rejected_count=len(candidates.rejected),
            selected_symbol=candidate.symbol,
            ai_accepted=True,
            execution_status=execution.status,
            submitted=execution.submitted,
            risk_reasons=list(execution.risk.reason_codes),
            persisted={
                "candidates": persisted_candidate_count,
                "ai_decisions": ai_run.persisted,
                **execution.persisted,
            },
        )
    finally:
        connection.close()


def _build_narrative_runner(config: AppConfig, *, collected_at: str) -> NarrativeCollectionRunner:
    symbols = market_symbols(config)
    collectors = [
        ManualExportCollector(
            config.get("SQUARE_EXPORT_DIR"),
            default_source="binance_square",
            known_symbols=symbols,
            collected_at=collected_at,
            tolerant=True,
        )
    ]
    feeds = rss_feed_urls(config)
    if feeds:
        collectors.append(RssFeedCollector(feeds, known_symbols=symbols, collected_at=collected_at))
    return NarrativeCollectionRunner(collectors)


def _collect_market_heat_narratives(config: AppConfig, market_snapshots, collected_at: str):
    return MarketHeatNarrativeCollector(
        market_snapshots,
        known_symbols=market_symbols(config),
        collected_at=collected_at,
        min_quote_volume=float(config.get("BFA_MARKET_HEAT_MIN_QUOTE_VOLUME_USDT")),
        min_price_change_percent=float(config.get("BFA_MARKET_HEAT_MIN_PRICE_CHANGE_PERCENT")),
        min_taker_buy_sell_ratio=float(config.get("BFA_MARKET_HEAT_MIN_TAKER_BUY_SELL_RATIO")),
        min_open_interest_value=float(config.get("BFA_MARKET_HEAT_MIN_OPEN_INTEREST_VALUE_USDT")),
        max_kline_range_percent=float(config.get("BFA_MARKET_HEAT_MAX_KLINE_RANGE_PERCENT")),
        max_records=int(config.get("BFA_MARKET_HEAT_MAX_RECORDS")),
    ).collect()


def _build_signed_client(config: AppConfig, mode: RuntimeMode):
    if mode not in {RuntimeMode.TESTNET, RuntimeMode.LIVE}:
        return None
    return BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )


def _risk_state_from_exchange(signed_client) -> RiskState | None:
    if signed_client is None:
        return None
    try:
        positions = signed_client.position_risk()
    except Exception:
        return None
    active_positions = 0
    active_exposures: list[dict[str, str]] = []
    for position in positions:
        try:
            amount = abs(float(position.get("positionAmt", 0)))
        except (TypeError, ValueError):
            amount = 0.0
        if amount > 0:
            active_positions += 1
            direction = _position_direction(position)
            active_exposures.append(
                {
                    "symbol": str(position.get("symbol", "")).upper(),
                    "direction": direction,
                }
            )
    return RiskState(active_positions=active_positions, active_exposures=active_exposures)


def _position_direction(position: dict[str, Any]) -> str:
    side = str(position.get("positionSide") or "").upper()
    if side in {"LONG", "SHORT"}:
        return side
    try:
        amount = float(position.get("positionAmt", 0))
    except (TypeError, ValueError):
        amount = 0.0
    return "LONG" if amount > 0 else "SHORT"


def _market_records(event_ids, snapshots) -> list[dict[str, Any]]:
    return [
        {
            "id": event_id,
            "event_type": "market_snapshot",
            "occurred_at": str(snapshot.event_time or snapshot.received_at),
            "source": snapshot.source,
            "symbol": snapshot.symbol,
            "ref_id": f"{snapshot.event_type}:{snapshot.symbol}:{snapshot.event_time}",
            "payload": snapshot.to_dict(),
        }
        for event_id, snapshot in zip(event_ids, snapshots, strict=False)
    ]


def _narrative_records(event_ids, records) -> list[dict[str, Any]]:
    return [
        {
            "id": event_id,
            "event_type": "narrative",
            "occurred_at": record.published_at or record.collected_at,
            "source": record.source,
            "symbol": record.symbol_mentions[0] if record.symbol_mentions else None,
            "ref_id": record.source_id,
            "payload": record.to_dict(),
        }
        for event_id, record in zip(event_ids, records, strict=False)
    ]


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_ai_error(exc: Exception) -> str:
    if isinstance(exc, OpenAIAPIError):
        status = "none" if exc.status_code is None else str(exc.status_code)
        return f"openai_error:{status}:{exc.message}"
    return f"openai_error:{exc.__class__.__name__}"


@dataclass(frozen=True)
class _OpenAiBackoff:
    active: bool
    retry_after_iso: str | None = None


def _openai_backoff(config: AppConfig) -> _OpenAiBackoff:
    path = _openai_backoff_path(config)
    if not path.exists():
        return _OpenAiBackoff(False)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        retry_after_epoch = float(payload.get("retry_after_epoch", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _OpenAiBackoff(False)
    if time.time() >= retry_after_epoch:
        return _OpenAiBackoff(False)
    return _OpenAiBackoff(True, _epoch_to_iso(retry_after_epoch))


def _record_openai_backoff(config: AppConfig, exc: Exception) -> None:
    retry_after = time.time() + float(config.get("OPENAI_RETRY_AFTER_SECONDS"))
    path = _openai_backoff_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retry_after_epoch": retry_after,
        "retry_after": _epoch_to_iso(retry_after),
        "reason": _safe_ai_error(exc),
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _clear_openai_backoff(config: AppConfig) -> None:
    path = _openai_backoff_path(config)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _openai_backoff_path(config: AppConfig) -> Path:
    return Path(config.get("BFA_RUNTIME_DIR")) / "openai_backoff.json"


def _epoch_to_iso(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
