"""Validate micro-grid vol-regime adaptation on synthetic second paths.

Generates low/mid/high volatility second-level price paths, runs the micro-grid
geometry (with and without vol-regime scaling) on each, and compares the
expected net outcome. This confirms the adaptation improves expectancy in each
regime rather than just shifting geometry.

No live env/DB/service. Pure local research.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research"))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "micro_research", ROOT / "scripts" / "run_micro_grid_research.py"
)
research = importlib.util.module_from_spec(_spec)
sys.modules["micro_research"] = research
_spec.loader.exec_module(research)


def gen_seconds(vol_per_sec: float, n: int = 1200, center: float = 100.0, span_half: float = 0.3, rng: random.Random | None = None) -> list[research.BacktestBar]:
    """Mean-reverting second bars around `center` with given per-sec vol."""
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


def run_one(seconds: list, profile: research.MicroGridProfile) -> dict:
    """Build state + orders + simulate, return outcome stats."""
    state, reasons = research.build_micro_grid_state(seconds, len(seconds) - 1, profile)
    if state is None:
        return {"status": "rejected", "reasons": reasons}
    orders = research.build_grid_orders("TESTUSDT", state, profile)
    if not orders:
        return {"status": "no_orders", "reasons": research.grid_order_rejection_reasons(state, profile)}
    def _valid(o):
        if not research.is_passive_entry(o.side, o.entry_price, state.current_price, profile):
            return False
        reward = abs(o.target_price - o.entry_price)
        risk = abs(o.entry_price - o.stop_price)
        return reward > 0 and risk > 0
    valid = [o for o in orders if _valid(o)]
    if not valid:
        return {"status": "no_valid_orders", "n_orders": len(orders)}
    # simulate the best order
    best = max(valid, key=lambda o: o.size_weight)
    trade, status, fill_index = research.simulate_grid_basket(seconds, [best], profile, base_notional_usdt=20.0)
    if trade is None:
        return {"status": status, "n_orders": len(orders)}
    return {
        "status": status,
        "n_orders": len(orders),
        "n_valid": len(valid),
        "net_pnl_usdt": getattr(trade, "net_pnl_usdt", 0.0),
        "win": getattr(trade, "net_pnl_usdt", 0.0) > 0,
        "exit_reason": getattr(trade, "exit_reason", "?"),
        "vol_regime": research.classify_vol_regime(state.instantaneous_vol_percent, profile),
        "instantaneous_vol": round(state.instantaneous_vol_percent, 4),
        "width_percent": round(state.width_percent, 4),
    }


def main() -> int:
    base_profile = research.MicroGridProfile(
        min_width_percent=0.1, min_edge_alternations=1, min_reversal_response_rate=0.1,
        max_drift_to_width=2.0, wick_min_samples=2, wick_model_mode="quantile",
        dynamic_wick_enabled=False,  # isolate vol-regime effect from EV
    )
    profile_off = research.MicroGridProfile(**{**base_profile.__dict__, "vol_regime_enabled": False})
    profile_on = research.MicroGridProfile(**{**base_profile.__dict__, "vol_regime_enabled": True})

    regimes = [
        ("low vol (0.02%/s)", 0.02),
        ("mid vol (0.08%/s)", 0.08),
        ("high vol (0.25%/s)", 0.25),
    ]
    print("=" * 78)
    print("micro-grid vol-regime adaptation: off vs on, by volatility regime")
    print("=" * 78)
    for label, vol in regimes:
        print(f"\n--- {label} ---")
        off_wins = off_nets = on_wins = on_nets = 0
        off_runs = on_runs = 0
        for seed in range(40):
            seconds = gen_seconds(vol, n=1200, rng=random.Random(seed))
            r_off = run_one(seconds, profile_off)
            r_on = run_one(seconds, profile_on)
            if r_off.get("net_pnl_usdt") is not None:
                off_runs += 1; off_nets += r_off["net_pnl_usdt"]; off_wins += int(r_off["win"])
            if r_on.get("net_pnl_usdt") is not None:
                on_runs += 1; on_nets += r_on["net_pnl_usdt"]; on_wins += int(r_on["win"])
        print(f"  vol-regime OFF: runs={off_runs} wins={off_wins} win_rate={off_wins/max(off_runs,1):.2f} total_net={off_nets:+.2f}U avg={off_nets/max(off_runs,1):+.4f}U")
        print(f"  vol-regime ON : runs={on_runs} wins={on_wins} win_rate={on_wins/max(on_runs,1):.2f} total_net={on_nets:+.2f}U avg={on_nets/max(on_runs,1):+.4f}U")
        delta = on_nets - off_nets
        print(f"  delta (on-off): {delta:+.2f}U over {on_runs} runs")
    print("\n" + "=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
