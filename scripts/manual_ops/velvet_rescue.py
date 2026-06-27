#!/usr/bin/env python3
"""Manual VELVETUSDT hedge rescue monitor.

This is intentionally separate from the normal live strategy. It only manages
the operator-specified VELVETUSDT hedge and records every cycle/action to a
JSONL audit file.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from bfa.config import load_config
from bfa.execution.binance_client import BinanceFuturesSignedClient, BinanceSignedError


SYMBOL = "VELVETUSDT"
STATE_PATH = Path("/opt/binance-futures-agent/runtime/manual-rescue/velvet_state.json")
LOG_PATH = Path("/opt/binance-futures-agent/runtime/manual-rescue/velvet_actions.jsonl")
BASE_PUBLIC = "https://fapi.binance.com"


@dataclass(frozen=True)
class Position:
    side: str
    amount: float
    entry: float
    mark: float
    upnl: float


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def public_get(path: str, params: dict[str, object]) -> object:
    with urlopen(f"{BASE_PUBLIC}{path}?{urlencode(params)}", timeout=10) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def klines(interval: str = "1m", limit: int = 120) -> list[dict[str, float]]:
    raw = public_get("/fapi/v1/klines", {"symbol": SYMBOL, "interval": interval, "limit": limit})
    if not isinstance(raw, list):
        return []
    return [
        {
            "open_time": float(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "quote_volume": float(item[7]),
        }
        for item in raw
    ]


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(max(int(round((len(ordered) - 1) * q)), 0), len(ordered) - 1)
    return ordered[idx]


def market_context() -> dict[str, float]:
    bars1 = klines("1m", 120)
    bars5 = klines("5m", 72)
    if len(bars1) < 30:
        raise RuntimeError("insufficient 1m bars for VELVET rescue")
    closes = [item["close"] for item in bars1]
    ranges = [
        (item["high"] - item["low"]) / max(item["close"], 1e-9) * 100.0
        for item in bars1[-60:]
    ]
    returns = [
        (closes[idx] / closes[idx - 1] - 1.0) * 100.0
        for idx in range(1, len(closes))
        if closes[idx - 1] > 0
    ]
    recent = bars1[-30:]
    hi30 = max(item["high"] for item in recent)
    lo30 = min(item["low"] for item in recent)
    hi120 = max(item["high"] for item in bars1)
    lo120 = min(item["low"] for item in bars1)
    last = closes[-1]
    pos30 = (last - lo30) / (hi30 - lo30) * 100.0 if hi30 > lo30 else 50.0
    pos120 = (last - lo120) / (hi120 - lo120) * 100.0 if hi120 > lo120 else 50.0
    volume_mean_30 = sum(item["quote_volume"] for item in bars1[-30:]) / 30.0
    return {
        "last": last,
        "hi30": hi30,
        "lo30": lo30,
        "hi120": hi120,
        "lo120": lo120,
        "pos30": pos30,
        "pos120": pos120,
        "range_mean_60_pct": sum(ranges) / len(ranges) if ranges else 0.0,
        "range_p90_60_pct": quantile(ranges, 0.9) or 0.0,
        "ret_mean_60_pct": sum(returns[-60:]) / len(returns[-60:]) if returns[-60:] else 0.0,
        "ret_p10_60_pct": quantile(returns[-60:], 0.1) or 0.0,
        "ret_p90_60_pct": quantile(returns[-60:], 0.9) or 0.0,
        "volume_last": bars1[-1]["quote_volume"],
        "volume_mean_30": volume_mean_30,
        "bars5_last_close": bars5[-1]["close"] if bars5 else last,
    }


def build_client() -> BinanceFuturesSignedClient:
    config = load_config(env_file="/etc/binance-futures-agent/env")
    return BinanceFuturesSignedClient(
        base_url=config.get("BINANCE_FUTURES_BASE_URL"),
        api_key=config.get("BINANCE_API_KEY"),
        api_secret=config.get("BINANCE_API_SECRET"),
    )


def positions(client: BinanceFuturesSignedClient) -> dict[str, Position]:
    output: dict[str, Position] = {}
    for item in client.position_risk(SYMBOL):
        amount_signed = float(item.get("positionAmt") or 0.0)
        if abs(amount_signed) <= 0:
            continue
        side = str(item.get("positionSide") or ("LONG" if amount_signed > 0 else "SHORT")).upper()
        output[side] = Position(
            side=side,
            amount=abs(amount_signed),
            entry=float(item.get("entryPrice") or 0.0),
            mark=float(item.get("markPrice") or 0.0),
            upnl=float(item.get("unRealizedProfit") or 0.0),
        )
    return output


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {"reduced": {}, "last_action_at": None, "last_action_epoch": None}
    try:
        loaded = json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {"reduced": {}, "last_action_at": None, "last_action_epoch": None}
    return loaded if isinstance(loaded, dict) else {"reduced": {}, "last_action_at": None, "last_action_epoch": None}


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))


def log_event(payload: dict[str, object]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def round_qty(quantity: float) -> int:
    return max(1, int(math.floor(quantity)))


def reduce_order_params(position: Position) -> dict[str, str]:
    if position.side == "SHORT":
        return {"order_side": "BUY", "position_side": "SHORT"}
    return {"order_side": "SELL", "position_side": "LONG"}


def add_order_params(side: str) -> dict[str, str]:
    if side == "SHORT":
        return {"order_side": "SELL", "position_side": "SHORT"}
    return {"order_side": "BUY", "position_side": "LONG"}


def decide(
    position_by_side: dict[str, Position],
    context: dict[str, float],
    state: dict[str, object],
    *,
    profit_trigger: float,
    drawdown_readd_usdt: float,
    cooldown_seconds: float,
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    now_epoch = time.time()
    last_action = state.get("last_action_epoch")
    cooldown_ok = last_action is None or now_epoch - float(last_action) >= cooldown_seconds
    reduced_state = state.get("reduced")
    reduced = reduced_state if isinstance(reduced_state, dict) else {}
    for side, position in sorted(position_by_side.items()):
        side_reduced = reduced.get(side)
        qty = round_qty(position.amount / 3.0)
        if not side_reduced:
            if position.upnl >= profit_trigger and cooldown_ok and qty > 0:
                params = reduce_order_params(position)
                actions.append(
                    {
                        "action": "reduce_one_third",
                        "side": side,
                        "quantity": qty,
                        "reason": f"{side} upnl {position.upnl:.4f} >= {profit_trigger:.4f}",
                        **params,
                    }
                )
            continue
        if not isinstance(side_reduced, dict):
            continue
        original_qty = int(float(side_reduced.get("quantity") or 0))
        reduce_upnl = float(side_reduced.get("reduce_upnl") or 0.0)
        trigger_upnl = reduce_upnl - drawdown_readd_usdt
        # Re-add only after the leg has given back most locked profit and price
        # is no longer at a pure chase extreme.
        side_extreme_ok = (side == "SHORT" and context["pos30"] >= 45.0) or (
            side == "LONG" and context["pos30"] <= 55.0
        )
        if position.upnl <= trigger_upnl and cooldown_ok and original_qty > 0 and side_extreme_ok:
            params = add_order_params(side)
            actions.append(
                {
                    "action": "readd_reduced_third",
                    "side": side,
                    "quantity": original_qty,
                    "reason": (
                        f"{side} upnl {position.upnl:.4f} <= readd trigger {trigger_upnl:.4f} "
                        f"and pos30 {context['pos30']:.1f}"
                    ),
                    **params,
                }
            )
    return actions


def execute_action(client: BinanceFuturesSignedClient, action: dict[str, object], *, execute: bool) -> dict[str, object]:
    if not execute:
        return {"dry_run": True}
    return client.new_order(
        symbol=SYMBOL,
        side=str(action["order_side"]),
        order_type="MARKET",
        quantity=float(action["quantity"]),
        position_side=str(action["position_side"]),
        new_client_order_id=f"bfa-velvet-rescue-{int(time.time())}-{str(action['action'])[:6]}",
    )


def one_cycle(args: argparse.Namespace) -> None:
    client = build_client()
    position_by_side = positions(client)
    context = market_context()
    state = load_state()
    actions = decide(
        position_by_side,
        context,
        state,
        profit_trigger=args.profit_trigger,
        drawdown_readd_usdt=args.drawdown_readd,
        cooldown_seconds=args.cooldown_seconds,
    )
    event: dict[str, object] = {
        "ts": utc_now(),
        "symbol": SYMBOL,
        "execute": bool(args.execute),
        "positions": {side: asdict(position) for side, position in position_by_side.items()},
        "context": context,
        "state_before": state,
        "actions": actions,
    }
    for action in actions[:1]:
        try:
            action["response"] = execute_action(client, action, execute=bool(args.execute))
            if args.execute:
                state["last_action_epoch"] = time.time()
                state["last_action_at"] = utc_now()
                state_reduced = state.setdefault("reduced", {})
                if not isinstance(state_reduced, dict):
                    state_reduced = {}
                    state["reduced"] = state_reduced
                if action["action"] == "reduce_one_third":
                    side = str(action["side"])
                    state_reduced[side] = {
                        "quantity": int(float(action["quantity"])),
                        "reduce_upnl": position_by_side[side].upnl,
                        "reduced_at": utc_now(),
                    }
                elif action["action"] == "readd_reduced_third":
                    state_reduced.pop(str(action["side"]), None)
                save_state(state)
        except BinanceSignedError as exc:
            action["error"] = {
                "status": exc.status_code,
                "code": exc.binance_code,
                "message": exc.binance_message,
            }
    event["state_after"] = load_state()
    log_event(event)
    print(json.dumps(event, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--profit-trigger", type=float, default=10.0)
    parser.add_argument("--drawdown-readd", type=float, default=8.0)
    parser.add_argument("--cooldown-seconds", type=float, default=45.0)
    args = parser.parse_args()
    if args.once:
        one_cycle(args)
        return
    while True:
        one_cycle(args)
        time.sleep(max(args.interval, 5.0))


if __name__ == "__main__":
    main()
