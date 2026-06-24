"""Export a live-trading audit packet from the server DB and Binance klines.

The script intentionally keeps secrets on the server. It uses SSH to run
read-only SQLite and Binance signed-client queries, then writes local CSVs.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


BINANCE_FAPI = "https://fapi.binance.com"


@dataclass(frozen=True)
class Remote:
    host: str
    user: str
    key: str
    app_dir: str
    python: str
    db: str
    env_file: str

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="64.83.34.222")
    parser.add_argument("--user", default="root")
    parser.add_argument("--ssh-key", default=str(Path.home() / ".ssh" / "id_ed25519_bfa"))
    parser.add_argument("--app-dir", default="/opt/binance-futures-agent/app")
    parser.add_argument("--python", default="/opt/binance-futures-agent/.venv/bin/python")
    parser.add_argument("--db", default="/opt/binance-futures-agent/data/agent.sqlite")
    parser.add_argument("--env-file", default="/etc/binance-futures-agent/env")
    parser.add_argument("--since", default="2026-06-23T13:21:00Z")
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    remote = Remote(
        host=args.host,
        user=args.user,
        key=args.ssh_key,
        app_dir=args.app_dir,
        python=args.python,
        db=args.db,
        env_file=args.env_file,
    )
    since = parse_iso(args.since)
    generated_at = datetime.now(UTC)
    out_dir = Path(args.out_dir) if args.out_dir else Path.cwd() / "results" / f"live_audit_{generated_at:%Y%m%d_%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = {
        "order_intents": query_table(remote, "order_intents", since),
        "trade_setups": query_table(remote, "trade_setups", since),
        "ai_decisions": query_table(remote, "ai_decisions", since),
        "exchange_responses": query_table(remote, "exchange_responses", since),
        "outcomes": query_table(remote, "outcomes", since),
    }

    intents = [normalize_row(row) for row in raw["order_intents"]]
    setups = [normalize_row(row) for row in raw["trade_setups"]]
    decisions = [normalize_row(row) for row in raw["ai_decisions"]]
    responses = [normalize_row(row) for row in raw["exchange_responses"]]
    outcomes = [normalize_row(row) for row in raw["outcomes"]]

    symbols = sorted({str(row["symbol"]).upper() for row in intents if row.get("symbol")})
    remote_state = read_exchange_state(
        remote,
        symbols=symbols,
        start_ms=int((since - timedelta(minutes=5)).timestamp() * 1000),
        end_ms=int((generated_at + timedelta(minutes=5)).timestamp() * 1000),
    )

    setup_index = build_artifact_index(setups)
    decision_index = build_artifact_index(decisions)
    responses_by_key = index_exchange_responses(responses)
    outcomes_by_event = index_outcomes(outcomes)
    trades_by_symbol = {
        symbol.upper(): sorted(items, key=lambda item: int(item.get("time") or 0))
        for symbol, items in (remote_state.get("trades") or {}).items()
    }

    operation_rows: list[dict[str, Any]] = []
    operations_for_paths: list[dict[str, Any]] = []
    for row in intents:
        payload = row["payload"]
        intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
        symbol = str(row.get("symbol") or intent.get("symbol") or "").upper()
        if not symbol:
            continue
        decided_at = str(intent.get("decided_at") or row["occurred_at"])
        setup = lookup_artifact(setup_index, symbol, decided_at)
        ai_decision = lookup_artifact(decision_index, symbol, decided_at)
        matched_responses = lookup_exchange_responses(responses_by_key, symbol, intent)
        entry_response = first_response(matched_responses, "new_order")
        watchdog_response = first_response(matched_responses, "pending_limit_watchdog")
        adjustment_response = first_response(matched_responses, "position_adjustment")
        outcome = outcomes_by_event.get(int_or_none(row.get("event_id")) or -1)

        entry_order_id = extract_entry_order_id(entry_response)
        trade_summary = summarize_operation_trades(
            symbol=symbol,
            intent=intent,
            entry_order_id=entry_order_id,
            trades=trades_by_symbol.get(symbol, []),
            started_at=parse_iso(str(row["occurred_at"])),
            now=generated_at,
        )
        if outcome is not None:
            trade_summary.update(summary_from_outcome(outcome["payload"]))

        operation = build_operation_row(
            row=row,
            intent=intent,
            setup=setup["payload"] if setup else {},
            ai_decision=ai_decision["payload"] if ai_decision else {},
            entry_response=entry_response,
            watchdog_response=watchdog_response,
            adjustment_response=adjustment_response,
            outcome=outcome["payload"] if outcome else {},
            trade_summary=trade_summary,
            generated_at=generated_at,
        )
        operation_rows.append(operation)
        operations_for_paths.append(operation)

    kline_cache: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    minute_rows: list[dict[str, Any]] = []
    for operation in operations_for_paths:
        window_start, window_end = operation_window(operation, generated_at)
        if window_end < window_start:
            window_end = window_start
        klines = fetch_klines_cached(kline_cache, operation["symbol"], window_start, window_end)
        minute_rows.extend(build_minute_rows(operation, klines))

    analysis_rows = build_analysis_rows(operation_rows, minute_rows)

    operation_csv = out_dir / "live_trade_operations.csv"
    minute_csv = out_dir / "live_trade_minute_path.csv"
    analysis_csv = out_dir / "live_trade_analysis.csv"
    combined_csv = out_dir / "live_trade_audit_combined.csv"
    write_csv(operation_csv, operation_rows)
    write_csv(minute_csv, minute_rows)
    write_csv(analysis_csv, analysis_rows)
    write_combined_csv(combined_csv, operation_rows, minute_rows)

    metadata = {
        "generated_at": iso(generated_at),
        "since": iso(since),
        "operation_count": len(operation_rows),
        "minute_row_count": len(minute_rows),
        "symbols": symbols,
        "files": {
            "operations": str(operation_csv),
            "minute_path": str(minute_csv),
            "analysis": str(analysis_csv),
            "combined": str(combined_csv),
        },
        "summary": summarize_packet(operation_rows, analysis_rows),
    }
    (out_dir / "live_trade_audit_summary.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


def query_table(remote: Remote, table: str, since: datetime) -> list[dict[str, Any]]:
    sql = f"""
    SELECT id, event_id, occurred_at, source, symbol, ref_id, payload_json
    FROM {table}
    WHERE occurred_at >= '{iso(since)}'
    ORDER BY occurred_at ASC, id ASC
    """
    stdout = run_remote(remote, f"sqlite3 -json {shlex.quote(remote.db)} {shlex.quote(sql)}")
    return json.loads(stdout or "[]")


def read_exchange_state(remote: Remote, *, symbols: list[str], start_ms: int, end_ms: int) -> dict[str, Any]:
    script = f"""
import json
from bfa.config import load_config
from bfa.execution.binance_client import BinanceFuturesSignedClient

config = load_config(env_file={remote.env_file!r})
client = BinanceFuturesSignedClient(
    base_url=config.get("BINANCE_FUTURES_BASE_URL"),
    api_key=config.get("BINANCE_API_KEY"),
    api_secret=config.get("BINANCE_API_SECRET"),
)
symbols = {json.dumps(symbols)}
out = {{"trades": {{}}, "positions": [], "open_orders": [], "open_algo_orders": []}}
for symbol in symbols:
    try:
        out["trades"][symbol] = client.user_trades(symbol, start_time={start_ms}, end_time={end_ms}, limit=1000)
    except Exception as exc:
        out["trades"][symbol] = [{{"audit_error": str(exc)}}]
try:
    out["positions"] = client.position_risk()
except Exception as exc:
    out["positions"] = [{{"audit_error": str(exc)}}]
try:
    out["open_orders"] = client.open_orders()
except Exception as exc:
    out["open_orders"] = [{{"audit_error": str(exc)}}]
try:
    out["open_algo_orders"] = client.open_algo_orders()
except Exception as exc:
    out["open_algo_orders"] = [{{"audit_error": str(exc)}}]
print(json.dumps(out, ensure_ascii=False))
"""
    cmd = f"cd {shlex.quote(remote.app_dir)} && {shlex.quote(remote.python)} - <<'PY'\n{script}\nPY"
    stdout = run_remote(remote, cmd)
    return json.loads(stdout or "{}")


def run_remote(remote: Remote, command: str) -> str:
    proc = subprocess.run(
        [
            "ssh",
            "-i",
            remote.key,
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            remote.target,
            command,
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"remote command failed: {proc.stderr.strip()}")
    return proc.stdout


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload_json")
    if isinstance(payload, str):
        try:
            row["payload"] = json.loads(payload)
        except json.JSONDecodeError:
            row["payload"] = {}
    else:
        row["payload"] = payload if isinstance(payload, dict) else {}
    row.pop("payload_json", None)
    return row


def build_artifact_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        occurred_at = str(row.get("occurred_at") or "")
        if symbol and occurred_at:
            index[(symbol, occurred_at)] = row
    return index


def lookup_artifact(index: dict[tuple[str, str], dict[str, Any]], symbol: str, decided_at: str) -> dict[str, Any] | None:
    return index.get((symbol.upper(), normalize_iso_text(decided_at)))


def index_exchange_responses(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        payload = row["payload"]
        intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
        key = response_key(intent)
        if key[0]:
            index.setdefault(key, []).append(row)
    return index


def response_key(intent: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(intent.get("symbol") or "").upper(),
        normalize_iso_text(str(intent.get("decided_at") or "")),
        str(intent.get("side") or "").upper(),
        fmt_num(intent.get("entry_price")),
        fmt_num(intent.get("quantity")),
    )


def lookup_exchange_responses(
    index: dict[tuple[str, str, str, str, str], list[dict[str, Any]]],
    symbol: str,
    intent: dict[str, Any],
) -> list[dict[str, Any]]:
    return index.get(response_key({**intent, "symbol": symbol}), [])


def first_response(rows: list[dict[str, Any]], response_type: str) -> dict[str, Any] | None:
    for row in rows:
        actual = str(row["payload"].get("response_type") or "")
        if response_type == "position_adjustment":
            if actual.startswith("position_adjustment"):
                return row
        elif actual == response_type:
            return row
    return None


def index_outcomes(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out = {}
    for row in rows:
        event_id = deep_get(row["payload"], "intent", "event_id")
        if event_id is not None:
            out[int(event_id)] = row
    return out


def extract_entry_order_id(response_row: dict[str, Any] | None) -> int | None:
    payload = response_row["payload"] if response_row else {}
    response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
    final = response.get("entry_order_final") if isinstance(response.get("entry_order_final"), dict) else {}
    entry = response.get("entry_order") if isinstance(response.get("entry_order"), dict) else {}
    return int_or_none(final.get("orderId") or entry.get("orderId"))


def summarize_operation_trades(
    *,
    symbol: str,
    intent: dict[str, Any],
    entry_order_id: int | None,
    trades: list[dict[str, Any]],
    started_at: datetime,
    now: datetime,
) -> dict[str, Any]:
    if not entry_order_id:
        return {"trade_status": "no_entry_order_id", "trade_count": 0}
    relevant = [trade for trade in trades if int_or_none(trade.get("orderId")) == entry_order_id]
    if not relevant:
        return {"trade_status": "no_entry_fill_seen", "trade_count": 0}
    entry_time = min(int(trade.get("time") or 0) for trade in relevant)
    side = str(intent.get("side") or "").upper()
    position_side = "LONG" if side == "BUY" else "SHORT"
    intended_qty = float_or_zero(intent.get("quantity"))
    signed_open = intended_qty if side == "BUY" else -intended_qty
    cumulative = 0.0
    included: list[dict[str, Any]] = []
    started = False
    for trade in trades:
        trade_time = int_or_none(trade.get("time")) or 0
        if trade_time < entry_time:
            continue
        if str(trade.get("positionSide") or "").upper() not in {"", "BOTH", position_side}:
            continue
        qty = float_or_zero(trade.get("qty"))
        trade_side = str(trade.get("side") or "").upper()
        signed = qty if trade_side == "BUY" else -qty
        if not started:
            if int_or_none(trade.get("orderId")) != entry_order_id:
                continue
            started = True
        included.append(trade)
        cumulative += signed
        if abs(cumulative) < max(1e-9, abs(signed_open) * 0.000001) and len(included) > len(relevant):
            break
    gross = sum(float_or_zero(trade.get("realizedPnl")) for trade in included)
    fees = sum(float_or_zero(trade.get("commission")) for trade in included if str(trade.get("commissionAsset") or "USDT").upper() == "USDT")
    net_qty = sum((float_or_zero(trade.get("qty")) if str(trade.get("side") or "").upper() == "BUY" else -float_or_zero(trade.get("qty"))) for trade in included)
    closed = bool(included) and abs(net_qty) < max(1e-9, abs(signed_open) * 0.000001)
    first_trade = min((int_or_none(trade.get("time")) or 0) for trade in included) if included else None
    last_trade = max((int_or_none(trade.get("time")) or 0) for trade in included) if included else None
    avg_entry = weighted_avg([trade for trade in included if int_or_none(trade.get("orderId")) == entry_order_id])
    exit_trades = [trade for trade in included if int_or_none(trade.get("orderId")) != entry_order_id]
    avg_exit = weighted_avg(exit_trades)
    return {
        "trade_status": "closed" if closed else "open_or_partial",
        "trade_count": len(included),
        "first_trade_time": epoch_ms_to_iso(first_trade),
        "last_trade_time": epoch_ms_to_iso(last_trade),
        "avg_entry_fill_price": round(avg_entry, 12) if avg_entry is not None else "",
        "avg_exit_fill_price": round(avg_exit, 12) if avg_exit is not None else "",
        "net_quantity_signed": round(net_qty, 12),
        "gross_realized_pnl_usdt": round(gross, 8),
        "commission_usdt": round(fees, 8),
        "net_realized_pnl_usdt": round(gross - fees, 8),
        "included_trade_ids": "|".join(str(trade.get("id")) for trade in included),
        "audit_now": iso(now),
        "audit_started_at": iso(started_at),
    }


def summary_from_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    trades = payload.get("trades") if isinstance(payload.get("trades"), list) else []
    return {
        "trade_status": payload.get("status"),
        "trade_count": payload.get("trade_count"),
        "first_trade_time": payload.get("first_trade_time"),
        "last_trade_time": payload.get("last_trade_time"),
        "gross_realized_pnl_usdt": payload.get("gross_realized_pnl_usdt"),
        "commission_usdt": payload.get("commission_usdt"),
        "net_realized_pnl_usdt": payload.get("net_realized_pnl_usdt"),
        "net_quantity_signed": payload.get("net_quantity"),
        "included_trade_ids": "|".join(str(trade.get("trade_id")) for trade in trades if isinstance(trade, dict)),
    }


def build_operation_row(
    *,
    row: dict[str, Any],
    intent: dict[str, Any],
    setup: dict[str, Any],
    ai_decision: dict[str, Any],
    entry_response: dict[str, Any] | None,
    watchdog_response: dict[str, Any] | None,
    adjustment_response: dict[str, Any] | None,
    outcome: dict[str, Any],
    trade_summary: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    setup_payload = setup.get("setup") if isinstance(setup.get("setup"), dict) else {}
    candidate = setup.get("candidate") if isinstance(setup.get("candidate"), dict) else {}
    features = candidate.get("features") if isinstance(candidate.get("features"), dict) else {}
    price_basis = setup_payload.get("price_basis") if isinstance(setup_payload.get("price_basis"), dict) else {}
    factor_summary = setup_payload.get("factor_summary") if isinstance(setup_payload.get("factor_summary"), dict) else {}
    signal = price_basis.get("signal_diagnostics") if isinstance(price_basis.get("signal_diagnostics"), dict) else {}
    entry_quality = signal.get("entry_quality") if isinstance(signal.get("entry_quality"), dict) else {}
    limit_quality = price_basis.get("limit_entry_quality") if isinstance(price_basis.get("limit_entry_quality"), dict) else {}
    sizing = price_basis.get("adaptive_sizing_governor") if isinstance(price_basis.get("adaptive_sizing_governor"), dict) else {}
    sizing_diag = sizing.get("diagnostics") if isinstance(sizing.get("diagnostics"), dict) else {}
    route = price_basis.get("regime_router") if isinstance(price_basis.get("regime_router"), dict) else {}
    entry_basis = price_basis.get("entry_basis") if isinstance(price_basis.get("entry_basis"), dict) else {}
    stop_basis = price_basis.get("stop_basis") if isinstance(price_basis.get("stop_basis"), dict) else {}
    target_basis = price_basis.get("target_basis") if isinstance(price_basis.get("target_basis"), dict) else {}
    response_payload = entry_response["payload"] if entry_response else {}
    response = response_payload.get("response") if isinstance(response_payload.get("response"), dict) else {}
    entry_order = response.get("entry_order") if isinstance(response.get("entry_order"), dict) else {}
    entry_final = response.get("entry_order_final") if isinstance(response.get("entry_order_final"), dict) else {}
    stop_order = response.get("stop_loss_order") if isinstance(response.get("stop_loss_order"), dict) else {}
    target_order = response.get("take_profit_order") if isinstance(response.get("take_profit_order"), dict) else {}
    post_only = deep_get(intent, "metadata", "post_only_reprice") or deep_get(entry_order, "post_only_reprice") or {}
    validation = ai_decision.get("validation") if isinstance(ai_decision.get("validation"), dict) else {}
    ai_validation_decision = validation.get("decision") if isinstance(validation.get("decision"), dict) else {}
    risk = row["payload"].get("risk") if isinstance(row["payload"].get("risk"), dict) else {}
    op_type = classify_operation(row["payload"], entry_response, watchdog_response, adjustment_response)
    side = str(intent.get("side") or "").upper()
    direction = "long" if side == "BUY" else "short" if side == "SELL" else ""
    exit_class = classify_exit(direction, float_or_none(intent.get("stop_price")), float_or_none(intent.get("target_price")), float_or_none(trade_summary.get("avg_exit_fill_price")), trade_summary.get("trade_status"))
    return {
        "operation_id": f"op-{row['event_id']}",
        "event_id": row.get("event_id"),
        "intent_row_id": row.get("id"),
        "operation_type": op_type,
        "occurred_at_utc": normalize_iso_text(str(row.get("occurred_at"))),
        "decided_at_utc": normalize_iso_text(str(intent.get("decided_at") or row.get("occurred_at"))),
        "generated_audit_at_utc": iso(generated_at),
        "symbol": str(row.get("symbol") or intent.get("symbol") or "").upper(),
        "direction": direction,
        "side": side,
        "intent_status": row["payload"].get("status"),
        "risk_accepted": risk.get("accepted"),
        "risk_reason_codes": join_list(risk.get("reason_codes")),
        "risk_warnings": join_list(risk.get("warnings")),
        "order_type": intent.get("order_type"),
        "time_in_force": intent.get("time_in_force"),
        "quantity": intent.get("quantity"),
        "leverage": intent.get("leverage"),
        "notional_usdt": intent.get("notional_usdt"),
        "estimated_initial_margin_usdt": intent.get("estimated_initial_margin_usdt"),
        "entry_price": intent.get("entry_price"),
        "stop_price": intent.get("stop_price"),
        "target_price": intent.get("target_price"),
        "limit_wait_seconds": intent.get("limit_wait_seconds"),
        "setup_decision": setup_payload.get("decision"),
        "setup_confidence": setup_payload.get("confidence"),
        "edge_score": setup_payload.get("edge_score"),
        "long_score": setup_payload.get("long_score"),
        "short_score": setup_payload.get("short_score"),
        "selected_side": deep_get(factor_summary, "selected_side"),
        "risk_reward_ratio": setup_payload.get("risk_reward_ratio"),
        "stop_distance_percent": setup_payload.get("stop_distance_percent"),
        "target_distance_percent": setup_payload.get("target_distance_percent"),
        "regime_label": route.get("regime_label") or features.get("regime_label"),
        "regime_confidence": route.get("regime_confidence") or features.get("regime_confidence"),
        "route_decision": route.get("route_decision") or features.get("route_decision"),
        "route_shadow_only": route.get("route_shadow_only") if route else features.get("route_shadow_only"),
        "strategy_leg": route.get("strategy_leg") or features.get("strategy_leg"),
        "allowed_strategy_legs": join_list(route.get("allowed_strategy_legs") or features.get("allowed_strategy_legs")),
        "regime_reason_codes": join_list(route.get("regime_reason_codes") or features.get("regime_reason_codes")),
        "reason_codes": join_list(intent.get("reason_codes") or setup_payload.get("reasons")),
        "candidate_reason_codes": join_list(candidate.get("reason_codes")),
        "top_factors": top_factors_text(factor_summary.get("top_factors")),
        "factor_group_trend_net": deep_get(factor_summary, "group_totals", "trend_momentum", "net"),
        "factor_group_flow_net": deep_get(factor_summary, "group_totals", "flow", "net"),
        "factor_group_volume_net": deep_get(factor_summary, "group_totals", "volume", "net"),
        "factor_group_positioning_net": deep_get(factor_summary, "group_totals", "positioning", "net"),
        "factor_group_liquidity_net": deep_get(factor_summary, "group_totals", "liquidity_tradability", "net"),
        "factor_group_volatility_net": deep_get(factor_summary, "group_totals", "volatility_range", "net"),
        "reference_price": price_basis.get("reference_price") or features.get("reference_price"),
        "vwap": price_basis.get("vwap") or features.get("vwap"),
        "support_price": price_basis.get("support_price") or features.get("support_price"),
        "resistance_price": price_basis.get("resistance_price") or features.get("resistance_price"),
        "rsi": price_basis.get("rsi") or features.get("rsi"),
        "atr_percent": price_basis.get("atr_percent") or features.get("atr_percent"),
        "realized_volatility_percent": features.get("realized_volatility_percent"),
        "ema_spread_percent": price_basis.get("ema_spread_percent") or features.get("ema_spread_percent"),
        "kline_momentum_percent": features.get("kline_momentum_percent"),
        "kline_micro_momentum_percent": features.get("kline_micro_momentum_percent"),
        "kline_close_position_percent": features.get("kline_close_position_percent"),
        "kline_range_percent": features.get("kline_range_percent"),
        "quote_volume": features.get("quote_volume"),
        "open_interest_value": features.get("open_interest_value"),
        "open_interest_change_percent": features.get("open_interest_change_percent"),
        "taker_buy_sell_ratio": features.get("taker_buy_sell_ratio"),
        "taker_buy_sell_ratio_change": features.get("taker_buy_sell_ratio_change"),
        "entry_anchor": entry_basis.get("anchor"),
        "entry_offset_percent": entry_basis.get("offset_percent"),
        "limit_entry_quality_score": limit_quality.get("score"),
        "limit_entry_quality_checks": checks_text(limit_quality.get("checks")),
        "entry_quality_score": entry_quality.get("score"),
        "entry_quality_checks": checks_text(entry_quality.get("checks")),
        "stop_anchor": stop_basis.get("anchor"),
        "stop_raw_distance_percent": stop_basis.get("raw_stop_distance_percent"),
        "stop_was_capped": stop_basis.get("was_capped"),
        "target_anchor": target_basis.get("anchor"),
        "target_raw_distance_percent": target_basis.get("raw_target_distance_percent"),
        "target_was_capped": target_basis.get("was_capped"),
        "post_cost_target_to_cost_ratio": deep_get(price_basis, "post_cost_edge", "target_to_cost_ratio"),
        "sizing_multiplier": sizing.get("multiplier"),
        "sizing_components": json_compact(sizing.get("components")),
        "sizing_reason_codes": join_list(sizing.get("reason_codes")),
        "sizing_available_balance_usdt": deep_get(sizing_diag, "component_inputs", "account_available_balance_usdt"),
        "sizing_portfolio_remaining_margin_usdt": sizing_diag.get("portfolio_remaining_margin_usdt"),
        "sizing_stop_risk_notional_usdt": deep_get(sizing_diag, "hard_cap_candidates", "stop_risk_notional"),
        "ai_validation_accepted": validation.get("accepted"),
        "ai_model": deep_get(ai_decision, "response", "model"),
        "ai_decision": ai_validation_decision.get("decision"),
        "ai_confidence": ai_validation_decision.get("confidence"),
        "ai_reasons": join_list(ai_validation_decision.get("reasons")),
        "exchange_response_type": response_payload.get("response_type"),
        "entry_order_id": entry_final.get("orderId") or entry_order.get("orderId"),
        "client_order_id": entry_final.get("clientOrderId") or entry_order.get("clientOrderId"),
        "entry_order_status_initial": entry_order.get("status"),
        "entry_order_status_final": entry_final.get("status"),
        "entry_order_created_time_utc": epoch_ms_to_iso(entry_order.get("time") or entry_order.get("updateTime")),
        "entry_order_final_time_utc": epoch_ms_to_iso(entry_final.get("time") or entry_final.get("updateTime")),
        "entry_order_final_avg_price": entry_final.get("avgPrice"),
        "entry_order_executed_qty": entry_final.get("executedQty") or entry_order.get("executedQty"),
        "post_only_reprice_attempts": post_only_attempts_text(post_only),
        "stop_algo_status": stop_order.get("algoStatus") or deep_get(watchdog_response or {}, "payload", "response", "stop_loss_order", "algoStatus"),
        "stop_algo_trigger": stop_order.get("triggerPrice") or deep_get(watchdog_response or {}, "payload", "response", "stop_loss_order", "triggerPrice"),
        "take_profit_algo_status": target_order.get("algoStatus") or deep_get(watchdog_response or {}, "payload", "response", "take_profit_order", "algoStatus"),
        "take_profit_algo_trigger": target_order.get("triggerPrice") or deep_get(watchdog_response or {}, "payload", "response", "take_profit_order", "triggerPrice"),
        "watchdog_response_event_id": watchdog_response.get("event_id") if watchdog_response else "",
        "adjustment_response_event_id": adjustment_response.get("event_id") if adjustment_response else "",
        "trade_status": trade_summary.get("trade_status"),
        "trade_count": trade_summary.get("trade_count"),
        "first_trade_time_utc": trade_summary.get("first_trade_time"),
        "last_trade_time_utc": trade_summary.get("last_trade_time"),
        "avg_entry_fill_price": trade_summary.get("avg_entry_fill_price"),
        "avg_exit_fill_price": trade_summary.get("avg_exit_fill_price"),
        "exit_classification": exit_class,
        "net_quantity_signed": trade_summary.get("net_quantity_signed"),
        "gross_realized_pnl_usdt": trade_summary.get("gross_realized_pnl_usdt"),
        "commission_usdt": trade_summary.get("commission_usdt"),
        "net_realized_pnl_usdt": trade_summary.get("net_realized_pnl_usdt"),
        "included_trade_ids": trade_summary.get("included_trade_ids"),
    }


def classify_operation(
    payload: dict[str, Any],
    entry_response: dict[str, Any] | None,
    watchdog_response: dict[str, Any] | None,
    adjustment_response: dict[str, Any] | None,
) -> str:
    status = str(payload.get("status") or "")
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    order_type = str(intent.get("order_type") or "")
    if order_type.startswith("ALGO_") or status.startswith("position_adjustment") or adjustment_response is not None:
        return "position_management"
    if watchdog_response is not None and entry_response is None:
        return "watchdog_protection_backfill"
    if status == "rejected":
        return "rejected_before_order"
    if status == "entry_order_expired_canceled":
        return "entry_limit_expired_canceled"
    if status == "entry_order_pending":
        return "entry_limit_pending_then_watchdog"
    if status == "submitted" and entry_response is not None:
        return "entry_order_submitted"
    return status or "unknown"


def classify_exit(direction: str, stop: float | None, target: float | None, avg_exit: float | None, status: Any) -> str:
    if str(status) != "closed" or avg_exit is None:
        return ""
    if direction == "long":
        if stop is not None and avg_exit <= stop * 1.002:
            return "stop_loss"
        if target is not None and avg_exit >= target * 0.998:
            return "take_profit"
    if direction == "short":
        if stop is not None and avg_exit >= stop * 0.998:
            return "stop_loss"
        if target is not None and avg_exit <= target * 1.002:
            return "take_profit"
    return "closed_other"


def operation_window(operation: dict[str, Any], now: datetime) -> tuple[datetime, datetime]:
    order_at = parse_iso(str(operation["occurred_at_utc"]))
    first_trade = parse_iso_or_none(operation.get("first_trade_time_utc"))
    last_trade = parse_iso_or_none(operation.get("last_trade_time_utc"))
    entry_final = parse_iso_or_none(operation.get("entry_order_final_time_utc"))
    trade_status = str(operation.get("trade_status") or "")
    start = order_at - timedelta(minutes=15)
    if trade_status == "closed" and last_trade is not None:
        end = last_trade + timedelta(minutes=15)
    elif operation.get("intent_status") == "entry_order_expired_canceled" and entry_final is not None:
        end = entry_final + timedelta(minutes=15)
    elif operation.get("intent_status") == "rejected":
        end = order_at + timedelta(minutes=15)
    else:
        end = now
    if first_trade and first_trade < start:
        start = first_trade - timedelta(minutes=15)
    return start, end


def fetch_klines_cached(cache: dict[tuple[str, int, int], list[dict[str, Any]]], symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    start_ms = floor_minute_ms(start)
    end_ms = ceil_minute_ms(end)
    key = (symbol.upper(), start_ms, end_ms)
    if key in cache:
        return cache[key]
    params = {
        "symbol": symbol.upper(),
        "interval": "1m",
        "startTime": str(start_ms),
        "endTime": str(end_ms),
        "limit": "1500",
    }
    url = f"{BINANCE_FAPI}/fapi/v1/klines?{urlencode(params)}"
    with urlopen(url, timeout=20) as response:  # noqa: S310 - Binance public REST.
        payload = json.loads(response.read().decode("utf-8"))
    rows = []
    for item in payload:
        open_time = int(item[0])
        high = float(item[2])
        low = float(item[3])
        rows.append(
            {
                "minute_open_time_utc": epoch_ms_to_iso(open_time),
                "open_time_ms": open_time,
                "open": float(item[1]),
                "high": high,
                "low": low,
                "midpoint": (high + low) / 2.0,
                "close": float(item[4]),
                "volume": float(item[5]),
                "quote_volume": float(item[7]),
                "trade_count": int(item[8]),
                "taker_buy_base_volume": float(item[9]),
                "taker_buy_quote_volume": float(item[10]),
            }
        )
    time.sleep(0.05)
    cache[key] = rows
    return rows


def build_minute_rows(operation: dict[str, Any], klines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order_at = parse_iso(str(operation["occurred_at_utc"]))
    first_trade = parse_iso_or_none(operation.get("first_trade_time_utc"))
    last_trade = parse_iso_or_none(operation.get("last_trade_time_utc"))
    stop = float_or_none(operation.get("stop_price"))
    target = float_or_none(operation.get("target_price"))
    entry = float_or_none(operation.get("entry_price"))
    direction = str(operation.get("direction") or "")
    out = []
    for bar in klines:
        t = parse_iso(str(bar["minute_open_time_utc"]))
        phase = "pre_order"
        if first_trade and t >= floor_minute(first_trade):
            phase = "in_trade"
        elif t >= floor_minute(order_at):
            phase = "order_active_or_post_order"
        if last_trade and t > floor_minute(last_trade):
            phase = "post_exit"
        touched_entry = entry is not None and bar["low"] <= entry <= bar["high"]
        if direction == "long":
            touched_stop = stop is not None and bar["low"] <= stop
            touched_target = target is not None and bar["high"] >= target
            favorable_percent = pct((bar["high"] - (entry or bar["open"])) / (entry or bar["open"]))
            adverse_percent = pct(((entry or bar["open"]) - bar["low"]) / (entry or bar["open"]))
        elif direction == "short":
            touched_stop = stop is not None and bar["high"] >= stop
            touched_target = target is not None and bar["low"] <= target
            favorable_percent = pct(((entry or bar["open"]) - bar["low"]) / (entry or bar["open"]))
            adverse_percent = pct((bar["high"] - (entry or bar["open"])) / (entry or bar["open"]))
        else:
            touched_stop = False
            touched_target = False
            favorable_percent = ""
            adverse_percent = ""
        out.append(
            {
                "operation_id": operation["operation_id"],
                "event_id": operation["event_id"],
                "symbol": operation["symbol"],
                "direction": direction,
                "operation_type": operation["operation_type"],
                "intent_status": operation["intent_status"],
                "order_time_utc": operation["occurred_at_utc"],
                "first_trade_time_utc": operation.get("first_trade_time_utc") or "",
                "last_trade_time_utc": operation.get("last_trade_time_utc") or "",
                "minute_open_time_utc": bar["minute_open_time_utc"],
                "minute_offset_from_order": int((t - floor_minute(order_at)).total_seconds() // 60),
                "minute_offset_from_first_trade": "" if first_trade is None else int((t - floor_minute(first_trade)).total_seconds() // 60),
                "phase": phase,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "midpoint": bar["midpoint"],
                "close": bar["close"],
                "volume": bar["volume"],
                "quote_volume": bar["quote_volume"],
                "trade_count": bar["trade_count"],
                "taker_buy_quote_volume": bar["taker_buy_quote_volume"],
                "entry_price": entry if entry is not None else "",
                "stop_price": stop if stop is not None else "",
                "target_price": target if target is not None else "",
                "touched_entry": touched_entry,
                "touched_stop": touched_stop,
                "touched_target": touched_target,
                "favorable_excursion_percent_from_entry": favorable_percent,
                "adverse_excursion_percent_from_entry": adverse_percent,
            }
        )
    return out


def build_analysis_rows(operations: list[dict[str, Any]], minute_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_op: dict[str, list[dict[str, Any]]] = {}
    for row in minute_rows:
        by_op.setdefault(str(row["operation_id"]), []).append(row)
    analysis = []
    for op in operations:
        rows = by_op.get(str(op["operation_id"]), [])
        active = [row for row in rows if row["phase"] in {"in_trade", "post_exit"}]
        in_trade = [row for row in rows if row["phase"] == "in_trade"]
        after_order = [row for row in rows if row["minute_offset_from_order"] >= 0]
        first_target = first_touch(after_order, "touched_target")
        first_stop = first_touch(after_order, "touched_stop")
        post_exit_target = any(bool(row["touched_target"]) for row in rows if row["phase"] == "post_exit")
        post_exit_stop = any(bool(row["touched_stop"]) for row in rows if row["phase"] == "post_exit")
        max_fav = max_float(row.get("favorable_excursion_percent_from_entry") for row in active)
        max_adv = max_float(row.get("adverse_excursion_percent_from_entry") for row in active)
        first_touch_result = ""
        if first_target is not None and first_stop is not None:
            first_touch_result = "target_first" if first_target <= first_stop else "stop_first"
        elif first_target is not None:
            first_touch_result = "target_only"
        elif first_stop is not None:
            first_touch_result = "stop_only"
        analysis.append(
            {
                "operation_id": op["operation_id"],
                "event_id": op["event_id"],
                "symbol": op["symbol"],
                "direction": op["direction"],
                "operation_type": op["operation_type"],
                "intent_status": op["intent_status"],
                "trade_status": op.get("trade_status"),
                "exit_classification": op.get("exit_classification"),
                "net_realized_pnl_usdt": op.get("net_realized_pnl_usdt"),
                "commission_usdt": op.get("commission_usdt"),
                "entry_price": op.get("entry_price"),
                "stop_price": op.get("stop_price"),
                "target_price": op.get("target_price"),
                "first_touch_after_order": first_touch_result,
                "first_target_touch_minute_offset": first_target if first_target is not None else "",
                "first_stop_touch_minute_offset": first_stop if first_stop is not None else "",
                "post_exit_target_touched_within_window": post_exit_target,
                "post_exit_stop_touched_within_window": post_exit_stop,
                "max_favorable_excursion_percent": max_fav,
                "max_adverse_excursion_percent": max_adv,
                "in_trade_minutes_available": len(in_trade),
                "path_minutes_available": len(rows),
                "regime_label": op.get("regime_label"),
                "strategy_leg": op.get("strategy_leg"),
                "edge_score": op.get("edge_score"),
                "entry_quality_score": op.get("entry_quality_score"),
                "limit_entry_quality_score": op.get("limit_entry_quality_score"),
                "top_factors": op.get("top_factors"),
                "audit_note": analysis_note(op, first_touch_result, post_exit_target, max_fav, max_adv),
            }
        )
    return analysis


def first_touch(rows: list[dict[str, Any]], key: str) -> int | None:
    for row in rows:
        if bool(row.get(key)):
            return int(row["minute_offset_from_order"])
    return None


def analysis_note(op: dict[str, Any], touch: str, post_exit_target: bool, max_fav: Any, max_adv: Any) -> str:
    status = str(op.get("trade_status") or "")
    exit_class = str(op.get("exit_classification") or "")
    if status == "closed" and exit_class == "stop_loss" and post_exit_target:
        return "stopped_then_later_target_touched_in_window"
    if status == "closed" and exit_class == "stop_loss":
        return "stopped_without_target_touch_in_window"
    if status == "closed" and exit_class == "take_profit":
        return "target_closed"
    if "expired" in str(op.get("intent_status") or ""):
        return "limit_not_filled"
    if str(op.get("intent_status") or "") == "rejected":
        return "blocked_before_order"
    if status == "open_or_partial":
        return "still_open_or_partial_at_audit"
    return touch or "no_clear_touch"


def summarize_packet(operations: list[dict[str, Any]], analysis: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [op for op in operations if op.get("trade_status") == "closed"]
    submitted = [op for op in operations if op.get("intent_status") == "submitted"]
    return {
        "operations": len(operations),
        "submitted_status_rows": len(submitted),
        "closed_rows": len(closed),
        "closed_net_pnl_usdt": round(sum(float_or_zero(op.get("net_realized_pnl_usdt")) for op in closed), 8),
        "closed_fees_usdt": round(sum(float_or_zero(op.get("commission_usdt")) for op in closed), 8),
        "by_intent_status": counts(op.get("intent_status") for op in operations),
        "by_operation_type": counts(op.get("operation_type") for op in operations),
        "by_trade_status": counts(op.get("trade_status") for op in operations),
        "analysis_notes": counts(row.get("audit_note") for row in analysis),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_combined_csv(path: Path, operations: list[dict[str, Any]], minute_rows: list[dict[str, Any]]) -> None:
    operations_by_id = {str(row["operation_id"]): row for row in operations}
    operation_fields = [
        "operation_id",
        "event_id",
        "operation_type",
        "occurred_at_utc",
        "decided_at_utc",
        "symbol",
        "direction",
        "side",
        "intent_status",
        "risk_accepted",
        "risk_reason_codes",
        "order_type",
        "time_in_force",
        "quantity",
        "leverage",
        "notional_usdt",
        "estimated_initial_margin_usdt",
        "entry_price",
        "stop_price",
        "target_price",
        "limit_wait_seconds",
        "setup_decision",
        "setup_confidence",
        "edge_score",
        "long_score",
        "short_score",
        "risk_reward_ratio",
        "stop_distance_percent",
        "target_distance_percent",
        "regime_label",
        "regime_confidence",
        "route_decision",
        "strategy_leg",
        "regime_reason_codes",
        "reason_codes",
        "top_factors",
        "factor_group_trend_net",
        "factor_group_flow_net",
        "factor_group_volume_net",
        "factor_group_positioning_net",
        "factor_group_liquidity_net",
        "factor_group_volatility_net",
        "reference_price",
        "vwap",
        "support_price",
        "resistance_price",
        "rsi",
        "atr_percent",
        "realized_volatility_percent",
        "ema_spread_percent",
        "kline_momentum_percent",
        "kline_micro_momentum_percent",
        "kline_close_position_percent",
        "kline_range_percent",
        "quote_volume",
        "open_interest_value",
        "open_interest_change_percent",
        "taker_buy_sell_ratio",
        "taker_buy_sell_ratio_change",
        "entry_anchor",
        "entry_offset_percent",
        "limit_entry_quality_score",
        "limit_entry_quality_checks",
        "entry_quality_score",
        "entry_quality_checks",
        "stop_anchor",
        "stop_raw_distance_percent",
        "target_anchor",
        "target_raw_distance_percent",
        "post_cost_target_to_cost_ratio",
        "sizing_multiplier",
        "sizing_components",
        "sizing_reason_codes",
        "sizing_available_balance_usdt",
        "sizing_portfolio_remaining_margin_usdt",
        "ai_validation_accepted",
        "ai_model",
        "ai_decision",
        "ai_confidence",
        "ai_reasons",
        "exchange_response_type",
        "entry_order_id",
        "client_order_id",
        "entry_order_status_initial",
        "entry_order_status_final",
        "entry_order_created_time_utc",
        "entry_order_final_time_utc",
        "entry_order_final_avg_price",
        "entry_order_executed_qty",
        "post_only_reprice_attempts",
        "stop_algo_status",
        "stop_algo_trigger",
        "take_profit_algo_status",
        "take_profit_algo_trigger",
        "trade_status",
        "trade_count",
        "first_trade_time_utc",
        "last_trade_time_utc",
        "avg_entry_fill_price",
        "avg_exit_fill_price",
        "exit_classification",
        "net_quantity_signed",
        "gross_realized_pnl_usdt",
        "commission_usdt",
        "net_realized_pnl_usdt",
    ]
    minute_field_map = {
        "minute_open_time_utc": "minute_open_time_utc",
        "minute_offset_from_order": "minute_offset_from_order",
        "minute_offset_from_first_trade": "minute_offset_from_first_trade",
        "phase": "minute_phase",
        "open": "minute_open",
        "high": "minute_high",
        "low": "minute_low",
        "midpoint": "minute_midpoint",
        "close": "minute_close",
        "volume": "minute_volume",
        "quote_volume": "minute_quote_volume",
        "trade_count": "minute_trade_count",
        "taker_buy_quote_volume": "minute_taker_buy_quote_volume",
        "touched_entry": "minute_touched_entry",
        "touched_stop": "minute_touched_stop",
        "touched_target": "minute_touched_target",
        "favorable_excursion_percent_from_entry": "minute_favorable_excursion_percent_from_entry",
        "adverse_excursion_percent_from_entry": "minute_adverse_excursion_percent_from_entry",
    }
    fields = operation_fields + list(minute_field_map.values())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for minute in minute_rows:
            combined = {key: operations_by_id.get(str(minute.get("operation_id")), {}).get(key, "") for key in operation_fields}
            for source, target in minute_field_map.items():
                combined[target] = minute.get(source, "")
            writer.writerow(combined)


def weighted_avg(trades: list[dict[str, Any]]) -> float | None:
    total_qty = sum(float_or_zero(trade.get("qty")) for trade in trades)
    if total_qty <= 0:
        return None
    return sum(float_or_zero(trade.get("price")) * float_or_zero(trade.get("qty")) for trade in trades) / total_qty


def top_factors_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    parts = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        parts.append(
            f"{item.get('group','')}:{item.get('name','')}:{item.get('polarity','')}:{item.get('weighted_score','')}"
        )
    return " | ".join(parts)


def checks_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        parts.append(f"{item.get('name')}={item.get('passed')}({item.get('value')})")
    return " | ".join(parts)


def post_only_attempts_text(post_only: Any) -> str:
    if not isinstance(post_only, dict):
        return ""
    attempts = post_only.get("attempts")
    if not isinstance(attempts, list):
        return ""
    return " | ".join(
        f"{item.get('attempt')}:{item.get('price')}:{item.get('status')}"
        for item in attempts
        if isinstance(item, dict)
    )


def counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        out[key] = out.get(key, 0) + 1
    return out


def join_list(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def json_compact(value: Any) -> str:
    if value in (None, ""):
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def deep_get(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def fmt_num(value: Any) -> str:
    number = float_or_none(value)
    if number is None:
        return ""
    return f"{number:.12g}"


def float_or_none(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def float_or_zero(value: Any) -> float:
    number = float_or_none(value)
    return 0.0 if number is None else number


def int_or_none(value: Any) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def max_float(values: Any) -> float | str:
    numbers = [float(value) for value in values if value not in ("", None)]
    return round(max(numbers), 8) if numbers else ""


def pct(value: float) -> float:
    return round(value * 100.0, 8)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(normalize_iso_text(value).replace("Z", "+00:00")).astimezone(UTC)


def parse_iso_or_none(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return parse_iso(str(value))
    except ValueError:
        return None


def normalize_iso_text(value: str) -> str:
    if not value:
        return ""
    if value.endswith("+00:00"):
        value = value[:-6] + "Z"
    if "." in value and value.endswith("Z"):
        head, tail = value.split(".", 1)
        frac = tail[:-1]
        if len(frac) > 6:
            frac = frac[:6]
        value = f"{head}.{frac}Z"
    return value


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def epoch_ms_to_iso(value: Any) -> str:
    ms = int_or_none(value)
    if ms is None or ms <= 0:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def floor_minute(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(second=0, microsecond=0)


def floor_minute_ms(value: datetime) -> int:
    return int(floor_minute(value).timestamp() * 1000)


def ceil_minute_ms(value: datetime) -> int:
    floored = floor_minute(value)
    if value > floored:
        floored += timedelta(minutes=1)
    return int(floored.timestamp() * 1000)


if __name__ == "__main__":
    sys.exit(main())
