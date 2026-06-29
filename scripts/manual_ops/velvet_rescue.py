#!/usr/bin/env python3
"""Manual hedge rescue monitor for an operator-specified symbol.

This is intentionally separate from the normal live strategy. It only manages
the operator-specified hedge and records every cycle/action to a
JSONL audit file.
"""

from __future__ import annotations

import argparse
import copy
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


DEFAULT_SYMBOL = "VELVETUSDT"
RUNTIME_DIR = Path("/opt/binance-futures-agent/runtime/manual-rescue")
SYMBOL = DEFAULT_SYMBOL
STATE_PATH = RUNTIME_DIR / "velvet_state.json"
LOG_PATH = RUNTIME_DIR / "velvet_actions.jsonl"
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


def symbol_slug(symbol: str) -> str:
    clean = "".join(ch for ch in symbol.lower() if ch.isalnum())
    return clean[:-4] if clean.endswith("usdt") else clean


def configure_runtime(symbol: str, *, state_file: str | None = None, log_file: str | None = None) -> None:
    global SYMBOL, STATE_PATH, LOG_PATH
    SYMBOL = symbol.upper()
    slug = symbol_slug(SYMBOL)
    STATE_PATH = Path(state_file) if state_file else RUNTIME_DIR / f"{slug}_state.json"
    LOG_PATH = Path(log_file) if log_file else RUNTIME_DIR / f"{slug}_actions.jsonl"


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
        raise RuntimeError(f"insufficient 1m bars for {SYMBOL} rescue")
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
    change_5m = (closes[-1] / closes[-6] - 1.0) * 100.0 if len(closes) >= 6 and closes[-6] > 0 else 0.0
    change_15m = (closes[-1] / closes[-16] - 1.0) * 100.0 if len(closes) >= 16 and closes[-16] > 0 else 0.0
    change_30m = (closes[-1] / closes[-31] - 1.0) * 100.0 if len(closes) >= 31 and closes[-31] > 0 else 0.0
    pullback_from_hi30_pct = (hi30 - last) / max(last, 1e-9) * 100.0
    bounce_from_lo30_pct = (last - lo30) / max(last, 1e-9) * 100.0
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
        "change_5m_pct": change_5m,
        "change_15m_pct": change_15m,
        "change_30m_pct": change_30m,
        "pullback_from_hi30_pct": pullback_from_hi30_pct,
        "bounce_from_lo30_pct": bounce_from_lo30_pct,
        "volume_last": bars1[-1]["quote_volume"],
        "volume_mean_30": volume_mean_30,
        "volume_ratio_30": bars1[-1]["quote_volume"] / volume_mean_30 if volume_mean_30 > 0 else 0.0,
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


def default_state() -> dict[str, object]:
    return {
        "reduced": {},
        "last_action_at": None,
        "last_action_epoch": None,
        "baseline": None,
    }


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return default_state()
    try:
        loaded = json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return default_state()
    return loaded if isinstance(loaded, dict) else default_state()


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))


def log_event(payload: dict[str, object]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def round_qty(quantity: float) -> int:
    return max(1, int(math.floor(quantity)))


def total_upnl(position_by_side: dict[str, Position]) -> float:
    return sum(position.upnl for position in position_by_side.values())


def baseline_snapshot(
    position_by_side: dict[str, Position],
    *,
    source: str,
) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "captured_at": utc_now(),
        "source": source,
        "total_upnl": total_upnl(position_by_side),
    }
    for side in ("LONG", "SHORT"):
        position = position_by_side.get(side)
        snapshot[side] = {
            "amount": float(position.amount if position else 0.0),
            "entry": float(position.entry if position else 0.0),
            "mark": float(position.mark if position else 0.0),
            "upnl": float(position.upnl if position else 0.0),
        }
    return snapshot


def ensure_baseline(
    state: dict[str, object],
    position_by_side: dict[str, Position],
    *,
    source: str,
) -> tuple[dict[str, object], bool]:
    baseline = state.get("baseline")
    if isinstance(baseline, dict):
        return baseline, False
    snapshot = baseline_snapshot(position_by_side, source=source)
    state["baseline"] = snapshot
    return snapshot, True


def progress_against_baseline(
    side: str,
    position_by_side: dict[str, Position],
    baseline: dict[str, object],
) -> dict[str, float]:
    position = position_by_side[side]
    side_baseline = baseline.get(side)
    side_upnl_base = 0.0
    if isinstance(side_baseline, dict):
        side_upnl_base = float(side_baseline.get("upnl") or 0.0)
    baseline_total = float(baseline.get("total_upnl") or 0.0)
    current_total = total_upnl(position_by_side)
    side_delta = position.upnl - side_upnl_base
    book_delta = current_total - baseline_total
    effective_delta = max(side_delta, book_delta)
    return {
        "side_upnl_base": side_upnl_base,
        "baseline_total_upnl": baseline_total,
        "current_total_upnl": current_total,
        "side_delta": side_delta,
        "book_delta": book_delta,
        "effective_delta": effective_delta,
    }


def capped_reduce_quantity(
    side: str,
    position_by_side: dict[str, Position],
    desired_qty: int,
    *,
    max_imbalance_after_reduce: float,
) -> tuple[int, dict[str, float]]:
    long_amount = position_by_side.get("LONG").amount if position_by_side.get("LONG") else 0.0
    short_amount = position_by_side.get("SHORT").amount if position_by_side.get("SHORT") else 0.0
    if side == "LONG":
        long_amount = max(long_amount - desired_qty, 0.0)
    else:
        short_amount = max(short_amount - desired_qty, 0.0)
    max_amount = max(long_amount, short_amount, 1.0)
    imbalance = abs(long_amount - short_amount) / max_amount
    if imbalance <= max_imbalance_after_reduce:
        return desired_qty, {"post_long": long_amount, "post_short": short_amount, "post_imbalance": imbalance}

    # Reduce the profitable leg only as much as the hedge-balance cap allows.
    original_long = position_by_side.get("LONG").amount if position_by_side.get("LONG") else 0.0
    original_short = position_by_side.get("SHORT").amount if position_by_side.get("SHORT") else 0.0
    capped = 0
    for qty in range(desired_qty, 0, -1):
        post_long = max(original_long - qty, 0.0) if side == "LONG" else original_long
        post_short = max(original_short - qty, 0.0) if side == "SHORT" else original_short
        post_max = max(post_long, post_short, 1.0)
        post_imbalance = abs(post_long - post_short) / post_max
        if post_imbalance <= max_imbalance_after_reduce:
            capped = qty
            return capped, {
                "post_long": post_long,
                "post_short": post_short,
                "post_imbalance": post_imbalance,
                "desired_qty": float(desired_qty),
                "capped_by_imbalance": 1.0,
            }
    return 0, {
        "post_long": original_long,
        "post_short": original_short,
        "post_imbalance": abs(original_long - original_short) / max(max(original_long, original_short), 1.0),
        "desired_qty": float(desired_qty),
        "capped_by_imbalance": 1.0,
    }


def reduce_order_params(position: Position) -> dict[str, str]:
    if position.side == "SHORT":
        return {"order_side": "BUY", "position_side": "SHORT"}
    return {"order_side": "SELL", "position_side": "LONG"}


def add_order_params(side: str) -> dict[str, str]:
    if side == "SHORT":
        return {"order_side": "SELL", "position_side": "SHORT"}
    return {"order_side": "BUY", "position_side": "LONG"}


def trend_guard(side: str, context: dict[str, float]) -> dict[str, object]:
    range_mean = max(float(context.get("range_mean_60_pct") or 0.0), 0.1)
    volume_ratio = float(context.get("volume_ratio_30") or 0.0)
    change_5m = float(context.get("change_5m_pct") or 0.0)
    change_15m = float(context.get("change_15m_pct") or 0.0)
    change_30m = float(context.get("change_30m_pct") or 0.0)
    pos30 = float(context.get("pos30") or 50.0)
    pos120 = float(context.get("pos120") or 50.0)
    pullback = float(context.get("pullback_from_hi30_pct") or 0.0)
    bounce = float(context.get("bounce_from_lo30_pct") or 0.0)

    strong_up = (
        change_5m > range_mean * 0.35
        and change_15m > range_mean * 0.75
        and change_30m > range_mean * 0.9
        and pos30 >= 70.0
        and volume_ratio >= 0.65
    )
    strong_down = (
        change_5m < -range_mean * 0.35
        and change_15m < -range_mean * 0.75
        and change_30m < -range_mean * 0.9
        and pos30 <= 30.0
        and volume_ratio >= 0.65
    )
    if side == "LONG":
        at_take_zone = pos30 >= 82.0 or pos120 >= 72.0
        reversal_hint = pullback >= range_mean * 0.18 or change_5m <= 0.0 or volume_ratio <= 0.55
        blocked = strong_up and not reversal_hint
        return {
            "at_take_zone": at_take_zone,
            "reversal_hint": reversal_hint,
            "strong_continuation": strong_up,
            "blocked": blocked or not at_take_zone or not reversal_hint,
            "reason": "long_profit_take_requires_upper_extreme_and_fade",
        }
    at_take_zone = pos30 <= 18.0 or pos120 <= 28.0
    reversal_hint = bounce >= range_mean * 0.18 or change_5m >= 0.0 or volume_ratio <= 0.55
    blocked = strong_down and not reversal_hint
    return {
        "at_take_zone": at_take_zone,
        "reversal_hint": reversal_hint,
        "strong_continuation": strong_down,
        "blocked": blocked or not at_take_zone or not reversal_hint,
        "reason": "short_profit_take_requires_lower_extreme_and_bounce",
    }


def reduced_side_readd_urgent(side: str, context: dict[str, float]) -> bool:
    guard = trend_guard(side, context)
    return bool(guard.get("strong_continuation")) and not bool(guard.get("reversal_hint"))


def trend_rescue_regime(
    position_by_side: dict[str, Position],
    context: dict[str, float],
) -> dict[str, object]:
    range_mean = max(float(context.get("range_mean_60_pct") or 0.0), 0.1)
    change_5m = float(context.get("change_5m_pct") or 0.0)
    change_15m = float(context.get("change_15m_pct") or 0.0)
    change_30m = float(context.get("change_30m_pct") or 0.0)
    pos30 = float(context.get("pos30") or 50.0)
    pos120 = float(context.get("pos120") or 50.0)
    long_position = position_by_side.get("LONG")
    short_position = position_by_side.get("SHORT")
    long_amount = long_position.amount if long_position else 0.0
    short_amount = short_position.amount if short_position else 0.0
    long_upnl = long_position.upnl if long_position else 0.0
    short_upnl = short_position.upnl if short_position else 0.0
    net_amount = long_amount - short_amount
    down_score = 0.0
    up_score = 0.0
    if change_30m <= -range_mean * 0.9:
        down_score += 1.0
    if change_15m <= -range_mean * 0.7:
        down_score += 1.0
    if change_5m <= -range_mean * 0.35:
        down_score += 0.75
    if pos120 <= 35.0:
        down_score += 1.0
    if pos30 <= 30.0:
        down_score += 0.5
    if short_upnl > long_upnl + 5.0:
        down_score += 1.0
    if change_30m >= range_mean * 0.9:
        up_score += 1.0
    if change_15m >= range_mean * 0.7:
        up_score += 1.0
    if change_5m >= range_mean * 0.35:
        up_score += 0.75
    if pos120 >= 65.0:
        up_score += 1.0
    if pos30 >= 70.0:
        up_score += 0.5
    if long_upnl > short_upnl + 5.0:
        up_score += 1.0
    label = "RANGE"
    if down_score >= 2.5 and down_score > up_score + 0.75:
        label = "DOWN"
    elif up_score >= 2.5 and up_score > down_score + 0.75:
        label = "UP"
    return {
        "label": label,
        "down_score": down_score,
        "up_score": up_score,
        "net_amount": net_amount,
        "long_amount": long_amount,
        "short_amount": short_amount,
        "range_mean": range_mean,
    }


def trend_rescue_reduce_guard(
    side: str,
    position: Position,
    position_by_side: dict[str, Position],
    context: dict[str, float],
) -> dict[str, object]:
    regime = trend_rescue_regime(position_by_side, context)
    label = str(regime["label"])
    range_mean = float(regime["range_mean"])
    pos30 = float(context.get("pos30") or 50.0)
    pos120 = float(context.get("pos120") or 50.0)
    change_5m = float(context.get("change_5m_pct") or 0.0)
    volume_ratio = float(context.get("volume_ratio_30") or 0.0)
    pullback = float(context.get("pullback_from_hi30_pct") or 0.0)
    bounce = float(context.get("bounce_from_lo30_pct") or 0.0)
    net_amount = float(regime["net_amount"])
    if label == "DOWN":
        if side == "LONG":
            at_countertrend_high = pos30 >= 72.0 or pos120 >= 65.0
            fade_hint = pullback >= range_mean * 0.22 or change_5m <= range_mean * 0.25 or volume_ratio <= 0.75
            allowed = net_amount > 0 and position.upnl < 0.0 and at_countertrend_high and fade_hint
            return {
                **regime,
                "allowed": allowed,
                "reason": "downtrend_trim_overweight_long_only_on_fading_bounce",
                "at_countertrend_high": at_countertrend_high,
                "fade_hint": fade_hint,
            }
        return {
            **regime,
            "allowed": False,
            "reason": "downtrend_keep_short_hedge_running",
        }
    if label == "UP":
        if side == "SHORT":
            at_countertrend_low = pos30 <= 28.0 or pos120 <= 35.0
            fade_hint = bounce >= range_mean * 0.22 or change_5m >= -range_mean * 0.25 or volume_ratio <= 0.75
            allowed = net_amount < 0 and position.upnl < 0.0 and at_countertrend_low and fade_hint
            return {
                **regime,
                "allowed": allowed,
                "reason": "uptrend_trim_overweight_short_only_on_fading_pullback",
                "at_countertrend_low": at_countertrend_low,
                "fade_hint": fade_hint,
            }
        return {
            **regime,
            "allowed": False,
            "reason": "uptrend_keep_long_hedge_running",
        }
    guard = trend_guard(side, context)
    return {
        **regime,
        "allowed": position.upnl > 0.0 and not bool(guard.get("blocked")),
        "reason": "range_mode_requires_positive_leg_profit",
        "range_guard": guard,
    }


def trend_rescue_readd_guard(
    side: str,
    position_by_side: dict[str, Position],
    context: dict[str, float],
) -> dict[str, object]:
    regime = trend_rescue_regime(position_by_side, context)
    label = str(regime["label"])
    range_mean = float(regime["range_mean"])
    pos30 = float(context.get("pos30") or 50.0)
    pos120 = float(context.get("pos120") or 50.0)
    change_5m = float(context.get("change_5m_pct") or 0.0)
    volume_ratio = float(context.get("volume_ratio_30") or 0.0)
    if label == "DOWN" and side == "LONG":
        lower_bounce = (pos30 <= 22.0 or pos120 <= 28.0) and change_5m >= range_mean * 0.15
        trend_invalidated = pos30 >= 78.0 and change_5m >= range_mean * 0.7 and volume_ratio >= 0.75
        return {
            **regime,
            "allowed": lower_bounce or trend_invalidated,
            "reason": "readd_long_only_on_lower_bounce_or_downtrend_invalidation",
            "lower_bounce": lower_bounce,
            "trend_invalidated": trend_invalidated,
        }
    if label == "UP" and side == "SHORT":
        upper_fade = (pos30 >= 78.0 or pos120 >= 72.0) and change_5m <= -range_mean * 0.15
        trend_invalidated = pos30 <= 22.0 and change_5m <= -range_mean * 0.7 and volume_ratio >= 0.75
        return {
            **regime,
            "allowed": upper_fade or trend_invalidated,
            "reason": "readd_short_only_on_upper_fade_or_uptrend_invalidation",
            "upper_fade": upper_fade,
            "trend_invalidated": trend_invalidated,
        }
    urgent_readd = reduced_side_readd_urgent(side, context)
    return {
        **regime,
        "allowed": urgent_readd,
        "reason": "readd_only_if_original_side_resumes_strong_continuation",
        "urgent_readd": urgent_readd,
    }


def decide(
    position_by_side: dict[str, Position],
    context: dict[str, float],
    state: dict[str, object],
    *,
    mode: str,
    profit_trigger: float,
    drawdown_readd_usdt: float,
    cooldown_seconds: float,
    max_imbalance_after_reduce: float,
    reduce_fraction: float,
    trend_min_book_delta: float,
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    now_epoch = time.time()
    last_action = state.get("last_action_epoch")
    cooldown_ok = last_action is None or now_epoch - float(last_action) >= cooldown_seconds
    action_backoff_until = float(state.get("action_backoff_until") or 0.0)
    if now_epoch < action_backoff_until:
        return actions
    baseline, _ = ensure_baseline(state, position_by_side, source="auto_init")
    reduced_state = state.get("reduced")
    reduced = reduced_state if isinstance(reduced_state, dict) else {}
    for side, position in sorted(position_by_side.items()):
        side_reduced = reduced.get(side)
        desired_qty = round_qty(position.amount * reduce_fraction)
        progress = progress_against_baseline(side, position_by_side, baseline)
        if not side_reduced:
            if mode == "trend-rescue":
                guard = trend_rescue_reduce_guard(side, position, position_by_side, context)
                guard_blocked = not bool(guard.get("allowed"))
                if position.upnl < 0.0:
                    guard["book_delta"] = progress["book_delta"]
                    guard["min_book_delta"] = trend_min_book_delta
                    guard["book_delta_ok"] = progress["book_delta"] >= trend_min_book_delta
                    guard_blocked = guard_blocked or not bool(guard["book_delta_ok"])
            else:
                guard = trend_guard(side, context)
                guard_blocked = bool(guard["blocked"])
            qty, balance = capped_reduce_quantity(
                side,
                position_by_side,
                desired_qty,
                max_imbalance_after_reduce=max_imbalance_after_reduce,
            )
            if (
                progress["effective_delta"] >= profit_trigger
                and progress["side_delta"] > 0.0
                and cooldown_ok
                and qty > 0
                and not guard_blocked
            ):
                params = reduce_order_params(position)
                actions.append(
                    {
                        "action": "reduce_one_third",
                        "side": side,
                        "quantity": qty,
                        "reason": (
                            f"{side} effective_delta {progress['effective_delta']:.4f} >= {profit_trigger:.4f} "
                            f"(side_delta={progress['side_delta']:.4f}, book_delta={progress['book_delta']:.4f}, "
                            f"base_upnl={progress['side_upnl_base']:.4f}, current_upnl={position.upnl:.4f})"
                        ),
                        "trend_guard": guard,
                        "hedge_balance": balance,
                        "baseline_progress": progress,
                        **params,
                    }
                )
                return actions
            continue
        if not isinstance(side_reduced, dict):
            continue
        original_qty = int(float(side_reduced.get("quantity") or 0))
        reduce_upnl = float(side_reduced.get("reduce_upnl") or 0.0)
        trigger_upnl = reduce_upnl - drawdown_readd_usdt
        if mode == "trend-rescue":
            readd_guard = trend_rescue_readd_guard(side, position_by_side, context)
            should_readd = position.upnl <= trigger_upnl and bool(readd_guard.get("allowed"))
        else:
            # Re-add only after the leg has given back most locked profit and price
            # is no longer at a pure chase extreme.
            side_extreme_ok = (side == "SHORT" and context["pos30"] >= 45.0) or (
                side == "LONG" and context["pos30"] <= 55.0
            )
            urgent_readd = reduced_side_readd_urgent(side, context)
            readd_guard = {"side_extreme_ok": side_extreme_ok, "urgent_readd": urgent_readd}
            should_readd = (position.upnl <= trigger_upnl and side_extreme_ok) or urgent_readd
        if should_readd and cooldown_ok and original_qty > 0:
            params = add_order_params(side)
            actions.append(
                {
                    "action": "readd_reduced_third",
                    "side": side,
                    "quantity": original_qty,
                    "reason": (
                        f"{side} upnl {position.upnl:.4f} <= readd trigger {trigger_upnl:.4f} "
                        f"and pos30 {context['pos30']:.1f}; guard={readd_guard.get('reason', 'range_readd')}"
                    ),
                    "readd_guard": readd_guard,
                    **params,
                }
            )
            return actions
    return actions


def decision_diagnostics(
    position_by_side: dict[str, Position],
    context: dict[str, float],
    state: dict[str, object],
    *,
    mode: str,
    profit_trigger: float,
    cooldown_seconds: float,
    max_imbalance_after_reduce: float,
    reduce_fraction: float,
    trend_min_book_delta: float,
) -> list[dict[str, object]]:
    baseline = state.get("baseline")
    if not isinstance(baseline, dict):
        baseline = baseline_snapshot(position_by_side, source="diagnostic_unpersisted")
    now_epoch = time.time()
    last_action = state.get("last_action_epoch")
    cooldown_remaining = 0.0
    if last_action is not None:
        cooldown_remaining = max(cooldown_seconds - (now_epoch - float(last_action)), 0.0)
    backoff_remaining = max(float(state.get("action_backoff_until") or 0.0) - now_epoch, 0.0)
    reduced_state = state.get("reduced")
    reduced = reduced_state if isinstance(reduced_state, dict) else {}
    diagnostics: list[dict[str, object]] = []
    for side, position in sorted(position_by_side.items()):
        desired_qty = round_qty(position.amount * reduce_fraction)
        progress = progress_against_baseline(side, position_by_side, baseline)
        if mode == "trend-rescue":
            guard = trend_rescue_reduce_guard(side, position, position_by_side, context)
            guard_blocked = not bool(guard.get("allowed"))
            if position.upnl < 0.0:
                guard["book_delta"] = progress["book_delta"]
                guard["min_book_delta"] = trend_min_book_delta
                guard["book_delta_ok"] = progress["book_delta"] >= trend_min_book_delta
                guard_blocked = guard_blocked or not bool(guard["book_delta_ok"])
        else:
            guard = trend_guard(side, context)
            guard_blocked = bool(guard["blocked"])
        qty, balance = capped_reduce_quantity(
            side,
            position_by_side,
            desired_qty,
            max_imbalance_after_reduce=max_imbalance_after_reduce,
        )
        reasons: list[str] = []
        if reduced.get(side):
            reasons.append("side_already_reduced_waiting_readd")
        if progress["effective_delta"] < profit_trigger:
            reasons.append("profit_trigger_not_reached")
        if progress["side_delta"] <= 0.0:
            reasons.append("side_not_improved_vs_baseline")
        if cooldown_remaining > 0:
            reasons.append("cooldown_active")
        if backoff_remaining > 0:
            reasons.append("exchange_error_backoff_active")
        if qty <= 0:
            reasons.append("hedge_imbalance_cap_blocks_quantity")
        if guard_blocked:
            reasons.append("mode_guard_blocks_reduce")
        diagnostics.append(
            {
                "side": side,
                "position_upnl": position.upnl,
                "reduced_state": reduced.get(side),
                "desired_qty": desired_qty,
                "candidate_qty": qty,
                "hedge_balance": balance,
                "baseline_progress": progress,
                "reduce_guard": guard,
                "blocked_reasons": reasons,
                "cooldown_remaining_seconds": round(cooldown_remaining, 3),
                "backoff_remaining_seconds": round(backoff_remaining, 3),
            }
        )
    return diagnostics


def execute_action(client: BinanceFuturesSignedClient, action: dict[str, object], *, execute: bool) -> dict[str, object]:
    if not execute:
        return {"dry_run": True}
    return client.new_order(
        symbol=SYMBOL,
        side=str(action["order_side"]),
        order_type="MARKET",
        quantity=float(action["quantity"]),
        position_side=str(action["position_side"]),
        new_client_order_id=f"bfa-{symbol_slug(SYMBOL)}-rescue-{int(time.time())}-{str(action['action'])[:6]}",
    )


def one_cycle(args: argparse.Namespace) -> None:
    client = build_client()
    position_by_side = positions(client)
    context = market_context()
    state = load_state()
    _, baseline_created = ensure_baseline(state, position_by_side, source="auto_init")
    actions = decide(
        position_by_side,
        context,
        state,
        mode=args.mode,
        profit_trigger=args.profit_trigger,
        drawdown_readd_usdt=args.drawdown_readd,
        cooldown_seconds=args.cooldown_seconds,
        max_imbalance_after_reduce=args.max_imbalance_after_reduce,
        reduce_fraction=args.reduce_fraction,
        trend_min_book_delta=args.trend_min_book_delta,
    )
    event: dict[str, object] = {
        "ts": utc_now(),
        "symbol": SYMBOL,
        "mode": args.mode,
        "execute": bool(args.execute),
        "positions": {side: asdict(position) for side, position in position_by_side.items()},
        "context": context,
        "state_before": copy.deepcopy(state),
        "decision_diagnostics": decision_diagnostics(
            position_by_side,
            context,
            state,
            mode=args.mode,
            profit_trigger=args.profit_trigger,
            cooldown_seconds=args.cooldown_seconds,
            max_imbalance_after_reduce=args.max_imbalance_after_reduce,
            reduce_fraction=args.reduce_fraction,
            trend_min_book_delta=args.trend_min_book_delta,
        ),
        "actions": actions,
    }
    for action in actions[:1]:
        try:
            action["response"] = execute_action(client, action, execute=bool(args.execute))
            if args.execute:
                refreshed_positions = positions(client)
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
                        "reduce_upnl": refreshed_positions.get(side, position_by_side[side]).upnl,
                        "reduced_at": utc_now(),
                    }
                elif action["action"] == "readd_reduced_third":
                    state_reduced.pop(str(action["side"]), None)
                state["baseline"] = baseline_snapshot(
                    refreshed_positions if refreshed_positions else position_by_side,
                    source=f"post_{action['action']}",
                )
                save_state(state)
        except BinanceSignedError as exc:
            action["error"] = {
                "status": exc.status_code,
                "code": exc.binance_code,
                "message": exc.binance_message,
            }
            state["last_action_epoch"] = time.time()
            state["last_action_at"] = utc_now()
            state["action_backoff_until"] = time.time() + max(args.error_backoff_seconds, args.cooldown_seconds)
            save_state(state)
    if args.execute and baseline_created and not actions:
        save_state(state)
    event["state_after"] = load_state() if args.execute else state
    log_event(event)
    print(json.dumps(event, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--state-file")
    parser.add_argument("--log-file")
    parser.add_argument("--mode", choices=("range", "trend-rescue"), default="range")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--profit-trigger", type=float, default=10.0)
    parser.add_argument("--drawdown-readd", type=float, default=8.0)
    parser.add_argument("--cooldown-seconds", type=float, default=45.0)
    parser.add_argument("--max-imbalance-after-reduce", type=float, default=0.30)
    parser.add_argument("--reduce-fraction", type=float, default=1.0 / 3.0)
    parser.add_argument("--trend-min-book-delta", type=float, default=0.0)
    parser.add_argument("--error-backoff-seconds", type=float, default=300.0)
    args = parser.parse_args()
    configure_runtime(args.symbol, state_file=args.state_file, log_file=args.log_file)
    if args.once:
        one_cycle(args)
        return
    while True:
        one_cycle(args)
        time.sleep(max(args.interval, 5.0))


if __name__ == "__main__":
    main()
