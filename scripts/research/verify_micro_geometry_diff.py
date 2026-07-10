"""Verify micro-grid vol-regime changes order geometry (the core claim).

Instead of a full PnL backtest (which needs rich second-level microstructure
that synthetic OU paths can't reproduce), this confirms the vol-regime scaling
actually changes the entry/stop/target/hold of produced orders in each regime.
That is the mechanism by which adaptation improves outcomes.

No live env/DB/service. Pure local research.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "micro_research", ROOT / "scripts" / "run_micro_grid_research.py"
)
research = importlib.util.module_from_spec(_spec)
sys.modules["micro_research"] = research
_spec.loader.exec_module(research)


def gen_seconds(vol_per_sec, n=1200, center=100.0, span_half=0.4, rng=None):
    rng = rng or random.Random(42)
    bars = []
    price = center
    mr = 0.05
    for i in range(n):
        shock = rng.gauss(0.0, vol_per_sec / 100.0 * center)
        price = price + mr * (center - price) + shock
        price = max(min(price, center + span_half * 1.5), center - span_half * 1.5)
        wick = abs(rng.gauss(0.0, vol_per_sec / 100.0 * center * 0.5))
        bars.append(research.BacktestBar(
            symbol="TESTUSDT", open_time=i * 1000,
            open=price, high=price + wick, low=price - wick, close=price,
            volume=100.0, close_time=i * 1000 + 999,
            quote_volume=10000.0, taker_buy_quote_volume=5000.0,
        ))
    return bars


def order_geometry(seconds, profile):
    state, reasons = research.build_micro_grid_state(seconds, len(seconds) - 1, profile)
    if state is None:
        return None
    orders = research.build_grid_orders("TESTUSDT", state, profile)
    if not orders:
        return None
    # pick the first valid long order
    best = None
    for o in orders:
        if o.side == "long" and research.is_passive_entry(o.side, o.entry_price, state.current_price, profile):
            best = o
            break
    if best is None:
        best = orders[0]
    span = state.upper_price - state.lower_price
    return {
        "vol": round(state.instantaneous_vol_percent, 4),
        "width": round(state.width_percent, 4),
        "regime": research.classify_vol_regime(state.instantaneous_vol_percent, profile),
        "stop_frac": round(abs(best.entry_price - best.stop_price) / span, 4) if span > 0 else 0,
        "target_frac": round(abs(best.target_price - best.entry_price) / span, 4) if span > 0 else 0,
        "hold_s": best.max_hold_seconds,
    }


def main():
    base = research.MicroGridProfile(
        min_width_percent=0.1, min_edge_alternations=1, min_reversal_response_rate=0.1,
        max_drift_to_width=3.0, wick_min_samples=2, wick_model_mode="quantile",
        dynamic_wick_enabled=False, precision_entry_enabled=True,
    )
    prof_off = research.MicroGridProfile(**{**base.__dict__, "vol_regime_enabled": False})
    prof_on = research.MicroGridProfile(**{**base.__dict__, "vol_regime_enabled": True})

    print("=" * 80)
    print("micro-grid order geometry: vol-regime OFF vs ON (averaged over 20 seeds)")
    print("=" * 80)
    for label, vol in [("low 0.02%/s", 0.02), ("mid 0.08%/s", 0.08), ("high 0.25%/s", 0.25)]:
        off_geos = [order_geometry(gen_seconds(vol, rng=random.Random(s)), prof_off) for s in range(20)]
        on_geos = [order_geometry(gen_seconds(vol, rng=random.Random(s)), prof_on) for s in range(20)]
        off_geos = [g for g in off_geos if g]
        on_geos = [g for g in on_geos if g]
        if not off_geos or not on_geos:
            print(f"\n--- {label}: no valid geometry (state rejected) ---")
            continue
        def avg(geos, k):
            return sum(g[k] for g in geos) / len(geos)
        print(f"\n--- {label} (n_off={len(off_geos)} n_on={len(on_geos)}) ---")
        print(f"             stop_frac  target_frac  hold_s    regime(on)")
        print(f"  OFF:      {avg(off_geos,'stop_frac'):.4f}     {avg(off_geos,'target_frac'):.4f}      {avg(off_geos,'hold_s'):.0f}")
        print(f"  ON :      {avg(on_geos,'stop_frac'):.4f}     {avg(on_geos,'target_frac'):.4f}      {avg(on_geos,'hold_s'):.0f}      {on_geos[0]['regime']}")
        ds = avg(on_geos,'stop_frac') - avg(off_geos,'stop_frac')
        dt = avg(on_geos,'target_frac') - avg(off_geos,'target_frac')
        dh = avg(on_geos,'hold_s') - avg(off_geos,'hold_s')
        print(f"  delta:    {ds:+.4f}     {dt:+.4f}      {dh:+.0f}s")
    print("\n" + "=" * 80)
    print("Expected: low vol -> smaller stop/target/hold; high vol -> larger stop/target, shorter hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
