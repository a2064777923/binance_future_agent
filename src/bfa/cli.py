"""Command-line utilities for local foundation checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from bfa.config import AppConfig, load_config, market_symbols, rss_feed_urls, validate_config
from bfa.event_store.migrations import connect, migrate
from bfa.event_store.report import generate_review_report
from bfa.event_store.store import EventStore
from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.market.collector import MarketDataCollector
from bfa.market.snapshot_writer import write_jsonl_snapshots
from bfa.narrative.collector import NarrativeCollectionRunner
from bfa.narrative.manual import ManualExportCollector
from bfa.narrative.rss import RssFeedCollector
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


if __name__ == "__main__":
    raise SystemExit(main())
