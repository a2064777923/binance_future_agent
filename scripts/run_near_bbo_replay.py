"""Run the fixed multi-date, multi-symbol offline near-BBO replay.

Inputs may be public aggTrades or compatible self-collected individual ticks.
This entry point is research-only.  It never imports an exchange client and
never places, cancels, or inspects live orders.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bfa.backtest.near_bbo_replay import (  # noqa: E402
    NearBboReplayConfig,
    ReplayWindow,
    aggregate_variant_reports,
    available_symbols,
    default_variants,
    default_windows,
    days_for_range,
    fill_audit_variants,
    load_eligibility_schedule,
    replay_window,
    select_symbols_for_window,
    utc_ms,
)


def _window_spec(raw: str) -> ReplayWindow:
    parts = [item.strip() for item in raw.split(",")]
    if len(parts) != 3 or not all(parts):
        raise ValueError("window must be NAME,START_ISO,END_ISO")
    return ReplayWindow(parts[0], utc_ms(parts[1]), utc_ms(parts[2]))


def _parse_symbols(raw: str) -> tuple[str, ...]:
    symbols = tuple(dict.fromkeys(item.strip().upper() for item in raw.split(",") if item.strip()))
    if not symbols:
        raise ValueError("--symbols must contain at least one symbol")
    return symbols


def _selected_variants(raw: str) -> tuple[Any, ...]:
    variants = {item.name: item for item in (*default_variants(), *fill_audit_variants())}
    names = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not names:
        raise ValueError("at least one variant is required")
    unknown = [name for name in names if name not in variants]
    if unknown:
        raise ValueError(f"unknown variants: {', '.join(unknown)}")
    return tuple(variants[name] for name in names)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default="runtime/aggTrades-cache")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--window",
        action="append",
        help="NAME,START_ISO,END_ISO; repeat to override the five predeclared windows",
    )
    parser.add_argument("--symbols", help="same comma-separated symbols for every window (optional)")
    parser.add_argument(
        "--eligibility-schedule",
        action="append",
        help="market-scan JSON containing a prior-only schedule-v2; repeat for more dates",
    )
    parser.add_argument("--require-complete-schedule", action="store_true")
    parser.add_argument("--symbols-per-window", type=int, default=24)
    parser.add_argument(
        "--variants",
        default="touch_upper_bound,queue_1pct,queue_10pct,displayed_queue",
    )
    parser.add_argument(
        "--data-source-kind",
        choices=[
            "public_aggtrades",
            "self_collected_individual_ticks",
            "other_aggtrade_compatible",
        ],
        default="public_aggtrades",
    )
    parser.add_argument("--account-capital-usdt", type=float, default=400.0)
    parser.add_argument("--notional-usdt", type=float, default=120.0)
    parser.add_argument("--pending-capacity", type=int, default=3)
    parser.add_argument("--warmup-minutes", type=int, default=15)
    parser.add_argument("--evaluation-interval-ms", type=int, default=3_000)
    parser.add_argument("--quote-ttl-ms", type=int, default=20_000)
    parser.add_argument("--max-hold-ms", type=int, default=30_000)
    parser.add_argument("--post-window-ms", type=int, default=55_000)
    parser.add_argument("--setup-mode", choices=["legacy", "article_v2"], default="article_v2")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        cache_dir = Path(args.cache_dir)
        windows = tuple(_window_spec(item) for item in args.window) if args.window else default_windows()
        variants = _selected_variants(args.variants)
        if args.symbols_per_window <= 0:
            raise ValueError("--symbols-per-window must be positive")
        replay_config = NearBboReplayConfig(
            account_capital_usdt=float(args.account_capital_usdt),
            notional_usdt=float(args.notional_usdt),
            max_active_intents=int(args.pending_capacity),
            warmup_ms=int(args.warmup_minutes) * 60_000,
            evaluation_interval_ms=int(args.evaluation_interval_ms),
            quote_ttl_ms=int(args.quote_ttl_ms),
            max_hold_ms=int(args.max_hold_ms),
            post_window_ms=int(args.post_window_ms),
            setup_mode=str(args.setup_mode),
            data_source_kind=str(args.data_source_kind),
        )
        eligibility_schedule = (
            load_eligibility_schedule(args.eligibility_schedule)
            if args.eligibility_schedule
            else None
        )
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))

    fixed_symbols = _parse_symbols(args.symbols) if args.symbols else None
    window_reports: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    for index, window in enumerate(windows, start=1):
        required_days = days_for_range(
            window.start_ms - replay_config.warmup_ms,
            window.end_ms + replay_config.post_window_ms,
        )
        candidates = set(available_symbols(cache_dir, required_days))
        missing: list[str] = []
        if eligibility_schedule is not None:
            scheduled = set(
                eligibility_schedule.symbols_for_range(window.start_ms, window.end_ms)
            )
            requested = scheduled.intersection(fixed_symbols) if fixed_symbols else scheduled
            missing = sorted(requested.difference(candidates))
            if missing and args.require_complete_schedule:
                raise SystemExit(
                    f"window {window.name} lacks {len(missing)} scheduled cached archives"
                )
            symbols = tuple(sorted(requested.intersection(candidates)))
            selection_mode = "prior_only_market_opportunity_schedule"
        elif fixed_symbols is not None:
            symbols = fixed_symbols
            missing = sorted(set(symbols).difference(candidates))
            if missing:
                raise SystemExit(
                    f"window {window.name} lacks cached archives for symbols: {', '.join(missing)}"
                )
            selection_mode = "explicit"
        else:
            symbols = select_symbols_for_window(
                cache_dir,
                window,
                limit=int(args.symbols_per_window),
                warmup_ms=replay_config.warmup_ms,
                post_window_ms=replay_config.post_window_ms,
            )
            selection_mode = "stable_sha256_intersection"
        if not symbols:
            raise SystemExit(f"window {window.name} has no common cached symbols")
        selections.append(
            {
                "name": window.name,
                "symbols": list(symbols),
                "selection": selection_mode,
                "missing_scheduled_symbols": missing,
            }
        )
        if not args.quiet:
            print(f"[{index}/{len(windows)}] replay {window.name}: {len(symbols)} symbols", flush=True)
        window_reports.append(
            replay_window(
                cache_dir,
                window,
                symbols=symbols,
                variants=variants,
                config=replay_config,
                eligibility_schedule=eligibility_schedule,
            )
        )

    payload = {
        "schema": "bfa_near_bbo_historical_multiwindow_v1",
        "execution_mode": "offline_trade_data_research_only_no_orders",
        "replay_config": asdict(replay_config),
        "variants": [asdict(item) for item in variants],
        "predeclared_windows": [
            {"name": item.name, "start": item.start_ms, "end": item.end_ms} for item in windows
        ],
        "symbol_selections": selections,
        "eligibility_schedule": {
            "enabled": eligibility_schedule is not None,
            "sources": list(eligibility_schedule.sources) if eligibility_schedule else [],
        },
        "windows": window_reports,
        "aggregate": aggregate_variant_reports(window_reports),
        "limitations": [
            "Trade-only replay sources provide no historical BBO/L2/queue state.",
            "Synthetic BBO variants are sensitivity scenarios, not exchange reconstruction.",
            "Results are not a live promotion decision; live and sentinel remain separate and stopped.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    if not args.quiet:
        compact = {
            name: report.get("metrics")
            for name, report in payload["aggregate"].items()
        }
        print(json.dumps({"output": str(output), "aggregate": compact}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
