"""One-cycle automated trading runner."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Any

from bfa.ai.client import OpenAIAPIError
from bfa.ai.decision import AiDecisionRun
from bfa.ai.decision import run_ai_decision
from bfa.ai.journal import AiDecisionJournal
from bfa.ai.schema import RiskLimits, context_from_candidate
from bfa.ai.providers import ai_source, build_ai_client
from bfa.backtest.matrix import HotUniverseConfig, select_hot_usdt_symbols
from bfa.config import AppConfig, RuntimeMode, market_symbols, rss_feed_urls, validate_config
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.execution.executor import ExecutionEngine
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import RiskState
from bfa.execution.sizing import (
    apply_adaptive_sizing_governor,
    compute_position_sizing,
    dynamic_sizing_enabled,
    sizing_input_from_config,
)
from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.market.collector import MarketDataCollector
from bfa.narrative.collector import NarrativeCollectionRunner
from bfa.narrative.manual import ManualExportCollector
from bfa.narrative.market_heat import MarketHeatNarrativeCollector
from bfa.narrative.rss import RssFeedCollector
from bfa.ops.position_adjustment import build_position_adjustment_plan_report, execute_position_adjustment_plan_report
from bfa.strategy.candidates import StrategyConfig, generate_candidates
from bfa.strategy.paper_guard import build_forward_paper_guard, guard_config_from_app, merge_guard_profile
from bfa.strategy.setup import build_trade_setup, persist_trade_setup
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
    scan_symbols: list[str] = field(default_factory=list)
    selected_symbol: str | None = None
    evaluated_symbols: list[str] = field(default_factory=list)
    ai_accepted: bool = False
    execution_status: str | None = None
    submitted: bool = False
    validation_errors: list[str] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)
    persisted: dict[str, int] = field(default_factory=dict)
    position_review: dict[str, Any] | None = None
    position_adjustment_plan: dict[str, Any] | None = None
    paper_guard: dict[str, Any] | None = None
    source_health: dict[str, Any] = field(default_factory=dict)
    candidate_evaluations: list[dict[str, Any]] = field(default_factory=list)

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
            "quant_pass",
            "entry_capacity_blocked",
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
            "scan_symbols": list(self.scan_symbols),
            "selected_symbol": self.selected_symbol,
            "evaluated_symbols": list(self.evaluated_symbols),
            "ai_accepted": self.ai_accepted,
            "execution_status": self.execution_status,
            "submitted": self.submitted,
            "validation_errors": list(self.validation_errors),
            "risk_reasons": list(self.risk_reasons),
            "persisted": dict(self.persisted),
            "position_review": self.position_review,
            "position_adjustment_plan": self.position_adjustment_plan,
            "paper_guard": self.paper_guard,
            "source_health": dict(self.source_health),
            "candidate_evaluations": [dict(item) for item in self.candidate_evaluations],
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
    ai_enabled = _truthy(config.get("BFA_OPENAI_ENABLED"))
    quant_fallback_enabled = _ai_fallback_to_quant_enabled(config)
    if not ai_enabled and not quant_fallback_enabled:
        return AgentRunResult(
            status="openai_disabled",
            mode=config.get("BFA_MODE"),
            started_at=started_at,
            validation_errors=[
                "BFA_OPENAI_ENABLED must be true for automated trading unless BFA_AI_FALLBACK_TO_QUANT_ENABLED=true"
            ],
        )

    mode = RuntimeMode(config.get("BFA_MODE"))
    backoff = _openai_backoff(config)
    if backoff.active and not quant_fallback_enabled:
        return AgentRunResult(
            status="openai_backoff",
            mode=mode.value,
            started_at=started_at,
            validation_errors=[f"openai_retry_after:{backoff.retry_after_iso}"],
            source_health=_pre_collection_source_health(config, reason="openai_backoff"),
        )

    signed_client = signed_client or _build_signed_client(config, mode)
    preflight_risk_state = (
        _risk_state_from_exchange(
            signed_client,
            manual_symbols=set(config.get_list("BFA_MANUAL_POSITION_SYMBOLS")),
        )
        if mode is RuntimeMode.LIVE
        else None
    )
    if mode is RuntimeMode.LIVE and preflight_risk_state is None:
        return AgentRunResult(
            status="position_risk_failed",
            mode=mode.value,
            started_at=started_at,
            validation_errors=["unable to read live position risk"],
            source_health=_pre_collection_source_health(config, reason="position_risk_failed"),
        )
    market = market_client or BinanceFuturesRestClient(base_url=config.get("BINANCE_FUTURES_BASE_URL"))
    position_adjustment_plan = (
        _live_position_adjustment_plan(config, db_path=db_path, signed_client=signed_client, market_client=market)
        if mode is RuntimeMode.LIVE and preflight_risk_state is not None
        else None
    )
    connection = None
    try:
        store = None
        position_lifecycle_event_id = None
        position_auto_management_execution = None
        if mode is RuntimeMode.LIVE:
            connection = connect(db_path or config.get("BFA_DB_PATH"))
            store = EventStore(connection)
            position_auto_management_execution = _execute_live_position_auto_management(
                config,
                db_path=db_path,
                signed_client=signed_client,
                started_at=started_at,
                adjustment_plan=position_adjustment_plan,
            )
            position_lifecycle_event_id = _persist_position_lifecycle(
                store,
                config=config,
                started_at=started_at,
                adjustment_plan=position_adjustment_plan,
                auto_management_execution=position_auto_management_execution,
            )

        preflight_reasons = _live_entry_capacity_blockers(config, preflight_risk_state)
        if preflight_reasons:
            return AgentRunResult(
                status="entry_capacity_blocked",
                mode=mode.value,
                started_at=started_at,
                risk_reasons=preflight_reasons,
                persisted=_position_lifecycle_persisted(position_lifecycle_event_id),
                position_review=_position_review_summary(position_adjustment_plan),
                position_adjustment_plan=_position_adjustment_summary(position_adjustment_plan),
                source_health=_pre_collection_source_health(config, reason="entry_capacity_blocked"),
            )

        scan_symbols, source_health = _agent_scan_symbols_with_health(config, market)
        collector = collector or MarketDataCollector(
            client=market,
            symbols=scan_symbols,
            max_symbols=max(len(scan_symbols), 1),
            received_at=started_at,
        )
        narrative_runner = narrative_runner or _build_narrative_runner(
            config,
            collected_at=started_at,
            known_symbols=scan_symbols,
        )
        ai_client = ai_client or (build_ai_client(config) if ai_enabled else None)

        if store is None:
            connection = connect(db_path or config.get("BFA_DB_PATH"))
            store = EventStore(connection)
        paper_guard = build_forward_paper_guard(connection, guard_config_from_app(config))
        market_snapshots = collector.collect_rest_snapshots()
        market_event_ids = [store.insert_market_snapshot(snapshot) for snapshot in market_snapshots]
        narrative_records = narrative_runner.collect()
        market_heat_records = []
        market_heat_status = "not_needed" if narrative_records else "disabled"
        if not narrative_records and _truthy(config.get("BFA_MARKET_HEAT_NARRATIVE_ENABLED")):
            market_heat_records = _collect_market_heat_narratives(
                config,
                market_snapshots,
                started_at,
                known_symbols=scan_symbols,
            )
            narrative_records = market_heat_records
            market_heat_status = "used" if market_heat_records else "empty"
        narrative_event_ids = [store.insert_narrative(record) for record in narrative_records]
        source_health = _augment_live_source_health(
            config,
            source_health,
            market_snapshots=market_snapshots,
            narrative_records=narrative_records,
            market_heat_records=market_heat_records,
            market_heat_status=market_heat_status,
            paper_guard=paper_guard,
        )

        replay_packet = {
            "start": started_at,
            "end": started_at,
            "symbol": None,
            "event_count": len(market_event_ids) + len(narrative_event_ids),
            "symbols": scan_symbols,
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
                allowed_symbols=scan_symbols,
                generated_at=started_at,
                top_n=top_n,
                max_position_notional_usdt=base_sizing.max_position_notional_usdt,
                paper_guard=paper_guard,
                spike_reversal_enabled=_truthy(config.get("BFA_SPIKE_REVERSAL_SIGNAL_ENABLED")),
                spike_min_wick_percent=float(config.get("BFA_SPIKE_REVERSAL_MIN_WICK_PERCENT")),
                spike_min_wick_to_body_ratio=float(config.get("BFA_SPIKE_REVERSAL_MIN_WICK_TO_BODY_RATIO")),
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
                scan_symbols=scan_symbols,
                position_review=_position_review_summary(position_adjustment_plan),
                position_adjustment_plan=_position_adjustment_summary(position_adjustment_plan),
                paper_guard=paper_guard.to_dict(),
                source_health=source_health,
                persisted={
                    **_position_lifecycle_persisted(position_lifecycle_event_id),
                    "candidates": persisted_candidate_count,
                },
            )

        exchange_info = market.exchange_info().payload
        risk_state = preflight_risk_state if mode is RuntimeMode.LIVE else RiskState()
        if risk_state is None:
            return AgentRunResult(
                status="position_risk_failed",
                mode=mode.value,
                started_at=started_at,
                market_snapshot_count=len(market_snapshots),
                narrative_record_count=len(narrative_records),
                candidate_count=len(candidates.candidates),
                rejected_count=len(candidates.rejected),
                scan_symbols=scan_symbols,
                ai_accepted=True,
                validation_errors=["unable to read live position risk"],
                position_review=_position_review_summary(position_adjustment_plan),
                position_adjustment_plan=_position_adjustment_summary(position_adjustment_plan),
                paper_guard=paper_guard.to_dict(),
                source_health=source_health,
                persisted={
                    **_position_lifecycle_persisted(position_lifecycle_event_id),
                    "candidates": persisted_candidate_count,
                },
            )

        return _evaluate_candidate_queue(
            config=config,
            mode=mode,
            candidates=candidates.candidates,
            exchange_info=exchange_info,
            ai_client=ai_client,
            ai_enabled=ai_enabled and not backoff.active,
            journal_path=journal_path,
            store=store,
            signed_client=signed_client,
            risk_state=risk_state,
            started_at=started_at,
            market_snapshot_count=len(market_snapshots),
            narrative_record_count=len(narrative_records),
            candidate_count=len(candidates.candidates),
            rejected_count=len(candidates.rejected),
            scan_symbols=scan_symbols,
            persisted_candidate_count=persisted_candidate_count,
            position_lifecycle_event_id=position_lifecycle_event_id,
            position_adjustment_plan=position_adjustment_plan,
            paper_guard=paper_guard,
            source_health=source_health,
        )
    finally:
        if connection is not None:
            connection.close()


def _agent_scan_symbols(config: AppConfig, market_client) -> list[str]:
    symbols, _health = _agent_scan_symbols_with_health(config, market_client)
    return symbols


def _agent_scan_symbols_with_health(config: AppConfig, market_client) -> tuple[list[str], dict[str, Any]]:
    excluded = set(config.get_list("BFA_MANUAL_POSITION_SYMBOLS"))
    fallback_source = market_symbols(config)
    fallback = _without_symbols(fallback_source, excluded)
    filters = {
        "top_n": int(config.get("BFA_LIVE_AUTO_HOT_TOP_N")),
        "min_quote_volume_usdt": float(config.get("BFA_LIVE_AUTO_HOT_MIN_QUOTE_VOLUME_USDT")),
        "min_abs_price_change_percent": float(config.get("BFA_LIVE_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT")),
    }
    if not _truthy(config.get("BFA_LIVE_AUTO_HOT_SYMBOLS")):
        return fallback, _live_source_health_base(
            config,
            mode="config_fallback",
            status="used" if fallback else "empty",
            selected_symbols=fallback,
            filters=filters,
            fallback_symbols=fallback,
            manual_excluded_symbols=_manual_excluded_symbols(fallback_source, excluded),
            ticker_status="not_polled",
        )
    try:
        ticker_response = market_client.ticker_24hr()
        ticker_payload = ticker_response.payload if isinstance(ticker_response.payload, list) else []
        eligible_ticker_payload = [
            item
            for item in ticker_payload
            if isinstance(item, dict) and str(item.get("symbol", "")).upper() not in excluded
        ]
        hot_rows = select_hot_usdt_symbols(
            eligible_ticker_payload,
            HotUniverseConfig(
                top_n=filters["top_n"],
                min_quote_volume_usdt=filters["min_quote_volume_usdt"],
                min_abs_price_change_percent=filters["min_abs_price_change_percent"],
            ),
        )
    except Exception as exc:
        return fallback, _live_source_health_base(
            config,
            mode="auto_hot_fallback",
            status="fallback" if fallback else "empty",
            selected_symbols=fallback,
            filters=filters,
            fallback_symbols=fallback,
            manual_excluded_symbols=_manual_excluded_symbols(fallback_source, excluded),
            fallback_reason="ticker_error",
            ticker_status="error",
            ticker_error_type=exc.__class__.__name__,
        )
    hot_symbols = [str(item["symbol"]).upper() for item in hot_rows if item.get("symbol")]
    auto_selected = _without_symbols(hot_symbols, excluded)
    selected = auto_selected or fallback
    fallback_reason = None if auto_selected else "no_auto_hot_symbols_after_filters_or_manual_exclusions"
    return selected, _live_source_health_base(
        config,
        mode="binance_24h_ticker" if auto_selected else "auto_hot_fallback",
        status="used" if selected else "empty",
        selected_symbols=selected,
        ticker_payload_count=len(ticker_payload),
        ticker_eligible_payload_count=len(eligible_ticker_payload),
        selected_rows=hot_rows,
        filters=filters,
        fallback_symbols=fallback if not auto_selected else [],
        manual_excluded_symbols=_manual_excluded_symbols(
            [
                *[
                    str(item.get("symbol", "")).upper()
                    for item in ticker_payload
                    if isinstance(item, dict)
                ],
                *fallback_source,
            ],
            excluded,
        ),
        fallback_reason=fallback_reason,
        ticker_status="used" if auto_selected else "empty",
        ticker_selected_count=len(auto_selected),
    )


def _without_symbols(symbols: list[str], excluded: set[str]) -> list[str]:
    return [symbol for symbol in symbols if symbol.upper() not in excluded]


def _manual_excluded_symbols(symbols: list[str], excluded: set[str]) -> list[str]:
    return sorted({symbol.upper() for symbol in symbols if symbol.upper() in excluded})


def _pre_collection_source_health(config: AppConfig, *, reason: str) -> dict[str, Any]:
    return {
        "symbol_selection": {
            "mode": "not_started",
            "status": "not_started",
            "reason": reason,
            "selected_count": 0,
            "selected_symbols": [],
        },
        "manual_symbol_exclusions": {
            "configured_symbols": config.get_list("BFA_MANUAL_POSITION_SYMBOLS"),
            "excluded_symbols": [],
            "excluded_count": 0,
            "status": "configured" if config.get_list("BFA_MANUAL_POSITION_SYMBOLS") else "not_configured",
        },
        "configured_narrative_sources": _configured_narrative_sources(config),
    }


def _live_source_health_base(
    config: AppConfig,
    *,
    mode: str,
    status: str,
    selected_symbols: list[str],
    filters: dict[str, int | float],
    fallback_symbols: list[str],
    manual_excluded_symbols: list[str],
    ticker_status: str,
    ticker_payload_count: int | None = None,
    ticker_eligible_payload_count: int | None = None,
    selected_rows: list[dict[str, Any]] | None = None,
    fallback_reason: str | None = None,
    ticker_error_type: str | None = None,
    ticker_selected_count: int | None = None,
) -> dict[str, Any]:
    symbol_selection: dict[str, Any] = {
        "mode": mode,
        "status": status,
        "selected_count": len(selected_symbols),
        "selected_symbols": list(selected_symbols),
        "fallback_symbols": list(fallback_symbols),
    }
    if fallback_reason:
        symbol_selection["fallback_reason"] = fallback_reason
    ticker: dict[str, Any] = {
        "status": ticker_status,
        "payload_count": ticker_payload_count,
        "eligible_payload_count": ticker_eligible_payload_count,
        "selected_count": ticker_selected_count if ticker_selected_count is not None else len(selected_symbols),
        "filters": dict(filters),
        "selected_rows": list(selected_rows or []),
    }
    if ticker_error_type:
        ticker["error_type"] = ticker_error_type
    return {
        "symbol_selection": symbol_selection,
        "binance_24h_ticker": ticker,
        "manual_symbol_exclusions": {
            "configured_symbols": config.get_list("BFA_MANUAL_POSITION_SYMBOLS"),
            "excluded_symbols": list(manual_excluded_symbols),
            "excluded_count": len(manual_excluded_symbols),
            "status": "excluded" if manual_excluded_symbols else "none_matched",
        },
        "configured_narrative_sources": _configured_narrative_sources(config),
    }


def _configured_narrative_sources(config: AppConfig) -> dict[str, Any]:
    rss_urls = rss_feed_urls(config)
    return {
        "binance_square_manual_export_dir_configured": bool(config.get("SQUARE_EXPORT_DIR")),
        "rss_feed_count": len(rss_urls),
        "rss_feeds_configured": bool(rss_urls),
        "market_heat_fallback_enabled": _truthy(config.get("BFA_MARKET_HEAT_NARRATIVE_ENABLED")),
    }


def _augment_live_source_health(
    config: AppConfig,
    source_health: dict[str, Any],
    *,
    market_snapshots,
    narrative_records,
    market_heat_records,
    market_heat_status: str,
    paper_guard,
) -> dict[str, Any]:
    payload = dict(source_health)
    payload["market_snapshots"] = _market_snapshot_source_health(market_snapshots)
    payload["narrative_sources"] = _narrative_source_health(config, narrative_records)
    payload["market_heat_fallback"] = {
        "enabled": _truthy(config.get("BFA_MARKET_HEAT_NARRATIVE_ENABLED")),
        "status": market_heat_status,
        "record_count": len(market_heat_records),
        "covered_symbols": _narrative_covered_symbols(market_heat_records),
    }
    payload["paper_guard"] = _paper_guard_source_health(paper_guard)
    return payload


def _market_snapshot_source_health(market_snapshots) -> dict[str, Any]:
    counts = Counter(str(snapshot.event_type or "unknown") for snapshot in market_snapshots)
    covered_symbols = sorted({str(snapshot.symbol).upper() for snapshot in market_snapshots if snapshot.symbol})
    expected = [
        "ticker_24h",
        "kline",
        "funding_rate",
        "open_interest",
        "open_interest_hist",
        "taker_buy_sell_volume",
    ]
    return {
        "status": "available" if market_snapshots else "empty",
        "total_count": len(market_snapshots),
        "event_type_counts": dict(sorted(counts.items())),
        "covered_symbols": covered_symbols,
        "expected_event_status": {event: "available" if counts.get(event, 0) else "missing" for event in expected},
    }


def _narrative_source_health(config: AppConfig, narrative_records) -> dict[str, Any]:
    source_counts = Counter(str(record.source or "unknown") for record in narrative_records)
    configured = _configured_narrative_sources(config)
    return {
        "status": "available" if narrative_records else "empty",
        "total_count": len(narrative_records),
        "source_counts": dict(sorted(source_counts.items())),
        "covered_symbols": _narrative_covered_symbols(narrative_records),
        **configured,
    }


def _narrative_covered_symbols(narrative_records) -> list[str]:
    symbols: set[str] = set()
    for record in narrative_records:
        symbols.update(str(symbol).upper() for symbol in record.symbol_mentions if str(symbol).strip())
    return sorted(symbols)


def _paper_guard_source_health(paper_guard) -> dict[str, Any]:
    if paper_guard is None:
        return {"status": "not_built", "enabled": False, "active": False}
    payload = paper_guard.to_dict()
    return {
        "status": payload.get("status"),
        "enabled": bool(payload.get("enabled")),
        "active": bool(getattr(paper_guard, "active", False)),
        "reasons": list(payload.get("reasons") or []),
        "summary": dict(payload.get("summary") or {}),
        "symbol_block_count": len(payload.get("symbol_blocks") or {}),
        "side_block_count": len(payload.get("side_blocks") or {}),
        "factor_block_count": len(payload.get("factor_blocks") or {}),
        "guarded_symbols": sorted((payload.get("symbol_blocks") or {}).keys()),
        "guarded_sides": sorted((payload.get("side_blocks") or {}).keys()),
        "guarded_factors": sorted((payload.get("factor_blocks") or {}).keys()),
    }


def _build_narrative_runner(
    config: AppConfig,
    *,
    collected_at: str,
    known_symbols: list[str] | None = None,
) -> NarrativeCollectionRunner:
    symbols = known_symbols or market_symbols(config)
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


def _collect_market_heat_narratives(
    config: AppConfig,
    market_snapshots,
    collected_at: str,
    *,
    known_symbols: list[str] | None = None,
):
    return MarketHeatNarrativeCollector(
        market_snapshots,
        known_symbols=known_symbols or market_symbols(config),
        collected_at=collected_at,
        min_quote_volume=float(config.get("BFA_MARKET_HEAT_MIN_QUOTE_VOLUME_USDT")),
        min_price_change_percent=float(config.get("BFA_MARKET_HEAT_MIN_PRICE_CHANGE_PERCENT")),
        min_taker_buy_sell_ratio=float(config.get("BFA_MARKET_HEAT_MIN_TAKER_BUY_SELL_RATIO")),
        min_open_interest_value=float(config.get("BFA_MARKET_HEAT_MIN_OPEN_INTEREST_VALUE_USDT")),
        max_kline_range_percent=float(config.get("BFA_MARKET_HEAT_MAX_KLINE_RANGE_PERCENT")),
        max_records=int(config.get("BFA_MARKET_HEAT_MAX_RECORDS")),
    ).collect()


def _evaluate_candidate_queue(
    *,
    config: AppConfig,
    mode: RuntimeMode,
    candidates,
    exchange_info,
    ai_client,
    ai_enabled: bool,
    journal_path: str | None,
    store: EventStore,
    signed_client,
    risk_state: RiskState,
    started_at: str,
    market_snapshot_count: int,
    narrative_record_count: int,
    candidate_count: int,
    rejected_count: int,
    scan_symbols: list[str],
    persisted_candidate_count: int,
    position_lifecycle_event_id: int | None,
    position_adjustment_plan,
    paper_guard,
    source_health: dict[str, Any],
) -> AgentRunResult:
    evaluated_symbols: list[str] = []
    candidate_evaluations: list[dict[str, Any]] = []
    ai_decisions_persisted = 0
    trade_setups_persisted = 0
    skipped_risk_reasons: list[str] = []
    last_status = "no_candidate"
    last_validation_errors: list[str] = []
    last_risk_reasons: list[str] = []

    for candidate in candidates:
        evaluated_symbols.append(candidate.symbol)
        candidate_evaluation = _candidate_evaluation_base(candidate)
        candidate_evaluations.append(candidate_evaluation)
        candidate_sizing = compute_position_sizing(
            sizing_input_from_config(config, candidate=candidate.to_dict()),
            enabled=dynamic_sizing_enabled(config),
        )
        risk_limits = RiskLimits.from_config(config, sizing_result=candidate_sizing)
        setup = build_trade_setup(
            candidate,
            risk_limits=risk_limits,
            profile=merge_guard_profile(None, paper_guard),
        )
        governor = apply_adaptive_sizing_governor(
            config,
            setup=setup,
            candidate=candidate,
            risk_state=risk_state,
            paper_guard=paper_guard,
        )
        setup = _setup_with_sizing_governor(setup, governor)
        persist_trade_setup(
            store,
            setup=setup,
            candidate=candidate,
            decided_at=started_at,
        )
        trade_setups_persisted += 1
        _record_candidate_setup(candidate_evaluation, setup)
        candidate_evaluation["sizing_governor"] = governor.to_dict()
        if not governor.accepted:
            last_status = "quant_pass"
            last_validation_errors = list(governor.reason_codes)
            skipped_risk_reasons.extend(f"{candidate.symbol}:{reason}" for reason in governor.reason_codes)
            _finish_candidate_evaluation(
                candidate_evaluation,
                execution_status="quant_pass",
                risk_reasons=list(governor.reason_codes),
                continued=True,
                end_reason="adaptive_sizing_governor",
            )
            continue
        if setup.decision != "trade":
            last_status = "quant_pass"
            last_validation_errors = list(setup.reasons)
            skipped_risk_reasons.append(f"{candidate.symbol}:quant_pass")
            _finish_candidate_evaluation(
                candidate_evaluation,
                execution_status="quant_pass",
                risk_reasons=["quant_pass"],
                continued=True,
                end_reason="setup_pass",
            )
            continue
        ai_status = "not_evaluated"
        if ai_enabled and ai_client is not None:
            try:
                ai_run = run_ai_decision(
                    client=ai_client,
                    context=context_from_candidate(
                        candidate,
                        risk_limits=risk_limits,
                        decided_at=started_at,
                        quant_setup=setup,
                    ),
                    journal=AiDecisionJournal(journal_path) if journal_path else None,
                    store=store,
                    source=ai_source(config),
                )
            except Exception as exc:
                _record_openai_backoff(config, exc)
                if not _ai_fallback_to_quant_enabled(config):
                    _record_candidate_ai(
                        candidate_evaluation,
                        status="error",
                        validation_errors=[_safe_ai_error(exc)],
                    )
                    _finish_candidate_evaluation(
                        candidate_evaluation,
                        execution_status="ai_error",
                        risk_reasons=[],
                        continued=False,
                        end_reason="ai_error",
                    )
                    return AgentRunResult(
                        status="ai_error",
                        mode=mode.value,
                        started_at=started_at,
                        market_snapshot_count=market_snapshot_count,
                        narrative_record_count=narrative_record_count,
                        candidate_count=candidate_count,
                        rejected_count=rejected_count,
                        scan_symbols=scan_symbols,
                        selected_symbol=candidate.symbol,
                        evaluated_symbols=evaluated_symbols,
                        validation_errors=[_safe_ai_error(exc)],
                        risk_reasons=_dedupe(skipped_risk_reasons),
                        position_review=_position_review_summary(position_adjustment_plan),
                        position_adjustment_plan=_position_adjustment_summary(position_adjustment_plan),
                        paper_guard=paper_guard.to_dict() if paper_guard is not None else None,
                        source_health=source_health,
                        candidate_evaluations=candidate_evaluations,
                        persisted={
                            **_position_lifecycle_persisted(position_lifecycle_event_id),
                            "candidates": persisted_candidate_count,
                            "trade_setups": trade_setups_persisted,
                            "ai_decisions": ai_decisions_persisted,
                        },
                    )
                ai_run = _quant_fallback_run(
                    candidate=candidate,
                    risk_limits=risk_limits,
                    setup=setup,
                    decided_at=started_at,
                    reason=_safe_ai_error(exc),
                )
                ai_status = "fallback_to_quant"
                skipped_risk_reasons.append(f"{candidate.symbol}:ai_fallback_to_quant")
            else:
                _clear_openai_backoff(config)
                ai_decisions_persisted += ai_run.persisted
                ai_status = "accepted"
        elif _ai_fallback_to_quant_enabled(config):
            ai_run = _quant_fallback_run(
                candidate=candidate,
                risk_limits=risk_limits,
                setup=setup,
                decided_at=started_at,
                reason="ai_disabled_or_backoff",
            )
            ai_status = "quant_only"
            skipped_risk_reasons.append(f"{candidate.symbol}:quant_only")
        else:
            _record_candidate_ai(
                candidate_evaluation,
                status="unavailable",
                validation_errors=["ai_client_unavailable"],
            )
            _finish_candidate_evaluation(
                candidate_evaluation,
                execution_status="ai_error",
                risk_reasons=[],
                continued=False,
                end_reason="ai_client_unavailable",
            )
            return AgentRunResult(
                status="ai_error",
                mode=mode.value,
                started_at=started_at,
                market_snapshot_count=market_snapshot_count,
                narrative_record_count=narrative_record_count,
                candidate_count=candidate_count,
                rejected_count=rejected_count,
                scan_symbols=scan_symbols,
                selected_symbol=candidate.symbol,
                evaluated_symbols=evaluated_symbols,
                validation_errors=["ai_client_unavailable"],
                risk_reasons=_dedupe(skipped_risk_reasons),
                position_review=_position_review_summary(position_adjustment_plan),
                position_adjustment_plan=_position_adjustment_summary(position_adjustment_plan),
                paper_guard=paper_guard.to_dict() if paper_guard is not None else None,
                source_health=source_health,
                candidate_evaluations=candidate_evaluations,
                persisted={
                    **_position_lifecycle_persisted(position_lifecycle_event_id),
                    "candidates": persisted_candidate_count,
                    "trade_setups": trade_setups_persisted,
                    "ai_decisions": ai_decisions_persisted,
                },
            )
        ai_decision = ai_run.validation.decision
        if ai_decision is not None and ai_decision.decision == "pass":
            last_status = "ai_pass"
            last_validation_errors = list(ai_run.validation.validation_errors)
            skipped_risk_reasons.append(f"{candidate.symbol}:ai_decision_pass")
            _record_candidate_ai(candidate_evaluation, status="ai_pass", ai_run=ai_run)
            _finish_candidate_evaluation(
                candidate_evaluation,
                execution_status="ai_pass",
                risk_reasons=["ai_decision_pass"],
                continued=True,
                end_reason="ai_pass",
            )
            continue
        _record_candidate_ai(candidate_evaluation, status=ai_status, ai_run=ai_run)
        if not ai_run.validation.accepted:
            last_status = (
                "ai_pass"
                if ai_run.validation.decision and ai_run.validation.decision.decision == "pass"
                else "ai_rejected"
            )
            last_validation_errors = list(ai_run.validation.validation_errors)
            skipped_risk_reasons.append(f"{candidate.symbol}:{last_status}")
            _record_candidate_ai(candidate_evaluation, status=last_status, ai_run=ai_run)
            _finish_candidate_evaluation(
                candidate_evaluation,
                execution_status=last_status,
                risk_reasons=[last_status],
                continued=True,
                end_reason=last_status,
            )
            continue

        filters = _filters_for_candidate(exchange_info, candidate.symbol)
        if filters is None:
            last_status = "rejected"
            last_risk_reasons = ["symbol_filters_missing"]
            skipped_risk_reasons.append(f"{candidate.symbol}:symbol_filters_missing")
            _finish_candidate_evaluation(
                candidate_evaluation,
                execution_status="rejected",
                risk_reasons=["symbol_filters_missing"],
                continued=True,
                end_reason="symbol_filters_missing",
            )
            continue

        execution = ExecutionEngine(
            config=config,
            signed_client=signed_client,
            store=store,
            risk_limits=risk_limits,
        ).run(
            symbol=candidate.symbol,
            validation=ai_run.validation,
            decided_at=started_at,
            risk_state=risk_state,
            filters=filters,
            now=started_at,
        )
        if execution.status == "rejected" and _should_try_next_candidate(execution.risk.reason_codes):
            last_status = execution.status
            last_risk_reasons = list(execution.risk.reason_codes)
            skipped_risk_reasons.extend(f"{candidate.symbol}:{reason}" for reason in execution.risk.reason_codes)
            _finish_candidate_evaluation(
                candidate_evaluation,
                execution_status=execution.status,
                risk_reasons=list(execution.risk.reason_codes),
                continued=True,
                end_reason="retryable_risk_skip",
            )
            continue

        _finish_candidate_evaluation(
            candidate_evaluation,
            execution_status=execution.status,
            risk_reasons=list(execution.risk.reason_codes),
            continued=False,
            end_reason="submitted" if execution.submitted else execution.status,
        )
        return AgentRunResult(
            status=execution.status,
            mode=mode.value,
            started_at=started_at,
            market_snapshot_count=market_snapshot_count,
            narrative_record_count=narrative_record_count,
            candidate_count=candidate_count,
            rejected_count=rejected_count,
            scan_symbols=scan_symbols,
            selected_symbol=candidate.symbol,
            evaluated_symbols=evaluated_symbols,
            ai_accepted=True,
            execution_status=execution.status,
            submitted=execution.submitted,
            risk_reasons=_dedupe([*skipped_risk_reasons, *execution.risk.reason_codes]),
            position_review=_position_review_summary(position_adjustment_plan),
            position_adjustment_plan=_position_adjustment_summary(position_adjustment_plan),
            paper_guard=paper_guard.to_dict() if paper_guard is not None else None,
            source_health=source_health,
            candidate_evaluations=candidate_evaluations,
            persisted={
                **_position_lifecycle_persisted(position_lifecycle_event_id),
                "candidates": persisted_candidate_count,
                "trade_setups": trade_setups_persisted,
                "ai_decisions": ai_decisions_persisted,
                **execution.persisted,
            },
        )

    return AgentRunResult(
        status=last_status,
        mode=mode.value,
        started_at=started_at,
        market_snapshot_count=market_snapshot_count,
        narrative_record_count=narrative_record_count,
        candidate_count=candidate_count,
        rejected_count=rejected_count,
        scan_symbols=scan_symbols,
        selected_symbol=evaluated_symbols[-1] if evaluated_symbols else None,
        evaluated_symbols=evaluated_symbols,
        ai_accepted=False,
        execution_status=last_status if last_status == "rejected" else None,
        submitted=False,
        validation_errors=last_validation_errors,
        risk_reasons=_dedupe([*skipped_risk_reasons, *last_risk_reasons]),
        position_review=_position_review_summary(position_adjustment_plan),
        position_adjustment_plan=_position_adjustment_summary(position_adjustment_plan),
        paper_guard=paper_guard.to_dict() if paper_guard is not None else None,
        source_health=source_health,
        candidate_evaluations=candidate_evaluations,
        persisted={
            **_position_lifecycle_persisted(position_lifecycle_event_id),
            "candidates": persisted_candidate_count,
            "trade_setups": trade_setups_persisted,
            "ai_decisions": ai_decisions_persisted,
        },
    )


def _filters_for_candidate(exchange_info, symbol: str) -> SymbolExecutionFilters | None:
    try:
        return SymbolExecutionFilters.from_exchange_info(exchange_info, symbol)
    except ValueError:
        return None


def _should_try_next_candidate(reason_codes: list[str]) -> bool:
    retryable = {
        "ai_decision_pass",
        "ai_decision_not_accepted",
        "duplicate_symbol_direction_exposure",
        "leverage_exceeds_cap",
        "notional_exceeds_cap",
        "notional_below_min",
        "notional_below_min_executable",
        "price_not_positive",
        "quantity_above_max",
        "quantity_below_min",
        "quantity_not_positive",
        "risk_exceeds_cap",
        "symbol_filters_missing",
        "trade_decision_missing_prices",
    }
    return bool(reason_codes) and all(reason in retryable for reason in reason_codes)


def _candidate_evaluation_base(candidate) -> dict[str, Any]:
    return {
        "symbol": candidate.symbol,
        "score": candidate.score,
        "candidate_reason_codes": list(candidate.reason_codes),
        "data_quality_notes": list(candidate.data_quality_notes),
        "setup": {"status": "not_evaluated"},
        "ai": {"status": "not_evaluated"},
        "execution": {"status": "not_evaluated"},
        "risk_reasons": [],
        "continued": False,
        "end_reason": None,
    }


def _record_candidate_setup(candidate_evaluation: dict[str, Any], setup) -> None:
    candidate_evaluation["setup"] = {
        "status": "trade" if setup.decision == "trade" else "pass",
        "decision": setup.decision,
        "side": setup.side,
        "confidence": setup.confidence,
        "reasons": list(setup.reasons),
        "warnings": list(setup.warnings),
        "risk_reward_ratio": setup.risk_reward_ratio,
        "stop_distance_percent": setup.stop_distance_percent,
        "target_distance_percent": setup.target_distance_percent,
        "notional_usdt": setup.notional_usdt,
        "factor_summary": dict(setup.factor_summary),
        "price_basis": dict(setup.price_basis),
    }


def _setup_with_sizing_governor(setup, governor):
    payload = governor.to_dict()
    price_basis = dict(setup.price_basis)
    price_basis["adaptive_sizing_governor"] = payload
    warnings = _dedupe([*setup.warnings, *governor.warnings])
    reasons = _dedupe([*setup.reasons, *governor.reason_codes])
    if not governor.accepted:
        return replace(
            setup,
            decision="pass",
            side="flat",
            entry_price=None,
            stop_price=None,
            target_price=None,
            notional_usdt=None,
            hold_time_minutes=None,
            price_basis=price_basis,
            reasons=reasons,
            warnings=warnings,
        )
    if governor.final_notional_usdt is None:
        return replace(setup, price_basis=price_basis, reasons=reasons, warnings=warnings)
    return replace(
        setup,
        notional_usdt=governor.final_notional_usdt,
        price_basis=price_basis,
        reasons=reasons,
        warnings=warnings,
    )


def _record_candidate_ai(
    candidate_evaluation: dict[str, Any],
    *,
    status: str,
    ai_run: AiDecisionRun | None = None,
    validation_errors: list[str] | None = None,
) -> None:
    payload: dict[str, Any] = {"status": status}
    if ai_run is not None:
        validation = ai_run.validation
        decision = validation.decision
        payload.update(
            {
                "accepted": validation.accepted,
                "validation_errors": list(validation.validation_errors),
                "validation_warnings": list(validation.validation_warnings),
                "decision": decision.decision if decision is not None else None,
                "side": decision.side if decision is not None else None,
                "confidence": decision.confidence if decision is not None else None,
                "persisted": ai_run.persisted,
            }
        )
    if validation_errors is not None:
        payload["accepted"] = False
        payload["validation_errors"] = list(validation_errors)
    candidate_evaluation["ai"] = payload


def _finish_candidate_evaluation(
    candidate_evaluation: dict[str, Any],
    *,
    execution_status: str,
    risk_reasons: list[str],
    continued: bool,
    end_reason: str,
) -> None:
    candidate_evaluation["execution"] = {"status": execution_status}
    candidate_evaluation["risk_reasons"] = list(risk_reasons)
    candidate_evaluation["continued"] = continued
    candidate_evaluation["end_reason"] = end_reason


def _quant_fallback_run(
    *,
    candidate,
    risk_limits: RiskLimits,
    setup,
    decided_at: str,
    reason: str,
) -> AiDecisionRun:
    return AiDecisionRun(
        context=context_from_candidate(
            candidate,
            risk_limits=risk_limits,
            decided_at=decided_at,
            quant_setup=setup,
        ),
        request_payload={"fallback": "quant_setup"},
        raw_response={"fallback_reason": reason},
        validation=setup.to_validation(),
        response_text="",
        journaled=False,
        persisted=0,
    )


def _live_position_adjustment_plan(config: AppConfig, *, db_path: str | None, signed_client, market_client=None):
    if signed_client is None:
        return None
    try:
        return build_position_adjustment_plan_report(
            config,
            db_path=db_path,
            check_binance=True,
            signed_client=signed_client,
            market_client=market_client,
        )
    except Exception:
        return None


def _execute_live_position_auto_management(
    config: AppConfig,
    *,
    db_path: str | None,
    signed_client,
    started_at: str,
    adjustment_plan,
):
    if signed_client is None or adjustment_plan is None:
        return None
    if not _truthy(config.get("BFA_POSITION_AUTO_MANAGEMENT_ENABLED")):
        return None
    if not adjustment_plan.adjustment_allowed:
        return None
    max_actions = _positive_int_or_default(
        config.get("BFA_POSITION_AUTO_MANAGEMENT_MAX_ACTIONS_PER_CYCLE"),
        1,
    )
    try:
        return execute_position_adjustment_plan_report(
            config,
            adjustment_plan,
            db_path=db_path or config.get("BFA_DB_PATH"),
            checked_at=started_at,
            signed_client=signed_client,
            allowed_actions=("trail_protective_orders",),
            max_actions=max_actions,
        )
    except Exception:
        return None


def _position_review_summary(adjustment_plan) -> dict[str, Any] | None:
    if adjustment_plan is None or adjustment_plan.position_review is None:
        return None
    review = adjustment_plan.position_review
    return {
        "status": review.status,
        "action_required": review.action_required,
        "reasons": list(review.reasons),
        "positions": [
            {
                "symbol": item.symbol,
                "position_side": item.position_side,
                "recommendation": item.recommendation,
                "urgency": item.urgency,
                "pnl_percent": item.pnl_percent,
                "stop_r_multiple": item.stop_r_multiple,
                "target_progress": item.target_progress,
                "hold_elapsed_fraction": item.hold_elapsed_fraction,
            }
            for item in review.positions
        ],
    }


def _position_adjustment_summary(adjustment_plan) -> dict[str, Any] | None:
    if adjustment_plan is None:
        return None
    return {
        "status": adjustment_plan.status,
        "adjustment_allowed": adjustment_plan.adjustment_allowed,
        "reasons": list(adjustment_plan.reasons),
        "diagnostics": [item.to_dict() for item in adjustment_plan.diagnostics],
        "plans": [
            {
                "symbol": item.order_plan.symbol,
                "action": item.order_plan.action,
                "quantity": item.order_plan.quantity,
                "side": item.order_plan.side,
                "position_side": item.order_plan.position_side,
                "reasons": list(item.reasons),
            }
            for item in adjustment_plan.plans
            if item.order_plan is not None
        ],
    }


def _persist_position_lifecycle(
    store: EventStore,
    *,
    config: AppConfig,
    started_at: str,
    adjustment_plan,
    auto_management_execution=None,
) -> int:
    payload = _position_lifecycle_payload(
        config,
        started_at=started_at,
        adjustment_plan=adjustment_plan,
        auto_management_execution=auto_management_execution,
    )
    return store.insert_artifact(
        "risk_state",
        occurred_at=started_at,
        source="agent.live_cycle",
        symbol=None,
        ref_id=f"position_lifecycle:{started_at}",
        event_type="position_lifecycle_decision",
        payload=payload,
    )


def _position_lifecycle_payload(
    config: AppConfig,
    *,
    started_at: str,
    adjustment_plan,
    auto_management_execution=None,
) -> dict[str, Any]:
    diagnostics = [item.to_dict() for item in adjustment_plan.diagnostics] if adjustment_plan is not None else []
    eligible_actions = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.get("order_plan") is not None and not diagnostic.get("manual_symbol")
    ]
    auto_allowed_actions = {"trail_protective_orders"}
    auto_eligible_actions = [
        diagnostic
        for diagnostic in eligible_actions
        if (diagnostic.get("order_plan") or {}).get("action") in auto_allowed_actions
    ]
    auto_management_enabled = _truthy(config.get("BFA_POSITION_AUTO_MANAGEMENT_ENABLED"))
    max_actions = _positive_int_or_default(
        config.get("BFA_POSITION_AUTO_MANAGEMENT_MAX_ACTIONS_PER_CYCLE"),
        1,
    )
    auto_execution_payload = auto_management_execution.to_dict() if auto_management_execution is not None else None
    auto_executed = bool(auto_management_execution and auto_management_execution.adjustment_executed)
    auto_status = (
        auto_management_execution.status
        if auto_management_execution is not None
        else "enabled_no_allowed_action"
        if auto_management_enabled
        else "disabled"
    )
    auto_reasons = (
        list(auto_management_execution.reasons)
        if auto_management_execution is not None
        else ["auto_management_waiting_for_trailing_action"]
        if auto_management_enabled
        else ["auto_management_disabled"]
    )
    return {
        "schema": "bfa_position_lifecycle_decision_v1",
        "mode": config.get("BFA_MODE"),
        "decided_at": started_at,
        "status": adjustment_plan.status if adjustment_plan is not None else "position_adjustment_unavailable",
        "adjustment_allowed": bool(adjustment_plan.adjustment_allowed) if adjustment_plan is not None else False,
        "reasons": list(adjustment_plan.reasons) if adjustment_plan is not None else ["position_adjustment_unavailable"],
        "manual_position_symbols": config.get_list("BFA_MANUAL_POSITION_SYMBOLS"),
        "auto_management": {
            "enabled": auto_management_enabled,
            "max_actions_per_cycle": max_actions,
            "eligible_action_count": len(eligible_actions),
            "auto_eligible_action_count": len(auto_eligible_actions),
            "selected_action_count": min(len(auto_eligible_actions), max_actions) if auto_management_enabled else 0,
            "allowed_actions": sorted(auto_allowed_actions),
            "executed": auto_executed,
            "status": auto_status,
            "reasons": auto_reasons,
            "execution": auto_execution_payload,
        },
        "position_review": _position_review_summary(adjustment_plan),
        "position_adjustment_plan": _position_adjustment_summary(adjustment_plan),
        "diagnostics": diagnostics,
        "read_only_exchange": {
            "places_orders": auto_executed,
            "cancels_orders": auto_executed,
            "mutates_exchange_state": auto_executed,
            "changes_systemd_state": False,
            "writes_env_files": False,
        },
    }


def _position_lifecycle_persisted(event_id: int | None) -> dict[str, int]:
    return {"position_lifecycle": event_id} if event_id is not None else {}


def _build_signed_client(config: AppConfig, mode: RuntimeMode):
    if mode not in {RuntimeMode.TESTNET, RuntimeMode.LIVE}:
        return None
    return BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )


def _risk_state_from_exchange(signed_client, *, manual_symbols: set[str] | None = None) -> RiskState | None:
    if signed_client is None:
        return None
    try:
        positions = signed_client.position_risk()
    except Exception:
        return None
    account_available_balance = None
    account_total_wallet_balance = None
    try:
        account = signed_client.account()
    except Exception:
        account = {}
    if isinstance(account, dict):
        account_available_balance = _float_or_none(account.get("availableBalance"))
        account_total_wallet_balance = _float_or_none(account.get("totalWalletBalance"))
    excluded = {symbol.upper() for symbol in (manual_symbols or set())}
    active_positions = 0
    active_exposures: list[dict[str, Any]] = []
    manual_exposures: list[dict[str, Any]] = []
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        try:
            amount = abs(float(position.get("positionAmt", 0)))
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            continue
        exposure = {
            "symbol": symbol,
            "direction": _position_direction(position),
            "notional_usdt": _position_notional(position),
            "initial_margin_usdt": _position_initial_margin(position),
            "leverage": _position_leverage(position),
        }
        if symbol in excluded:
            manual_exposures.append(exposure)
        else:
            active_positions += 1
            active_exposures.append(exposure)
    return RiskState(
        active_positions=active_positions,
        active_exposures=active_exposures,
        manual_exposures=manual_exposures,
        account_available_balance_usdt=account_available_balance,
        account_total_wallet_balance_usdt=account_total_wallet_balance,
    )


def _live_entry_capacity_blockers(config: AppConfig, risk_state: RiskState | None) -> list[str]:
    if risk_state is None:
        return []
    reasons: list[str] = []
    if risk_state.active_positions > 0 and not _truthy(config.get("BFA_MULTI_POSITION_ENABLED")):
        reasons.append("multi_position_disabled")
    try:
        max_open_positions = int(config.get("BFA_MAX_OPEN_POSITIONS"))
    except (TypeError, ValueError):
        max_open_positions = 0
    if risk_state.active_positions > 0 and risk_state.active_positions >= max_open_positions:
        reasons.append("max_open_positions_reached")
    portfolio_margin_cap = _portfolio_margin_cap(config)
    if portfolio_margin_cap > 0 and risk_state.total_initial_margin_usdt >= portfolio_margin_cap:
        reasons.append("portfolio_margin_cap_reached")
        if risk_state.manual_initial_margin_usdt > 0:
            reasons.append("manual_margin_pressure_included")
    return _dedupe(reasons)


def _portfolio_margin_cap(config: AppConfig) -> float:
    absolute = _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_USDT")) or 0.0
    capital = _float_or_none(config.get("BFA_ACCOUNT_CAPITAL_USDT")) or 0.0
    fraction = _float_or_none(config.get("BFA_MAX_PORTFOLIO_MARGIN_FRACTION")) or 0.0
    fraction_cap = capital * fraction
    positive = [value for value in (absolute, fraction_cap) if value > 0]
    return min(positive) if positive else 0.0


def _position_direction(position: dict[str, Any]) -> str:
    side = str(position.get("positionSide") or "").upper()
    if side in {"LONG", "SHORT"}:
        return side
    try:
        amount = float(position.get("positionAmt", 0))
    except (TypeError, ValueError):
        amount = 0.0
    return "LONG" if amount > 0 else "SHORT"


def _position_notional(position: dict[str, Any]) -> float:
    notional = _float_or_none(position.get("notional"))
    if notional is not None:
        return abs(notional)
    amount = abs(_float_or_none(position.get("positionAmt")) or 0.0)
    mark = _float_or_none(position.get("markPrice")) or _float_or_none(position.get("entryPrice")) or 0.0
    return abs(amount * mark)


def _position_initial_margin(position: dict[str, Any]) -> float:
    margin = _float_or_none(position.get("initialMargin"))
    if margin is not None:
        return abs(margin)
    leverage = _position_leverage(position)
    if leverage <= 0:
        return 0.0
    return _position_notional(position) / leverage


def _position_leverage(position: dict[str, Any]) -> float:
    return _float_or_none(position.get("leverage")) or 0.0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int_or_default(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


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


def _ai_fallback_to_quant_enabled(config: AppConfig) -> bool:
    return _truthy(config.get("BFA_AI_FALLBACK_TO_QUANT_ENABLED"))


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


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
