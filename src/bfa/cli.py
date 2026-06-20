"""Command-line utilities for local foundation checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from bfa.agent import run_agent_once
from bfa.ai.decision import run_ai_decision
from bfa.ai.journal import AiDecisionJournal
from bfa.ai.providers import ai_source, build_ai_client
from bfa.ai.schema import RiskLimits, context_from_candidate
from bfa.backtest.data import fetch_historical_klines, load_klines_dataset, write_klines_dataset
from bfa.backtest.engine import run_hot_momentum_backtest, run_staged_sweep
from bfa.backtest.matrix import BacktestMatrixConfig, HotUniverseConfig, run_hot_backtest_matrix
from bfa.backtest.models import BacktestConfig, built_in_variants
from bfa.config import AppConfig, load_config, market_symbols, rss_feed_urls, validate_config
from bfa.event_store.migrations import connect, migrate
from bfa.event_store.report import generate_review_report
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.execution.executor import ExecutionEngine
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import RiskState
from bfa.execution.sizing import compute_position_sizing, dynamic_sizing_enabled, sizing_input_from_config
from bfa.execution.outcome import build_latest_trade_outcome, reconcile_submitted_trade_outcomes
from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.market.collector import MarketDataCollector
from bfa.market.snapshot_writer import write_jsonl_snapshots
from bfa.narrative.collector import NarrativeCollectionRunner
from bfa.narrative.manual import ManualExportCollector
from bfa.narrative.rss import RssFeedCollector
from bfa.ops.health import run_health_checks
from bfa.ops.exposure_status import build_exposure_status_report
from bfa.ops.live_status import build_live_status_report
from bfa.ops.position_adjustment import (
    build_position_adjustment_execute_report,
    build_position_adjustment_plan_report,
)
from bfa.ops.position_hold_check import build_position_hold_check_report, build_time_exit_plan_report
from bfa.ops.position_review import build_position_review_report
from bfa.ops.risk_profile import apply_risk_profile, build_risk_profile_plan
from bfa.ops.risk_change_check import build_risk_change_check_report
from bfa.ops.resume_check import build_resume_check_report
from bfa.ops.strategy_promotion import build_strategy_promotion_check_report
from bfa.ops.time_exit_execute import build_time_exit_execute_report
from bfa.ops.trade_trace import build_trade_trace_report
from bfa.strategy.candidates import StrategyConfig, generate_candidates
from bfa.strategy.setup import build_trade_setup
from bfa.strategy.store import persist_candidates


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    client_factory=None,
    collector_factory=None,
    narrative_runner_factory=None,
    ai_client_factory=None,
    signed_client_factory=None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "config-check":
        return _run_config_check(args, env=env, stdout=stdout)
    if args.command == "market-data":
        return _run_market_data(
            args,
            env=env,
            stdout=stdout,
            client_factory=client_factory,
            collector_factory=collector_factory,
        )
    if args.command == "narrative":
        return _run_narrative(
            args,
            env=env,
            stdout=stdout,
            runner_factory=narrative_runner_factory,
        )
    if args.command == "event-store":
        return _run_event_store(args, env=env, stdout=stdout)
    if args.command == "strategy":
        return _run_strategy(args, env=env, stdout=stdout)
    if args.command == "ai":
        return _run_ai(
            args,
            env=env,
            stdout=stdout,
            ai_client_factory=ai_client_factory,
        )
    if args.command == "execution":
        return _run_execution(
            args,
            env=env,
            stdout=stdout,
            signed_client_factory=signed_client_factory,
        )
    if args.command == "ops":
        return _run_ops(
            args,
            env=env,
            stdout=stdout,
            client_factory=client_factory,
            ai_client_factory=ai_client_factory,
            signed_client_factory=signed_client_factory,
        )
    if args.command == "agent":
        return _run_agent(
            args,
            env=env,
            stdout=stdout,
            client_factory=client_factory,
            collector_factory=collector_factory,
            narrative_runner_factory=narrative_runner_factory,
            ai_client_factory=ai_client_factory,
            signed_client_factory=signed_client_factory,
        )
    if args.command == "backtest":
        return _run_backtest(
            args,
            env=env,
            stdout=stdout,
            client_factory=client_factory,
        )

    parser.print_help(file=stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bfa")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_check = subparsers.add_parser(
        "config-check",
        help="validate runtime configuration without printing secrets",
    )
    config_check.add_argument(
        "--env-file",
        help="optional env file to load before environment overrides",
    )

    market_data = subparsers.add_parser(
        "market-data",
        help="public Binance USD-M market-data smoke commands",
    )
    market_subparsers = market_data.add_subparsers(dest="market_command", required=True)

    exchange_info = market_subparsers.add_parser(
        "exchange-info",
        help="fetch public exchange metadata",
    )
    exchange_info.add_argument(
        "--env-file",
        help="optional env file to load before environment overrides",
    )

    snapshot = market_subparsers.add_parser(
        "snapshot",
        help="collect selected-symbol public market snapshots",
    )
    snapshot.add_argument(
        "--env-file",
        help="optional env file to load before environment overrides",
    )
    snapshot.add_argument(
        "--output",
        required=True,
        help="JSONL output path under a caller-managed data/runtime directory",
    )

    narrative = subparsers.add_parser(
        "narrative",
        help="narrative and hot-coin source collection smoke commands",
    )
    narrative_subparsers = narrative.add_subparsers(dest="narrative_command", required=True)

    collect = narrative_subparsers.add_parser(
        "collect",
        help="collect configured narrative sources and write normalized JSONL records",
    )
    collect.add_argument(
        "--env-file",
        help="optional env file to load before environment overrides",
    )
    collect.add_argument(
        "--output",
        required=True,
        help="JSONL output path under a caller-managed data/runtime directory",
    )
    collect.add_argument(
        "--append",
        action="store_true",
        help="append to the output JSONL file instead of overwriting it",
    )

    event_store = subparsers.add_parser(
        "event-store",
        help="local SQLite event-store smoke commands",
    )
    event_store_subparsers = event_store.add_subparsers(dest="event_store_command", required=True)

    event_init = event_store_subparsers.add_parser(
        "init",
        help="initialize the SQLite event-store schema",
    )
    event_init.add_argument("--env-file", help="optional env file to load before environment overrides")
    event_init.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")

    event_report = event_store_subparsers.add_parser(
        "report",
        help="print event-store review metrics",
    )
    event_report.add_argument("--env-file", help="optional env file to load before environment overrides")
    event_report.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")

    strategy = subparsers.add_parser(
        "strategy",
        help="strategy smoke commands",
    )
    strategy_subparsers = strategy.add_subparsers(dest="strategy_command", required=True)
    candidates = strategy_subparsers.add_parser(
        "candidates",
        help="rank hot-coin candidates from a replay packet JSON file",
    )
    candidates.add_argument("--env-file", help="optional env file to load before environment overrides")
    candidates.add_argument("--replay", required=True, help="replay packet JSON file")
    candidates.add_argument("--db", help="optional SQLite DB path for persisting candidates")
    candidates.add_argument("--top-n", type=int, default=5, help="maximum candidates to return")
    candidates.add_argument(
        "--generated-at",
        required=True,
        help="deterministic generation timestamp to stamp candidate records",
    )

    ai = subparsers.add_parser(
        "ai",
        help="AI structured decision-layer smoke commands",
    )
    ai_subparsers = ai.add_subparsers(dest="ai_command", required=True)
    decide = ai_subparsers.add_parser(
        "decide",
        help="ask the selected AI provider for a structured decision for one candidate JSON payload",
    )
    decide.add_argument("--env-file", help="optional env file to load before environment overrides")
    decide.add_argument("--candidate", required=True, help="candidate JSON file")
    decide.add_argument("--decided-at", required=True, help="deterministic decision timestamp")
    decide.add_argument("--journal", help="optional JSONL journal path for redacted request/response records")
    decide.add_argument("--db", help="optional SQLite DB path for persisting AI decisions")

    execution = subparsers.add_parser(
        "execution",
        help="risk-gated execution smoke commands",
    )
    execution_subparsers = execution.add_subparsers(dest="execution_command", required=True)
    run_execution = execution_subparsers.add_parser(
        "run",
        help="turn an accepted AI decision into a dry-run or live order intent",
    )
    run_execution.add_argument("--env-file", help="optional env file to load before environment overrides")
    run_execution.add_argument("--decision", required=True, help="AI decision JSON file")
    run_execution.add_argument("--symbol", required=True, help="symbol to execute, e.g. BTCUSDT")
    run_execution.add_argument("--decided-at", required=True, help="deterministic decision timestamp")
    run_execution.add_argument("--exchange-info", help="optional exchangeInfo JSON file for symbol filters")
    run_execution.add_argument("--db", help="optional SQLite DB path for persisting execution artifacts")

    ops = subparsers.add_parser(
        "ops",
        help="server deployment and operations smoke commands",
    )
    ops_subparsers = ops.add_subparsers(dest="ops_command", required=True)
    health = ops_subparsers.add_parser(
        "health-check",
        help="run secret-safe server health checks",
    )
    health.add_argument("--env-file", help="optional env file to load before environment overrides")
    health.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    health.add_argument("--create-dirs", action="store_true", help="create missing runtime directories")
    health.add_argument("--check-binance", action="store_true", help="check public Binance exchangeInfo")
    health.add_argument("--check-openai", action="store_true", help="check selected AI provider when enabled")
    health.add_argument("--skip-network", action="store_true", help="disable all network health checks")

    live_status = ops_subparsers.add_parser(
        "live-status",
        help="summarize live activation evidence from the local event store",
    )
    live_status.add_argument("--env-file", help="optional env file to load before environment overrides")
    live_status.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    live_status.add_argument("--check-binance", action="store_true", help="also fetch read-only signed Binance account evidence")

    resume_check = ops_subparsers.add_parser(
        "resume-check",
        help="read-only gate for deciding whether the live timer can be resumed",
    )
    resume_check.add_argument("--env-file", help="optional env file to load before environment overrides")
    resume_check.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    resume_check.add_argument(
        "--skip-binance",
        action="store_true",
        help="use only local event-store evidence instead of signed Binance reads",
    )

    trade_outcome = ops_subparsers.add_parser(
        "trade-outcome",
        help="reconstruct the latest submitted trade outcome from read-only Binance fills",
    )
    trade_outcome.add_argument("--env-file", help="optional env file to load before environment overrides")
    trade_outcome.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    trade_outcome.add_argument("--symbol", help="optional symbol filter, e.g. ZECUSDT")
    trade_outcome.add_argument("--persist", action="store_true", help="persist fills and outcome into the event store")

    trade_trace = ops_subparsers.add_parser(
        "trade-trace",
        help="read-only reconstruction of candidate, quant setup, AI, risk, and exchange evidence for a trade",
    )
    trade_trace.add_argument("--env-file", help="optional env file to load before environment overrides")
    trade_trace.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    trade_trace.add_argument("--event-id", type=int, help="order_intent event id or row id")
    trade_trace.add_argument("--symbol", help="latest order intent for symbol, e.g. SOLUSDT")

    strategy_promotion = ops_subparsers.add_parser(
        "strategy-promotion-check",
        help="read-only gate for promoting a backtest matrix toward forward/live use",
    )
    strategy_promotion.add_argument("--env-file", help="optional env file to load before environment overrides")
    strategy_promotion.add_argument("--matrix-report", required=True, help="JSON report from backtest matrix")
    strategy_promotion.add_argument("--variant", default="quant_setup", help="variant to check")
    strategy_promotion.add_argument("--min-trade-count", type=int, default=5, help="minimum trades per interval cell")
    strategy_promotion.add_argument(
        "--min-positive-window-rate",
        type=float,
        default=0.5,
        help="minimum positive window rate per interval cell",
    )
    strategy_promotion.add_argument(
        "--max-worst-drawdown-usdt",
        type=float,
        help="optional absolute drawdown cap; defaults to matrix cell max_daily_loss_usdt",
    )

    reconcile_outcomes = ops_subparsers.add_parser(
        "reconcile-outcomes",
        help="sweep submitted trade intents and reconcile closed outcomes from read-only Binance fills",
    )
    reconcile_outcomes.add_argument("--env-file", help="optional env file to load before environment overrides")
    reconcile_outcomes.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    reconcile_outcomes.add_argument("--symbol", help="optional symbol filter, e.g. BNBUSDT")
    reconcile_outcomes.add_argument(
        "--persist-closed",
        action="store_true",
        help="persist fills/outcomes only for trades that summarize as closed",
    )
    reconcile_outcomes.add_argument(
        "--include-reconciled",
        action="store_true",
        help="also fetch submitted intents that already have a closed outcome",
    )
    reconcile_outcomes.add_argument("--limit", type=int, default=500, help="maximum userTrades rows per intent")

    position_hold_check = ops_subparsers.add_parser(
        "position-hold-check",
        help="read-only check for active positions that exceed AI hold-time guidance",
    )
    position_hold_check.add_argument("--env-file", help="optional env file to load before environment overrides")
    position_hold_check.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    position_hold_check.add_argument("--now", help="optional ISO timestamp for deterministic checks")
    position_hold_check.add_argument(
        "--skip-binance",
        action="store_true",
        help="use only local event-store evidence instead of signed Binance reads",
    )

    position_review = ops_subparsers.add_parser(
        "position-review",
        help="read-only review of active positions with hold/watch/trail/close recommendations",
    )
    position_review.add_argument("--env-file", help="optional env file to load before environment overrides")
    position_review.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    position_review.add_argument("--now", help="optional ISO timestamp for deterministic checks")
    position_review.add_argument(
        "--skip-binance",
        action="store_true",
        help="use only local event-store evidence instead of signed Binance reads",
    )

    position_adjustment_plan = ops_subparsers.add_parser(
        "position-adjustment-plan",
        help="read-only plan for partial take-profit or close adjustments from active-position review",
    )
    position_adjustment_plan.add_argument("--env-file", help="optional env file to load before environment overrides")
    position_adjustment_plan.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    position_adjustment_plan.add_argument("--now", help="optional ISO timestamp for deterministic checks")
    position_adjustment_plan.add_argument(
        "--skip-binance",
        action="store_true",
        help="use only local event-store evidence instead of signed Binance reads",
    )

    position_adjustment_execute = ops_subparsers.add_parser(
        "position-adjustment-execute",
        help="operator-approved execution of a ready active-position adjustment plan",
    )
    position_adjustment_execute.add_argument("--env-file", help="optional env file to load before environment overrides")
    position_adjustment_execute.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    position_adjustment_execute.add_argument("--now", help="optional ISO timestamp for deterministic checks")
    position_adjustment_execute.add_argument(
        "--confirm-token",
        help="confirmation token from a prior position-adjustment-execute preview",
    )
    position_adjustment_execute.add_argument(
        "--service-active",
        action="store_true",
        help="fail closed when the live systemd service is currently active",
    )

    time_exit_plan = ops_subparsers.add_parser(
        "time-exit-plan",
        help="read-only plan for closing positions that exceeded AI hold-time guidance",
    )
    time_exit_plan.add_argument("--env-file", help="optional env file to load before environment overrides")
    time_exit_plan.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    time_exit_plan.add_argument("--now", help="optional ISO timestamp for deterministic checks")
    time_exit_plan.add_argument(
        "--skip-binance",
        action="store_true",
        help="use only local event-store evidence instead of signed Binance reads",
    )

    time_exit_execute = ops_subparsers.add_parser(
        "time-exit-execute",
        help="operator-approved execution of a ready time-exit plan",
    )
    time_exit_execute.add_argument("--env-file", help="optional env file to load before environment overrides")
    time_exit_execute.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    time_exit_execute.add_argument("--now", help="optional ISO timestamp for deterministic checks")
    time_exit_execute.add_argument(
        "--confirm-token",
        help="confirmation token from a prior dry confirmation-required response",
    )
    time_exit_execute.add_argument(
        "--service-active",
        action="store_true",
        help="fail closed when the live systemd service is currently active",
    )

    risk_change_check = ops_subparsers.add_parser(
        "risk-change-check",
        help="read-only gate for deciding whether leverage/risk caps may be changed",
    )
    risk_change_check.add_argument("--env-file", help="optional env file to load before environment overrides")
    risk_change_check.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    risk_change_check.add_argument("--target-leverage", type=int, help="optional proposed new max leverage")
    risk_change_check.add_argument(
        "--skip-binance",
        action="store_true",
        help="use only local event-store evidence instead of signed Binance reads",
    )

    risk_profile_plan = ops_subparsers.add_parser(
        "risk-profile-plan",
        help="preview a named risk profile env diff without writing files",
    )
    risk_profile_plan.add_argument("--env-file", help="optional env file to load before environment overrides")
    risk_profile_plan.add_argument("--profile", default="30u_8x_dynamic", help="risk profile name")
    risk_profile_plan.add_argument(
        "--allow-two-positions",
        action="store_true",
        help="preview profile with two concurrent positions enabled",
    )

    risk_profile_apply = ops_subparsers.add_parser(
        "risk-profile-apply",
        help="apply a named risk profile after risk-change readiness and token confirmation",
    )
    risk_profile_apply.add_argument("--env-file", required=True, help="env file to read and update")
    risk_profile_apply.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    risk_profile_apply.add_argument("--profile", default="30u_8x_dynamic", help="risk profile name")
    risk_profile_apply.add_argument("--confirm-token", help="confirmation token from risk-profile-plan")
    risk_profile_apply.add_argument(
        "--allow-two-positions",
        action="store_true",
        help="apply profile with two concurrent positions enabled",
    )
    risk_profile_apply.add_argument(
        "--service-active",
        action="store_true",
        help="fail closed when the live systemd service is currently active",
    )

    exposure_status = ops_subparsers.add_parser(
        "exposure-status",
        help="read-only explanation of current sizing, direction support, and entry capacity",
    )
    exposure_status.add_argument("--env-file", help="optional env file to load before environment overrides")
    exposure_status.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    exposure_status.add_argument(
        "--skip-binance",
        action="store_true",
        help="use only local event-store evidence instead of signed Binance reads",
    )
    exposure_status.add_argument(
        "--target-profile",
        default="30u_10x_multi_dynamic",
        help="optional risk profile to preview; use empty string to disable",
    )
    exposure_status.add_argument(
        "--allow-two-positions",
        action="store_true",
        help="preview target profile with two concurrent positions enabled",
    )
    exposure_status.add_argument("--hypothetical-symbol", help="optional symbol for a hypothetical new entry")
    exposure_status.add_argument(
        "--hypothetical-side",
        choices=("long", "short"),
        help="optional side for a hypothetical new entry",
    )

    agent = subparsers.add_parser(
        "agent",
        help="automated one-cycle trading runner",
    )
    agent_subparsers = agent.add_subparsers(dest="agent_command", required=True)
    run_once = agent_subparsers.add_parser(
        "run-once",
        help="collect data, decide, and execute at most one risk-gated order",
    )
    run_once.add_argument("--env-file", help="optional env file to load before environment overrides")
    run_once.add_argument("--db", help="SQLite DB path; defaults to BFA_DB_PATH")
    run_once.add_argument("--journal", help="optional redacted AI journal JSONL path")
    run_once.add_argument("--top-n", type=int, default=3, help="maximum candidates to evaluate")

    backtest = subparsers.add_parser(
        "backtest",
        help="small-capital short-window backtest commands",
    )
    backtest_subparsers = backtest.add_subparsers(dest="backtest_command", required=True)
    fetch_klines = backtest_subparsers.add_parser(
        "fetch-klines",
        help="fetch Binance USD-M futures klines into a local JSON dataset",
    )
    fetch_klines.add_argument("--env-file", help="optional env file to load before environment overrides")
    fetch_klines.add_argument("--symbols", help="comma-separated symbols; defaults to BFA_MARKET_SYMBOLS")
    fetch_klines.add_argument("--interval", default="5m", help="kline interval, e.g. 1m, 5m, 15m")
    fetch_klines.add_argument("--start", help="inclusive ISO time or epoch milliseconds")
    fetch_klines.add_argument("--end", help="inclusive ISO time or epoch milliseconds")
    fetch_klines.add_argument("--limit", type=int, default=288, help="maximum bars per symbol")
    fetch_klines.add_argument("--output", required=True, help="output JSON path under data/ or runtime/")

    run_backtest = backtest_subparsers.add_parser(
        "run",
        help="run one hot-momentum backtest variant from a local kline dataset",
    )
    run_backtest.add_argument("--input", required=True, help="kline JSON dataset from fetch-klines")
    run_backtest.add_argument("--variant", choices=sorted(built_in_variants()), default="balanced")
    run_backtest.add_argument("--include-trades", action="store_true", help="include individual trades in output")
    run_backtest.add_argument("--output", help="optional JSON report path")

    sweep = backtest_subparsers.add_parser(
        "sweep",
        help="run staged short-window sweeps across strict/balanced/aggressive variants",
    )
    sweep.add_argument("--input", required=True, help="kline JSON dataset from fetch-klines")
    sweep.add_argument("--window-bars", type=int, default=72, help="bars per stage window")
    sweep.add_argument("--step-bars", type=int, help="bars to move between windows; defaults to window-bars")
    sweep.add_argument(
        "--variants",
        default="strict,balanced,aggressive",
        help="comma-separated variants; see backtest run --help for names",
    )
    sweep.add_argument("--output", help="optional JSON report path")

    matrix = backtest_subparsers.add_parser(
        "matrix",
        help="select hot USDT futures symbols and run multi-interval staged sweeps",
    )
    matrix.add_argument("--env-file", help="optional env file to load before environment overrides")
    matrix.add_argument("--symbols", help="comma-separated symbols; when omitted, auto-select from Binance 24h ticker")
    matrix.add_argument("--intervals", default="5m,15m", help="comma-separated intervals to fetch and sweep")
    matrix.add_argument("--start", help="inclusive ISO time or epoch milliseconds")
    matrix.add_argument("--end", help="inclusive ISO time or epoch milliseconds")
    matrix.add_argument("--limit", type=int, default=144, help="maximum bars per symbol per interval")
    matrix.add_argument("--window-bars", type=int, default=72, help="bars per stage window")
    matrix.add_argument("--step-bars", type=int, default=36, help="bars to move between windows")
    matrix.add_argument(
        "--variants",
        default="strict,balanced,aggressive",
        help="comma-separated variants; see backtest run --help for names",
    )
    matrix.add_argument("--top-n", type=int, default=8, help="number of hot symbols to select")
    matrix.add_argument(
        "--min-quote-volume-usdt",
        type=float,
        default=10_000_000.0,
        help="minimum 24h quote volume for automatic hot-symbol selection",
    )
    matrix.add_argument(
        "--min-abs-price-change-percent",
        type=float,
        default=3.0,
        help="minimum absolute 24h price change percent for automatic hot-symbol selection",
    )
    matrix.add_argument("--output", help="optional JSON report path")
    return parser


def _run_config_check(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    result = validate_config(config)
    payload = {
        "mode": result.mode.value if result.mode is not None else None,
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "redacted": result.redacted,
    }
    print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
    return 0 if result.valid else 1


def _run_market_data(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
    client_factory,
    collector_factory,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    client = _build_client(config, client_factory)

    if args.market_command == "exchange-info":
        response = client.exchange_info()
        payload = {
            "endpoint": response.endpoint,
            "params": response.params,
            "request_weight": response.request_weight,
            "payload": response.payload,
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0

    if args.market_command == "snapshot":
        collector = _build_collector(config, client, collector_factory)
        snapshots = collector.collect_rest_snapshots()
        written = write_jsonl_snapshots(Path(args.output), snapshots)
        payload = {
            "output": str(args.output),
            "snapshot_count": len(snapshots),
            "symbols": getattr(collector, "symbols", market_symbols(config)),
            "written": written,
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0

    return 2


def _build_client(config: AppConfig, client_factory):
    if client_factory is not None:
        return client_factory(config)
    return BinanceFuturesRestClient(base_url=config.get("BINANCE_FUTURES_BASE_URL"))


def _build_collector(config: AppConfig, client, collector_factory):
    if collector_factory is not None:
        return collector_factory(config, client)
    return MarketDataCollector(client=client, symbols=market_symbols(config))


def _run_narrative(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
    runner_factory,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    if args.narrative_command == "collect":
        runner = _build_narrative_runner(config, runner_factory)
        records, written = runner.collect_to_jsonl(args.output, append=args.append)
        payload = {
            "output": str(args.output),
            "record_count": len(records),
            "sources": sorted({record.source for record in records}),
            "symbols": sorted({symbol for record in records for symbol in record.symbol_mentions}),
            "written": written,
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0
    return 2


def _build_narrative_runner(config: AppConfig, runner_factory):
    if runner_factory is not None:
        return runner_factory(config)
    known_symbols = market_symbols(config)
    collectors = [
        ManualExportCollector(
            config.get("SQUARE_EXPORT_DIR"),
            default_source="binance_square",
            known_symbols=known_symbols,
        )
    ]
    feeds = rss_feed_urls(config)
    if feeds:
        collectors.append(RssFeedCollector(feeds, known_symbols=known_symbols))
    return NarrativeCollectionRunner(collectors)


def _run_event_store(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    db_path = args.db or config.get("BFA_DB_PATH")
    connection = connect(db_path)
    try:
        migrate(connection)
        if args.event_store_command == "init":
            payload = {"db": str(db_path), "initialized": True}
            print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
            return 0
        if args.event_store_command == "report":
            payload = {"db": str(db_path), "report": generate_review_report(connection).to_dict()}
            print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
            return 0
    finally:
        connection.close()
    return 2


def _run_strategy(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    if args.strategy_command == "candidates":
        replay_packet = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        sizing = compute_position_sizing(
            sizing_input_from_config(config),
            enabled=dynamic_sizing_enabled(config),
        )
        result = generate_candidates(
            replay_packet,
            StrategyConfig(
                allowed_symbols=market_symbols(config),
                generated_at=args.generated_at,
                top_n=args.top_n,
                max_position_notional_usdt=sizing.max_position_notional_usdt,
            ),
        )
        persisted = 0
        if args.db:
            connection = connect(args.db)
            try:
                store = EventStore(connection)
                persisted = len(persist_candidates(store, result.candidates))
            finally:
                connection.close()
        payload = result.to_dict()
        payload["persisted"] = persisted
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0
    return 2


def _run_ai(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
    ai_client_factory,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    if args.ai_command == "decide":
        if not _truthy(config.get("BFA_OPENAI_ENABLED")):
            payload = {
                "accepted": False,
                "decision": None,
                "validation_errors": ["BFA_OPENAI_ENABLED must be true for ai decide"],
                "journaled": False,
                "persisted": 0,
            }
            print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
            return 1
        config_result = validate_config(config)
        if not config_result.valid:
            payload = {
                "accepted": False,
                "decision": None,
                "validation_errors": config_result.errors,
                "journaled": False,
                "persisted": 0,
            }
            print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
            return 1

        candidate = _candidate_payload_from_json(Path(args.candidate))
        candidate_sizing = compute_position_sizing(
            sizing_input_from_config(config, candidate=candidate),
            enabled=dynamic_sizing_enabled(config),
        )
        risk_limits = RiskLimits.from_config(config, sizing_result=candidate_sizing)
        setup = build_trade_setup(candidate, risk_limits=risk_limits)
        context = context_from_candidate(
            candidate,
            risk_limits=risk_limits,
            decided_at=args.decided_at,
            quant_setup=setup,
        )
        client = _build_ai_client(config, ai_client_factory)
        journal = AiDecisionJournal(args.journal) if args.journal else None
        connection = connect(args.db) if args.db else None
        try:
            store = EventStore(connection) if connection is not None else None
            result = run_ai_decision(
                client=client,
                context=context,
                journal=journal,
                store=store,
                source=ai_source(config),
            )
        finally:
            if connection is not None:
                connection.close()
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if result.validation.accepted else 1
    return 2


def _build_ai_client(config: AppConfig, ai_client_factory):
    return build_ai_client(config, ai_client_factory)


def _run_execution(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
    signed_client_factory,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    validation = _decision_validation_from_json(Path(args.decision), config, args.symbol, args.decided_at)
    filters = _execution_filters_from_file(args.exchange_info, args.symbol) if args.exchange_info else None
    connection = connect(args.db) if args.db else None
    try:
        store = EventStore(connection) if connection is not None else None
        signed_client = _build_signed_client(config, signed_client_factory)
        result = ExecutionEngine(
            config=config,
            signed_client=signed_client,
            store=store,
        ).run(
            symbol=args.symbol,
            validation=validation,
            decided_at=args.decided_at,
            risk_state=RiskState(),
            filters=filters,
            now=args.decided_at,
        )
    finally:
        if connection is not None:
            connection.close()
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True), file=stdout)
    return 0 if result.status in {"dry_run", "submitted", "test_order_checked"} else 1


def _build_signed_client(config: AppConfig, signed_client_factory):
    if signed_client_factory is not None:
        return signed_client_factory(config)
    if config.get("BFA_MODE") not in {"live", "testnet"}:
        return None
    return BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )


def _run_ops(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
    client_factory,
    ai_client_factory,
    signed_client_factory,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    if args.ops_command == "health-check":
        check_binance = bool(args.check_binance and not args.skip_network)
        check_openai = bool(args.check_openai and not args.skip_network)
        market_client = _build_client(config, client_factory) if check_binance else None
        ai_client = _build_ai_client(config, ai_client_factory) if check_openai else None
        report = run_health_checks(
            config,
            db_path=args.db,
            create_dirs=args.create_dirs,
            check_binance=check_binance,
            check_openai=check_openai,
            market_client=market_client,
            ai_client=ai_client,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.ok else 1
    if args.ops_command == "live-status":
        report = build_live_status_report(
            config,
            db_path=args.db,
            check_binance=args.check_binance,
            signed_client=_build_signed_client(config, signed_client_factory) if args.check_binance else None,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0
    if args.ops_command == "resume-check":
        report = build_resume_check_report(
            config,
            db_path=args.db,
            check_binance=not args.skip_binance,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.resume_allowed else 1
    if args.ops_command == "trade-outcome":
        signed_client = _build_signed_client(config, signed_client_factory)
        if signed_client is None:
            payload = {
                "found": False,
                "outcome": None,
                "error": "BFA_MODE must be live or testnet for ops trade-outcome",
            }
            print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
            return 1
        connection = connect(args.db or config.get("BFA_DB_PATH"))
        try:
            store = EventStore(connection)
            outcome = build_latest_trade_outcome(
                store,
                signed_client,
                symbol=args.symbol,
                persist=args.persist,
            )
        finally:
            connection.close()
        payload = {"found": outcome is not None, "outcome": outcome.to_dict() if outcome else None}
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0 if outcome is not None else 1
    if args.ops_command == "trade-trace":
        report = build_trade_trace_report(
            db_path=args.db or config.get("BFA_DB_PATH"),
            event_id=args.event_id,
            symbol=args.symbol,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.found else 1
    if args.ops_command == "strategy-promotion-check":
        report = build_strategy_promotion_check_report(
            args.matrix_report,
            variant=args.variant,
            min_trade_count=args.min_trade_count,
            min_positive_window_rate=args.min_positive_window_rate,
            max_worst_drawdown_usdt=args.max_worst_drawdown_usdt,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.promotion_allowed else 1
    if args.ops_command == "reconcile-outcomes":
        signed_client = _build_signed_client(config, signed_client_factory)
        if signed_client is None:
            payload = {
                "found": False,
                "report": None,
                "error": "BFA_MODE must be live or testnet for ops reconcile-outcomes",
            }
            print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
            return 1
        connection = connect(args.db or config.get("BFA_DB_PATH"))
        try:
            store = EventStore(connection)
            report = reconcile_submitted_trade_outcomes(
                store,
                signed_client,
                symbol=args.symbol,
                persist_closed=args.persist_closed,
                include_reconciled=args.include_reconciled,
                limit=args.limit,
            )
        finally:
            connection.close()
        payload = {"found": bool(report.items), "report": report.to_dict()}
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0
    if args.ops_command == "position-hold-check":
        report = build_position_hold_check_report(
            config,
            db_path=args.db,
            check_binance=not args.skip_binance,
            now=args.now,
            signed_client=_build_signed_client(config, signed_client_factory),
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 1 if report.action_required else 0
    if args.ops_command == "position-review":
        report = build_position_review_report(
            config,
            db_path=args.db,
            check_binance=not args.skip_binance,
            now=args.now,
            signed_client=_build_signed_client(config, signed_client_factory),
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 1 if report.action_required else 0
    if args.ops_command == "position-adjustment-plan":
        report = build_position_adjustment_plan_report(
            config,
            db_path=args.db,
            check_binance=not args.skip_binance,
            now=args.now,
            signed_client=_build_signed_client(config, signed_client_factory),
            market_client=_build_client(config, client_factory),
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.adjustment_allowed else 1
    if args.ops_command == "position-adjustment-execute":
        report = build_position_adjustment_execute_report(
            config,
            db_path=args.db,
            confirm_token=args.confirm_token,
            now=args.now,
            signed_client=_build_signed_client(config, signed_client_factory),
            market_client=_build_client(config, client_factory),
            service_active=args.service_active,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.adjustment_executed else 1
    if args.ops_command == "time-exit-plan":
        report = build_time_exit_plan_report(
            config,
            db_path=args.db,
            check_binance=not args.skip_binance,
            now=args.now,
            signed_client=_build_signed_client(config, signed_client_factory),
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.exit_allowed else 1
    if args.ops_command == "time-exit-execute":
        report = build_time_exit_execute_report(
            config,
            db_path=args.db,
            confirm_token=args.confirm_token,
            now=args.now,
            signed_client=_build_signed_client(config, signed_client_factory),
            service_active=args.service_active,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.exit_executed else 1
    if args.ops_command == "risk-change-check":
        report = build_risk_change_check_report(
            config,
            db_path=args.db,
            check_binance=not args.skip_binance,
            target_leverage=args.target_leverage,
            signed_client=_build_signed_client(config, signed_client_factory) if not args.skip_binance else None,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.risk_change_allowed else 1
    if args.ops_command == "risk-profile-plan":
        plan = build_risk_profile_plan(
            config,
            profile=args.profile,
            allow_two_positions=args.allow_two_positions,
        )
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0
    if args.ops_command == "risk-profile-apply":
        report = apply_risk_profile(
            config,
            env_path=args.env_file,
            db_path=args.db,
            profile=args.profile,
            confirm_token=args.confirm_token,
            allow_two_positions=args.allow_two_positions,
            service_active=args.service_active,
            signed_client=_build_signed_client(config, signed_client_factory),
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if report.applied else 1
    if args.ops_command == "exposure-status":
        report = build_exposure_status_report(
            config,
            db_path=args.db,
            check_binance=not args.skip_binance,
            signed_client=_build_signed_client(config, signed_client_factory)
            if not args.skip_binance
            else None,
            target_profile=args.target_profile or None,
            allow_two_positions=args.allow_two_positions,
            hypothetical_symbol=args.hypothetical_symbol,
            hypothetical_side=args.hypothetical_side,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0
    return 2


def _run_agent(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
    client_factory,
    collector_factory,
    narrative_runner_factory,
    ai_client_factory,
    signed_client_factory,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    if args.agent_command == "run-once":
        market_client = _build_client(config, client_factory)
        result = run_agent_once(
            config=config,
            db_path=args.db,
            journal_path=args.journal,
            top_n=args.top_n,
            market_client=market_client,
            collector=_build_collector(config, market_client, collector_factory)
            if collector_factory is not None
            else None,
            narrative_runner=_build_narrative_runner(config, narrative_runner_factory)
            if narrative_runner_factory is not None
            else None,
            ai_client=_build_ai_client(config, ai_client_factory)
            if ai_client_factory is not None
            else None,
            signed_client=_build_signed_client(config, signed_client_factory)
            if signed_client_factory is not None
            else None,
        )
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if result.ok else 1
    return 2


def _run_backtest(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
    client_factory,
) -> int:
    if args.backtest_command == "fetch-klines":
        config = load_config(env=env, env_file=args.env_file)
        symbols = _symbols_arg(args.symbols) if args.symbols else market_symbols(config)
        client = _build_client(config, client_factory)
        rows = fetch_historical_klines(
            client,
            symbols=symbols,
            interval=args.interval,
            start=args.start,
            end=args.end,
            limit=args.limit,
        )
        write_klines_dataset(args.output, interval=args.interval, symbols=rows)
        payload = {
            "schema": "bfa_backtest_fetch_klines_v1",
            "output": args.output,
            "interval": args.interval,
            "symbols": symbols,
            "bar_counts": {symbol: len(values) for symbol, values in sorted(rows.items())},
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0

    if args.backtest_command == "run":
        dataset = load_klines_dataset(args.input)
        config = built_in_variants()[args.variant]
        result = run_hot_momentum_backtest(dataset, config)
        payload = result.to_dict(include_trades=args.include_trades)
        _write_optional_json(args.output, payload)
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0

    if args.backtest_command == "sweep":
        dataset = load_klines_dataset(args.input)
        payload = run_staged_sweep(
            dataset,
            window_bars=args.window_bars,
            step_bars=args.step_bars,
            variants=_symbols_arg(args.variants, uppercase=False),
        )
        _write_optional_json(args.output, payload)
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0

    if args.backtest_command == "matrix":
        config = load_config(env=env, env_file=args.env_file)
        matrix_config = BacktestMatrixConfig(
            intervals=tuple(_symbols_arg(args.intervals, uppercase=False)),
            limit=args.limit,
            window_bars=args.window_bars,
            step_bars=args.step_bars,
            variants=tuple(_symbols_arg(args.variants, uppercase=False)),
            hot_universe=HotUniverseConfig(
                top_n=args.top_n,
                min_quote_volume_usdt=args.min_quote_volume_usdt,
                min_abs_price_change_percent=args.min_abs_price_change_percent,
            ),
        )
        payload = run_hot_backtest_matrix(
            _build_client(config, client_factory),
            matrix_config,
            symbols=_symbols_arg(args.symbols) if args.symbols else None,
            start=args.start,
            end=args.end,
        )
        _write_optional_json(args.output, payload)
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return 0

    return 2


def _execution_filters_from_file(path: str, symbol: str) -> SymbolExecutionFilters:
    return SymbolExecutionFilters.from_exchange_info(
        json.loads(Path(path).read_text(encoding="utf-8")),
        symbol,
    )


def _decision_validation_from_json(
    path: Path,
    config: AppConfig,
    symbol: str,
    decided_at: str,
) -> DecisionValidationResult:
    from bfa.ai.decision import validate_decision_payload
    from bfa.ai.schema import AiTradeDecision, DecisionValidationResult, context_from_candidate

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("decision file must contain a JSON object")
    if isinstance(payload.get("decision"), dict):
        decision_payload = payload["decision"]
        decision = AiTradeDecision(
            decision=str(decision_payload.get("decision", "")),
            side=str(decision_payload.get("side", "")),
            confidence=float(decision_payload.get("confidence", 0.0)),
            entry_price=decision_payload.get("entry_price"),
            stop_price=decision_payload.get("stop_price"),
            target_price=decision_payload.get("target_price"),
            notional_usdt=decision_payload.get("notional_usdt"),
            hold_time_minutes=decision_payload.get("hold_time_minutes"),
            reasons=[str(item) for item in decision_payload.get("reasons", [])],
        )
        return DecisionValidationResult(
            accepted=bool(payload.get("accepted")),
            decision=decision,
            validation_errors=[str(item) for item in payload.get("validation_errors", [])],
            validation_warnings=[str(item) for item in payload.get("validation_warnings", [])],
        )
    context = context_from_candidate(
        {"symbol": symbol.upper()},
        risk_limits=RiskLimits.from_config(config),
        decided_at=decided_at,
    )
    return validate_decision_payload(payload, context)


def _candidate_payload_from_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        candidates = payload["candidates"]
        if not candidates:
            raise ValueError("candidate file contains no candidates")
        first = candidates[0]
        if isinstance(first, dict):
            return first
    if isinstance(payload, dict):
        return payload
    raise ValueError("candidate file must contain a JSON object")


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _symbols_arg(value: str, *, uppercase: bool = True) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    return [item.upper() for item in values] if uppercase else values


def _write_optional_json(path: str | None, payload: Mapping[str, object]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
