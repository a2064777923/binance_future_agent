"""Command-line utilities for local foundation checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from bfa.config import AppConfig, load_config, market_symbols, validate_config
from bfa.market.binance_rest import BinanceFuturesRestClient
from bfa.market.collector import MarketDataCollector
from bfa.market.snapshot_writer import write_jsonl_snapshots


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    client_factory=None,
    collector_factory=None,
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


if __name__ == "__main__":
    raise SystemExit(main())
