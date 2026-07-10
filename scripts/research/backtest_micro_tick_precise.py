"""Micro-grid PnL backtest on REAL aggTrades with tick-precise fills.

The previous version aggregated aggTrades to 1-second OHLC bars and simulated
fills on those bars, which flattened intraday wicks/spikes so the strategy saw
~0% win rate. This version keeps the 1-second bars for state/edge computation
(the band boundaries that predict where to post passive limit orders) but
simulates order fills against the *raw tick stream* so瞬時插針 are captured.

This is the correct还原 of the live micro-grid logic:
  - state (band edges, width, vol) from 1s bars  -> 預測掛單點位
  - fills simulated tick-by-tick                  -> 吃到瞬時插針

No live env/DB/service. Uses the user-provided aggTrades cache.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "micro_research", ROOT / "scripts" / "run_micro_grid_research.py"
)
research = importlib.util.module_from_spec(_spec)
sys.modules["micro_research"] = research
_spec.loader.exec_module(research)

AGG_CACHE = Path(r"D:/教青垃圾系統/binance/aggTrades-cache")
NOTIONAL_USDT = 20.0

# ML wick filter (A): loaded lazily
_WICK_MODEL = None
_WICK_FEATURES = [
    "width_percent", "stable_width_percent", "instantaneous_vol",
    "recent_spike_depth", "close_position", "turn_count", "edge_alternation_count",
    "reversal_response_rate", "path_efficiency", "drift_to_width",
    "recent_path_efficiency", "recent_drift_to_width", "amplitude_percent",
    "bollinger_width_percent", "center_cross_count", "score",
    "long_pullback_quality", "short_pullback_quality",
    "stochastic_k", "stochastic_slope", "triple_ema_bias",
    "entry_taker_buy_ratio",
]


def load_wick_filter(model_path="data/research/wick_filter_v1.txt", threshold=0.45):
    global _WICK_MODEL
    if _WICK_MODEL is None:
        try:
            import lightgbm as lgb
            _WICK_MODEL = lgb.Booster(model_file=model_path)
        except Exception:
            _WICK_MODEL = False  # disabled
    return _WICK_MODEL, threshold


def wick_filter_verdict(state, threshold):
    """Return True if the ML wick filter accepts this setup."""
    model = _WICK_MODEL
    if not model:
        return True, 0.5
    row = []
    for k in _WICK_FEATURES:
        v = getattr(state, k, None)
        if v is None:
            v = 0.0
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        row.append(v if v == v else 0.0)
    import numpy as np
    proba = float(model.predict(np.array([row], dtype=float))[0])
    return proba >= threshold, proba


def ticks_to_seconds(symbol: str, ticks: list) -> list:
    """Aggregate ticks into 1-second OHLC bars (for state computation)."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for t in ticks:
        sec = t.time_ms // 1000
        buckets[sec].append((t.price, t.quantity, t.buyer_maker))
    if not buckets:
        return []
    bars = []
    secs = sorted(buckets)
    prev_close = None
    for sec in range(secs[0], secs[-1] + 1):
        trades = buckets.get(sec)
        if trades:
            prices = [t[0] for t in trades]
            qv = sum(t[0] * t[1] for t in trades)
            tbq = sum(t[0] * t[1] for t in trades if t[2])
            bars.append(research.BacktestBar(
                symbol=symbol, open_time=sec * 1000,
                open=prices[0], high=max(prices), low=min(prices), close=prices[-1],
                volume=0.0, close_time=sec * 1000 + 999,
                quote_volume=qv, taker_buy_quote_volume=tbq,
            ))
            prev_close = prices[-1]
        elif prev_close is not None:
            bars.append(research.BacktestBar(
                symbol=symbol, open_time=sec * 1000,
                open=prev_close, high=prev_close, low=prev_close, close=prev_close,
                volume=0.0, close_time=sec * 1000 + 999,
                quote_volume=0.0, taker_buy_quote_volume=0.0,
            ))
    return bars


def run_day(symbol: str, day: date, profile, tick_source, *, use_wick_filter=False, wick_threshold=0.45) -> dict:
    """Run micro-grid across one day with tick-precise fills."""
    # load the full day's ticks, build 1s bars for state
    stream = tick_source.load_day(day)
    if not stream.ticks:
        return {"status": "no_ticks", "trades": 0}
    seconds = ticks_to_seconds(symbol, stream.ticks)
    if len(seconds) < 1500:
        return {"status": "too_short", "trades": 0, "bars": len(seconds)}

    window = 1200
    stride = 600
    results = []
    for start in range(600, len(seconds) - window - 500, stride):
        chunk = seconds[start:start + window]
        if len(chunk) < window:
            continue
        state, reasons = research.build_micro_grid_state(chunk, len(chunk) - 1, profile)
        if state is None:
            continue
        orders = research.build_grid_orders(symbol, state, profile)
        if not orders:
            continue
        valid = []
        for o in orders:
            if not research.is_passive_entry(o.side, o.entry_price, state.current_price, profile):
                continue
            if abs(o.target_price - o.entry_price) <= 0 or abs(o.entry_price - o.stop_price) <= 0:
                continue
            valid.append(o)
        if not valid:
            continue
        # A: ML wick filter — reject low-confidence wick setups
        if use_wick_filter:
            accepted, proba = wick_filter_verdict(state, wick_threshold)
            if not accepted:
                continue
        best = max(valid, key=lambda o: o.size_weight)
        # tick-precise fill: get the tick slice for this order's window
        order_ticks = tick_source.stream_for_order(chunk, best, profile)
        trade, status, _ = research.simulate_grid_basket(
            chunk, [best], profile,
            base_notional_usdt=NOTIONAL_USDT,
            tick_stream=order_ticks,
        )
        if trade is not None:
            results.append({
                "net_pnl": getattr(trade, "net_pnl_usdt", 0.0),
                "win": getattr(trade, "net_pnl_usdt", 0.0) > 0,
                "exit_reason": getattr(trade, "exit_reason", "?"),
                "vol": round(state.instantaneous_vol_percent, 4),
                "regime": research.classify_vol_regime(state.instantaneous_vol_percent, profile),
            })
    if not results:
        return {"status": "no_trades", "trades": 0, "bars": len(seconds)}
    nets = [r["net_pnl"] for r in results]
    wins = sum(1 for r in results if r["win"])
    return {
        "status": "ok",
        "trades": len(results),
        "wins": wins,
        "win_rate": round(wins / len(results), 4),
        "total_net": round(sum(nets), 4),
        "avg_net": round(sum(nets) / len(results), 4),
        "bars": len(seconds),
    }


def main() -> int:
    base_profile = research.MicroGridProfile(
        min_width_percent=0.08, min_edge_alternations=2, min_reversal_response_rate=0.20,
        max_drift_to_width=2.0, wick_min_samples=4, wick_model_mode="ev",
        dynamic_wick_enabled=True, precision_entry_enabled=True,
        min_turn_count=3, min_center_crosses=1, min_width_cost_ratio=0.0,
        max_path_efficiency=0.7,
    )
    prof_off = research.MicroGridProfile(**{**base_profile.__dict__, "vol_regime_enabled": False})
    prof_on = research.MicroGridProfile(**{**base_profile.__dict__, "vol_regime_enabled": True})

    symbols = ["SOLUSDT", "HYPEUSDT"]
    print("=" * 88)
    print("micro-grid PnL on REAL aggTrades (TICK-PRECISE fills): vol-regime OFF vs ON")
    print(f"symbols={symbols}  notional/pos={NOTIONAL_USDT}U  window=1200s stride=600s  wick=ev")
    print("=" * 88)

    grand_off = {"trades": 0, "wins": 0, "net": 0.0}
    grand_on = {"trades": 0, "wins": 0, "net": 0.0}
    for sym in symbols:
        sym_dir = AGG_CACHE / sym
        if not sym_dir.exists():
            continue
        zips = sorted(sym_dir.glob("*.zip"))[:3]
        # derive dates from filenames
        days = []
        for zp in zips:
            dstr = zp.stem.split("-")[-1]  # YYYY-MM-DD
            try:
                days.append(date.fromisoformat(dstr))
            except ValueError:
                continue
        print(f"\n--- {sym} ({len(days)} days) ---")
        # build tick source per profile (off/on share data but separate sources for safety)
        ts_off = research.TickReplaySource(symbol=sym, start=days[0], end=days[-1], cache_dir=AGG_CACHE)
        ts_on = research.TickReplaySource(symbol=sym, start=days[0], end=days[-1], cache_dir=AGG_CACHE)
        for day in days:
            r_off = run_day(sym, day, prof_off, ts_off)
            r_on = run_day(sym, day, prof_on, ts_on)
            grand_off["trades"] += r_off.get("trades", 0)
            grand_off["wins"] += r_off.get("wins", 0)
            grand_off["net"] += r_off.get("total_net", 0.0)
            grand_on["trades"] += r_on.get("trades", 0)
            grand_on["wins"] += r_on.get("wins", 0)
            grand_on["net"] += r_on.get("total_net", 0.0)
            def fmt(r):
                if r["status"] != "ok":
                    return f"{r['status']}(bars={r.get('bars',0)})"
                return f"trades={r['trades']:3d} wins={r['wins']:3d} wr={r['win_rate']:.2f} net={r['total_net']:+.4f}"
            print(f"  {day}: OFF[{fmt(r_off)}]")
            print(f"  {day}: ON [{fmt(r_on)}]")

    print("\n" + "=" * 88)
    print("GRAND TOTAL (tick-precise):")
    print(f"  OFF: trades={grand_off['trades']:4d} wins={grand_off['wins']:4d} wr={grand_off['wins']/max(grand_off['trades'],1):.3f} total_net={grand_off['net']:+.4f}U")
    print(f"  ON : trades={grand_on['trades']:4d} wins={grand_on['wins']:4d} wr={grand_on['wins']/max(grand_on['trades'],1):.3f} total_net={grand_on['net']:+.4f}U")
    print(f"  delta (ON - OFF): {grand_on['net']-grand_off['net']:+.4f}U")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
