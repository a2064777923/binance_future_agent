"""Micro-grid PnL backtest on REAL aggTrades (vol-regime on vs off).

Aggregates real Binance aggTrades into 1-second OHLC bars, runs the micro-grid
strategy (with and without vol-regime adaptation) on each symbol/day, and
reports net PnL, win rate, and trade count. This is the real-data counterpart
to the synthetic verify_micro_geometry_diff.py.

Uses the live account caps (20U margin per position, maker-in/taker-out costs).

No live env/DB/service. Pure local research on the user-provided aggTrades cache.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "micro_research", ROOT / "scripts" / "run_micro_grid_research.py"
)
research = importlib.util.module_from_spec(_spec)
sys.modules["micro_research"] = research
_spec.loader.exec_module(research)

AGG_CACHE = Path(r"D:/教青垃圾系統/binance/aggTrades-cache")

# live caps for micro sizing
NOTIONAL_USDT = 20.0  # margin per position * 1 (micro uses fraction of notional)


def aggtrades_zip_to_seconds(zip_path: Path) -> list[research.BacktestBar]:
    """Read a daily aggTrades zip and aggregate to 1-second OHLC bars."""
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = next((n for n in zf.namelist() if n.endswith(".csv")), None)
        if csv_name is None:
            return []
        with zf.open(csv_name) as fh:
            reader = csv.reader(io.TextIOWrapper(fh, encoding="utf-8"))
            next(reader, None)  # header
            # bucket by second
            buckets: dict[int, list[float]] = defaultdict(list)
            for row in reader:
                if len(row) < 7:
                    continue
                try:
                    price = float(row[1])
                    qty = float(row[2])
                    tms = int(row[5])
                except (ValueError, IndexError):
                    continue
                sec = tms // 1000
                buckets[sec].append((price, qty, row[6].lower() == "true"))
    # build 1s bars, fill gaps
    if not buckets:
        return []
    bars = []
    secs = sorted(buckets)
    first, last = secs[0], secs[-1]
    prev_close = None
    for sec in range(first, last + 1):
        trades = buckets.get(sec)
        if trades:
            prices = [t[0] for t in trades]
            qv = sum(t[0] * t[1] for t in trades)
            tbq = sum(t[0] * t[1] for t in trades if t[2])  # buyer-maker = sell-side aggressive? binance: is_buyer_maker True means buyer is maker (taker sold)
            open_p = prices[0]
            close_p = prices[-1]
            high_p = max(prices)
            low_p = min(prices)
            prev_close = close_p
        else:
            # gap: use prev close as flat bar
            if prev_close is None:
                continue
            open_p = high_p = low_p = close_p = prev_close
            qv = 0.0
            tbq = 0.0
        bars.append(research.BacktestBar(
            symbol="SYMBOL", open_time=sec * 1000,
            open=open_p, high=high_p, low=low_p, close=close_p,
            volume=0.0, close_time=sec * 1000 + 999,
            quote_volume=qv, taker_buy_quote_volume=tbq,
        ))
    return bars


def run_day(seconds: list, profile: research.MicroGridProfile) -> dict:
    """Run micro-grid on one day's seconds, return PnL stats."""
    if len(seconds) < 1500:
        return {"status": "too_short", "trades": 0}
    # slide a window across the day, evaluating at strides. Window must exceed
    # required_history_seconds(600) + wick_training_seconds(900) headroom.
    window = 1200  # 20-minute evaluation window
    stride = 600   # re-evaluate every 10 min (EV training is expensive)
    results = []
    for start in range(0, len(seconds) - window, stride):
        chunk = seconds[start:start + window]
        state, reasons = research.build_micro_grid_state(chunk, len(chunk) - 1, profile)
        if state is None:
            continue
        orders = research.build_grid_orders("SYMBOL", state, profile)
        if not orders:
            continue
        valid = []
        for o in orders:
            if not research.is_passive_entry(o.side, o.entry_price, state.current_price, profile):
                continue
            reward = abs(o.target_price - o.entry_price)
            risk = abs(o.entry_price - o.stop_price)
            if reward > 0 and risk > 0:
                valid.append(o)
        if not valid:
            continue
        # simulate the best single order on the remaining chunk
        best = max(valid, key=lambda o: o.size_weight)
        trade, status, _ = research.simulate_grid_basket(chunk, [best], profile, base_notional_usdt=NOTIONAL_USDT)
        if trade is not None:
            results.append({
                "net_pnl": getattr(trade, "net_pnl_usdt", 0.0),
                "win": getattr(trade, "net_pnl_usdt", 0.0) > 0,
                "vol": round(state.instantaneous_vol_percent, 4),
                "regime": research.classify_vol_regime(state.instantaneous_vol_percent, profile),
            })
    if not results:
        return {"status": "no_trades", "trades": 0}
    nets = [r["net_pnl"] for r in results]
    wins = sum(1 for r in results if r["win"])
    return {
        "status": "ok",
        "trades": len(results),
        "wins": wins,
        "win_rate": round(wins / len(results), 4),
        "total_net": round(sum(nets), 4),
        "avg_net": round(sum(nets) / len(results), 4),
    }


def main() -> int:
    # full micro leg: dynamic wick EV (the real edge source) + vol-regime
    base_profile = research.MicroGridProfile(
        min_width_percent=0.08, min_edge_alternations=2, min_reversal_response_rate=0.20,
        max_drift_to_width=2.0, wick_min_samples=4, wick_model_mode="ev",
        dynamic_wick_enabled=True, precision_entry_enabled=True,
        min_turn_count=3, min_center_crosses=1, min_width_cost_ratio=0.0,
        max_path_efficiency=0.7,
    )
    prof_off = research.MicroGridProfile(**{**base_profile.__dict__, "vol_regime_enabled": False})
    prof_on = research.MicroGridProfile(**{**base_profile.__dict__, "vol_regime_enabled": True})

    # pick a spread of symbols: large / mid / small cap + a live alt
    symbols = ["SOLUSDT", "HYPEUSDT"]
    print("=" * 84)
    print("micro-grid PnL on REAL aggTrades: vol-regime OFF vs ON")
    print(f"symbols={symbols}  notional/pos={NOTIONAL_USDT}U  window=600s stride=180s")
    print("=" * 84)

    grand_off = {"trades": 0, "wins": 0, "net": 0.0}
    grand_on = {"trades": 0, "wins": 0, "net": 0.0}
    for sym in symbols:
        sym_dir = AGG_CACHE / sym
        if not sym_dir.exists():
            print(f"\n--- {sym}: no data ---")
            continue
        zips = sorted(sym_dir.glob("*.zip"))
        # cap to first 3 days for speed (EV training is expensive)
        zips = zips[:3]
        print(f"\n--- {sym} ({len(zips)} days) ---")
        for zp in zips:
            day = zp.stem.split("-")[-1]
            seconds = aggtrades_zip_to_seconds(zp)
            if not seconds:
                print(f"  {day}: no bars")
                continue
            r_off = run_day(seconds, prof_off)
            r_on = run_day(seconds, prof_on)
            grand_off["trades"] += r_off.get("trades", 0)
            grand_off["wins"] += r_off.get("wins", 0)
            grand_off["net"] += r_off.get("total_net", 0.0)
            grand_on["trades"] += r_on.get("trades", 0)
            grand_on["wins"] += r_on.get("wins", 0)
            grand_on["net"] += r_on.get("total_net", 0.0)
            off_str = f"trades={r_off.get('trades',0):3d} wr={r_off.get('win_rate',0):.2f} net={r_off.get('total_net',0):+.3f}" if r_off["status"]=="ok" else r_off["status"]
            on_str = f"trades={r_on.get('trades',0):3d} wr={r_on.get('win_rate',0):.2f} net={r_on.get('total_net',0):+.3f}" if r_on["status"]=="ok" else r_on["status"]
            print(f"  {day}: OFF[{off_str}]  ON[{on_str}]")

    print("\n" + "=" * 84)
    print("GRAND TOTAL (all symbols/days):")
    print(f"  OFF: trades={grand_off['trades']:4d} wins={grand_off['wins']:4d} wr={grand_off['wins']/max(grand_off['trades'],1):.3f} total_net={grand_off['net']:+.3f}U")
    print(f"  ON : trades={grand_on['trades']:4d} wins={grand_on['wins']:4d} wr={grand_on['wins']/max(grand_on['trades'],1):.3f} total_net={grand_on['net']:+.3f}U")
    delta = grand_on["net"] - grand_off["net"]
    print(f"  delta (ON - OFF): {delta:+.3f}U")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
