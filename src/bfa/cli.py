"""Command-line utilities for local foundation checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from bfa.agent import run_agent_once
from bfa.ai.client import OpenAIResponsesClient
from bfa.ai.decision import run_ai_decision
from bfa.ai.journal import AiDecisionJournal
from bfa.ai.schema import RiskLimits, context_from_candidate
from bfa.config import AppConfig, load_config, market_symbols, rss_feed_urls, validate_config
from bfa.event_store.migrations import connect, migrate
from bfa.event_store.report import generate_review_report
from bfa.event_store.store import EventStore
from bfa.execution.binance_client import BinanceFuturesSignedClient
from bfa.execution.executor import ExecutionEngine
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import RiskState
from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.market.collector import MarketDataCollector
from bfa.market.snapshot_writer import write_jsonl_snapshots
from bfa.narrative.collector import NarrativeCollectionRunner
from bfa.narrative.manual import ManualExportCollector
from bfa.narrative.rss import RssFeedCollector
from bfa.ops.health import run_health_checks
from bfa.strategy.candidates import StrategyConfig, generate_candidates
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
        help="OpenAI structured decision-layer smoke commands",
    )
    ai_subparsers = ai.add_subparsers(dest="ai_command", required=True)
    decide = ai_subparsers.add_parser(
        "decide",
        help="ask OpenAI for a structured decision for one candidate JSON payload",
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
    health.add_argument("--check-openai", action="store_true", help="check OpenAI Responses API when enabled")
    health.add_argument("--skip-network", action="store_true", help="disable all network health checks")

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
        result = generate_candidates(
            replay_packet,
            StrategyConfig(
                allowed_symbols=market_symbols(config),
                generated_at=args.generated_at,
                top_n=args.top_n,
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
        context = context_from_candidate(
            candidate,
            risk_limits=RiskLimits.from_config(config),
            decided_at=args.decided_at,
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
            )
        finally:
            if connection is not None:
                connection.close()
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True), file=stdout)
        return 0 if result.validation.accepted else 1
    return 2


def _build_ai_client(config: AppConfig, ai_client_factory):
    if ai_client_factory is not None:
        return ai_client_factory(config)
    return OpenAIResponsesClient(
        api_key=config.get("OPENAI_API_KEY"),
        model=config.get("OPENAI_MODEL"),
        timeout=float(config.get("OPENAI_TIMEOUT_SECONDS")),
        max_output_tokens=int(config.get("OPENAI_MAX_OUTPUT_TOKENS")),
    )


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


if __name__ == "__main__":
    raise SystemExit(main())
