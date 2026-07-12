"""Run a public-data-only near-BBO forward shadow; this script cannot trade."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bfa.backtest.near_bbo_shadow import NearBboShadowConfig, NearBboShadowLedger  # noqa: E402
from bfa.market.binance_ws import (  # noqa: E402
    book_ticker_stream,
    combined_stream_url,
    next_reconnect_delay,
    trade_stream,
)
from bfa.strategy.near_bbo_scalp import NearBboConfig, NearBboUniverse  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="comma-separated public Binance USD-M symbols (max 80)")
    parser.add_argument("--output", required=True, help="final JSON summary path")
    parser.add_argument("--events-output", help="optional JSONL shadow decisions/outcomes")
    parser.add_argument("--base-url", default="wss://fstream.binance.com")
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument("--evaluation-interval-ms", type=int, default=3_000)
    parser.add_argument("--max-symbols", type=int, default=80)
    parser.add_argument("--pending-capacity", type=int, default=3)
    parser.add_argument("--account-capital-usdt", type=float, default=400.0)
    parser.add_argument("--notional-usdt", type=float, default=120.0)
    parser.add_argument("--quote-ttl-ms", type=int, default=5_000)
    parser.add_argument("--max-hold-ms", type=int, default=30_000)
    parser.add_argument("--min-top-notional-usdt", type=float, default=1_000.0)
    parser.add_argument("--min-fill-probability", type=float, default=0.15)
    parser.add_argument("--min-win-probability", type=float, default=0.60)
    parser.add_argument("--min-net-ev-bps", type=float, default=0.50)
    parser.add_argument("--maker-entry-fee-bps", type=float, default=2.0)
    parser.add_argument("--maker-exit-fee-bps", type=float, default=2.0)
    parser.add_argument("--taker-exit-fee-bps", type=float, default=4.0)
    parser.add_argument("--taker-exit-probability", type=float, default=0.35)
    parser.add_argument("--exit-slippage-bps", type=float, default=0.5)
    parser.add_argument("--queue-ahead-fraction", type=float, default=1.0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    payload = asyncio.run(run_shadow(args))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    if not args.quiet:
        print(json.dumps({"output": str(output), "summary": payload["summary"]}, indent=2, sort_keys=True))
    return 0


async def run_shadow(args: argparse.Namespace) -> dict[str, Any]:
    try:
        import websockets
    except Exception as exc:  # noqa: BLE001 - explicit runtime dependency error.
        raise SystemExit("websockets is required for the public near-BBO shadow") from exc

    symbols = parse_symbols(args.symbols, max_symbols=max(1, int(args.max_symbols)))
    strategy_config = NearBboConfig(
        quote_ttl_ms=max(1, int(args.quote_ttl_ms)),
        max_pending_orders=max(1, int(args.pending_capacity)),
        min_top_notional_usdt=max(0.0, float(args.min_top_notional_usdt)),
        min_fill_probability=max(0.0, float(args.min_fill_probability)),
        min_win_probability=max(0.0, float(args.min_win_probability)),
        min_conditional_net_ev_bps=float(args.min_net_ev_bps),
        queue_ahead_fraction=max(0.01, float(args.queue_ahead_fraction)),
        maker_entry_fee_bps=max(0.0, float(args.maker_entry_fee_bps)),
        maker_exit_fee_bps=max(0.0, float(args.maker_exit_fee_bps)),
        taker_exit_fee_bps=max(0.0, float(args.taker_exit_fee_bps)),
        taker_exit_probability=float(args.taker_exit_probability),
        exit_slippage_bps=max(0.0, float(args.exit_slippage_bps)),
    )
    shadow_config = NearBboShadowConfig(
        account_capital_usdt=float(args.account_capital_usdt),
        notional_usdt=float(args.notional_usdt),
        max_active_intents=max(1, int(args.pending_capacity)),
        max_hold_ms=max(1, int(args.max_hold_ms)),
    )
    universe = NearBboUniverse(strategy_config)
    ledger = NearBboShadowLedger(shadow_config, strategy_config=strategy_config)
    evaluation_interval = max(100, int(args.evaluation_interval_ms)) / 1_000.0
    duration_seconds = max(0.0, float(args.duration_seconds))
    deadline = time.monotonic() + duration_seconds if duration_seconds > 0 else None
    next_evaluation = time.monotonic() + evaluation_interval
    websocket_url = combined_stream_url(args.base_url, list(build_streams(symbols)))
    message_count = 0
    book_count = 0
    trade_count = 0
    ignored_count = 0
    evaluation_count = 0
    missed_evaluation_count = 0
    evaluation_durations_ms: list[float] = []
    latest_event_ms: int | None = None
    latest_rank_diagnostics: dict[str, Any] = {}
    connection_count = 0
    reconnect_count = 0
    connection_errors: list[dict[str, Any]] = []
    event_handle = None
    if args.events_output:
        event_path = Path(args.events_output)
        event_path.parent.mkdir(parents=True, exist_ok=True)
        event_handle = event_path.open("w", encoding="utf-8")

    async def consume_connection(websocket) -> None:
        nonlocal message_count, book_count, trade_count, ignored_count
        nonlocal evaluation_count, missed_evaluation_count, latest_event_ms
        nonlocal latest_rank_diagnostics, next_evaluation
        while deadline is None or time.monotonic() < deadline:
            now = time.monotonic()
            wait_until = next_evaluation
            if deadline is not None:
                wait_until = min(wait_until, deadline)
            timeout = max(0.01, wait_until - now)
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                message = None
            if message is not None:
                message_count += 1
                event = ingest_public_message(message, universe=universe, ledger=ledger)
                event_type = str(event.get("event_type") or "ignored")
                event_ms = _int_or_none(event.get("event_time_ms"))
                if event_ms is not None:
                    latest_event_ms = max(latest_event_ms or event_ms, event_ms)
                if event_type == "bookTicker":
                    book_count += 1
                elif event_type == "trade":
                    trade_count += 1
                else:
                    ignored_count += 1
                outcomes = event.get("outcomes") or ()
                if outcomes and event_handle is not None:
                    for outcome in outcomes:
                        _write_event(event_handle, {"type": "outcome", "outcome": outcome.to_dict()})

            now = time.monotonic()
            if now < next_evaluation:
                continue
            if now - next_evaluation >= evaluation_interval:
                missed_evaluation_count += int((now - next_evaluation) // evaluation_interval)
            evaluation_now_ms = evaluation_time_ms(latest_event_ms=latest_event_ms)
            evaluation_started = time.perf_counter()
            closed = ledger.advance(evaluation_now_ms)
            proposals, latest_rank_diagnostics = universe.rank_opportunities(
                now_ms=evaluation_now_ms,
                excluded_symbols=ledger.active_symbols,
                capacity=ledger.available_capacity,
            )
            admitted = ledger.admit(proposals)
            elapsed_ms = (time.perf_counter() - evaluation_started) * 1_000.0
            evaluation_durations_ms.append(elapsed_ms)
            evaluation_count += 1
            if event_handle is not None and (admitted or closed or evaluation_count % 20 == 0):
                _write_event(
                    event_handle,
                    {
                        "type": "evaluation",
                        "event_time_ms": evaluation_now_ms,
                        "rank": latest_rank_diagnostics,
                        "admitted": [asdict(item) for item in admitted],
                        "closed": [item.to_dict() for item in closed],
                        "summary": ledger.summary(now_ms=evaluation_now_ms),
                    },
                )
            next_evaluation += evaluation_interval
            if next_evaluation <= now:
                next_evaluation = now + evaluation_interval

    started_wall_ms = int(time.time() * 1_000)
    reconnect_attempt = 0
    try:
        from websockets.exceptions import ConnectionClosed

        while deadline is None or time.monotonic() < deadline:
            try:
                async with websockets.connect(
                    websocket_url,
                    compression=None,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=2,
                    max_queue=4096,
                ) as websocket:
                    connection_count += 1
                    await consume_connection(websocket)
                    reconnect_attempt = 0
            except (ConnectionClosed, OSError) as exc:
                reconnect_count += 1
                connection_errors.append(
                    {
                        "type": exc.__class__.__name__,
                        "close_code": getattr(exc, "code", None),
                    }
                )
                connection_errors[:] = connection_errors[-20:]
                if event_handle is not None:
                    _write_event(
                        event_handle,
                        {
                            "type": "connection_error",
                            "error": connection_errors[-1],
                            "reconnect_count": reconnect_count,
                        },
                    )
            if deadline is not None and time.monotonic() >= deadline:
                break
            delay = next_reconnect_delay(reconnect_attempt, initial_delay=0.5, max_delay=10.0)
            reconnect_attempt += 1
            if deadline is not None:
                delay = min(delay, max(0.0, deadline - time.monotonic()))
            if delay > 0:
                await asyncio.sleep(delay)
    finally:
        if event_handle is not None:
            event_handle.close()

    ended_wall_ms = int(time.time() * 1_000)
    final_now_ms = evaluation_time_ms(
        latest_event_ms=latest_event_ms,
        wall_time_ms=ended_wall_ms,
    )
    ledger.advance(final_now_ms)
    return {
        "schema": "bfa_near_bbo_public_shadow_v1",
        "execution_mode": "public_data_shadow_no_orders",
        "symbols": list(symbols),
        "strategy_config": asdict(strategy_config),
        "shadow_config": asdict(shadow_config),
        "summary": ledger.summary(now_ms=final_now_ms),
        "latest_rank_diagnostics": latest_rank_diagnostics,
        "performance": {
            "started_wall_ms": started_wall_ms,
            "ended_wall_ms": ended_wall_ms,
            "message_count": message_count,
            "book_ticker_count": book_count,
            "trade_count": trade_count,
            "ignored_count": ignored_count,
            "evaluation_count": evaluation_count,
            "missed_evaluation_count": missed_evaluation_count,
            "connection_count": connection_count,
            "reconnect_count": reconnect_count,
            "connection_errors": connection_errors,
            "evaluation_ms_p50": _percentile(evaluation_durations_ms, 0.50),
            "evaluation_ms_p95": _percentile(evaluation_durations_ms, 0.95),
            "evaluation_ms_max": max(evaluation_durations_ms) if evaluation_durations_ms else None,
        },
        "outcomes": [item.to_dict() for item in ledger.outcomes],
        "limitations": [
            "win/fill probabilities are uncalibrated heuristics until enough forward labels exist",
            "top-of-book queue quantity is a conservative proxy, not authenticated exchange queue position",
            "bookTicker plus trades cannot distinguish every cancellation from consumed queue",
            "target and stop exits do not model authenticated exchange queue priority",
            "shadow results do not authorize testnet or live execution",
        ],
    }


def parse_symbols(raw: str, *, max_symbols: int = 80) -> tuple[str, ...]:
    symbols = tuple(dict.fromkeys(value.strip().upper() for value in raw.split(",") if value.strip()))
    if not symbols:
        raise ValueError("at least one symbol is required")
    if len(symbols) > max(1, int(max_symbols)):
        raise ValueError(f"symbol watch universe exceeds max {max_symbols}")
    return symbols


def build_streams(symbols: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    streams: list[str] = []
    for symbol in symbols:
        streams.extend((book_ticker_stream(symbol), trade_stream(symbol)))
    return tuple(streams)


def ingest_public_message(
    message: Mapping[str, Any] | str | bytes,
    *,
    universe: Any,
    ledger: Any,
) -> dict[str, Any]:
    payload = _json_mapping(message)
    if payload is None:
        return {"event_type": "ignored", "reason": "invalid_json"}
    raw_data = payload.get("data")
    data = raw_data if isinstance(raw_data, Mapping) else payload
    stream = str(payload.get("stream") or "")
    event_type = str(data.get("e") or "")
    if not event_type and "@bookticker" in stream.lower():
        event_type = "bookTicker"
    elif not event_type and "@trade" in stream.lower():
        event_type = "trade"
    symbol = str(data.get("s") or (stream.split("@", 1)[0] if "@" in stream else "")).upper()
    event_time_ms = _int_or_none(data.get("T") or data.get("E"))
    if not symbol or event_time_ms is None:
        return {"event_type": "ignored", "reason": "missing_symbol_or_time"}
    if event_type == "bookTicker":
        accepted = universe.ingest_book_ticker(
            symbol=symbol,
            event_time_ms=event_time_ms,
            bid_price=_float_or_zero(data.get("b")),
            bid_quantity=_float_or_zero(data.get("B")),
            ask_price=_float_or_zero(data.get("a")),
            ask_quantity=_float_or_zero(data.get("A")),
        )
        return {"event_type": event_type if accepted else "ignored", "event_time_ms": event_time_ms, "symbol": symbol}
    if event_type == "trade":
        price = _float_or_zero(data.get("p"))
        quantity = _float_or_zero(data.get("q"))
        taker_buy = not bool(data.get("m"))
        accepted = universe.ingest_trade(
            symbol=symbol,
            event_time_ms=event_time_ms,
            price=price,
            quantity=quantity,
            taker_buy=taker_buy,
        )
        outcomes = ledger.on_trade(
            symbol=symbol,
            event_time_ms=event_time_ms,
            price=price,
            quantity=quantity,
            taker_buy=taker_buy,
        )
        return {
            "event_type": event_type if accepted else "ignored",
            "event_time_ms": event_time_ms,
            "symbol": symbol,
            "outcomes": outcomes,
        }
    return {"event_type": "ignored", "event_time_ms": event_time_ms, "symbol": symbol, "reason": "unsupported_event"}


def _json_mapping(message: Mapping[str, Any] | str | bytes) -> Mapping[str, Any] | None:
    if isinstance(message, Mapping):
        return message
    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="replace")
    try:
        loaded = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, Mapping) else None


def _write_event(handle, payload: Mapping[str, Any]) -> None:
    handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n")
    handle.flush()


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def evaluation_time_ms(*, latest_event_ms: int | None, wall_time_ms: int | None = None) -> int:
    """Advance freshness even when a connected stream silently stops sending."""

    wall_ms = int(time.time() * 1_000) if wall_time_ms is None else int(wall_time_ms)
    return max(wall_ms, int(latest_event_ms or 0))


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


if __name__ == "__main__":
    raise SystemExit(main())
