"""Parameter sweep for trend vs micro protection profiles.

The state-machine test showed protection works (0 violations, 0 naked) but
avg MFE >> avg exit_R — profit giveback is severe. This sweep tests different
lock_r / giveback_r / min_profit_r combinations to find the balance that
maximizes captured profit (exit_R close to MFE) without choking off winners
(premature trailing exit on legit trends).

Splits scenarios into "should-lock" (spike_revert, slow_grind_reversal,
flash_crash — mean reverting, lock aggressively) vs "should-run" (trend_up,
trend_down — directional, trail loosely) and scores each param set on both.

No live env/DB/service.
"""
from __future__ import annotations
import sys, statistics
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research"))
import state_machine_protection_test as sm  # noqa: E402

SHOULD_LOCK = {"spike_revert", "slow_grind_reversal", "flash_crash", "range"}
SHOULD_RUN = {"trend_up", "trend_down"}


def score_params(profile: dict, profile_name: str, seeds=range(60)) -> dict:
    """Run all scenarios with given params, return score metrics."""
    results = []
    for scenario_name, gen in sm.SCENARIOS.items():
        for side in ("LONG", "SHORT"):
            for seed in seeds:
                path = gen(seed)
                entry = path.bars[0]["o"]
                stop_dist = 0.015 if profile_name == "trend" else 0.008
                if side == "LONG":
                    stop = entry * (1 - stop_dist); target = entry * (1 + stop_dist * 2.0)
                else:
                    stop = entry * (1 + stop_dist); target = entry * (1 - stop_dist * 2.0)
                r = sm.simulate_protection(path, side, entry, stop, target, profile)
                results.append({
                    "scenario": scenario_name, "pnl_r": r.exit_pnl_r, "mfe_r": r.mfe_r,
                    "exit_reason": r.exit_reason,
                })
    # split by should-lock vs should-run
    lock_r = [r for r in results if r["scenario"] in SHOULD_LOCK]
    run_r = [r for r in results if r["scenario"] in SHOULD_RUN]
    def metrics(rs):
        n = len(rs)
        if n == 0:
            return {}
        wins = sum(1 for r in rs if r["pnl_r"] > 0)
        avg = statistics.mean(r["pnl_r"] for r in rs)
        mfe = statistics.mean(r["mfe_r"] for r in rs)
        capture = avg / mfe if mfe > 0 else 0  # how much of MFE we kept
        # premature exit on trends: exited trailing_lock when MFE was high
        premature = sum(1 for r in rs if r["exit_reason"] == "trailing_lock" and r["mfe_r"] > 1.0) / n
        return {"win_rate": round(wins/n, 3), "avg_r": round(avg, 4),
                "avg_mfe": round(mfe, 4), "capture_ratio": round(capture, 3),
                "premature_trail_rate": round(premature, 3)}
    return {
        "lock_metrics": metrics(lock_r),
        "run_metrics": metrics(run_r),
        "overall_avg_r": round(statistics.mean(r["pnl_r"] for r in results), 4),
        "overall_capture": round(
            statistics.mean(r["pnl_r"] for r in results) /
            max(statistics.mean(r["mfe_r"] for r in results), 0.001), 3),
    }


def main():
    # parameter grid
    trend_grid = [
        {"min_profit_r": mp, "lock_r": lk, "giveback_r": gb}
        for mp in [0.20, 0.25, 0.35]
        for lk in [0.15, 0.25, 0.40]
        for gb in [0.35, 0.50, 0.65]
    ]
    micro_grid = [
        {"min_profit_r": mp, "lock_r": lk, "giveback_r": gb}
        for mp in [0.05, 0.08, 0.12]
        for lk in [0.08, 0.12, 0.18]
        for gb in [0.12, 0.18, 0.25]
    ]

    print("=" * 90)
    print("TREND leg parameter sweep (maximize capture on trends, avoid premature trail)")
    print(f"{'min_pr':>7s} {'lock_r':>7s} {'gb_r':>6s} | {'lock_WR':>8s} {'lock_R':>7s} {'lock_cap':>9s} | {'run_WR':>8s} {'run_R':>7s} {'run_cap':>8s} {'premature':>10s}")
    print("-" * 90)
    best_trend = None
    for p in trend_grid:
        s = score_params(p, "trend")
        lm, rm = s["lock_metrics"], s["run_metrics"]
        # score: high capture on both, low premature trail
        composite = lm.get("capture_ratio", 0) * 0.4 + rm.get("capture_ratio", 0) * 0.4 - rm.get("premature_trail_rate", 0) * 0.2
        if best_trend is None or composite > best_trend[1]:
            best_trend = (p, composite, s)
        print(f"{p['min_profit_r']:7.2f} {p['lock_r']:7.2f} {p['giveback_r']:6.2f} | "
              f"{lm.get('win_rate',0):8.1%} {lm.get('avg_r',0):+7.3f} {lm.get('capture_ratio',0):9.1%} | "
              f"{rm.get('win_rate',0):8.1%} {rm.get('avg_r',0):+7.3f} {rm.get('capture_ratio',0):8.1%} {rm.get('premature_trail_rate',0):10.1%}")
    print(f"\nBEST TREND: {best_trend[0]}  (composite={best_trend[1]:.3f})")

    print("\n" + "=" * 90)
    print("MICRO leg parameter sweep (maximize capture on mean-revert, fast lock)")
    print(f"{'min_pr':>7s} {'lock_r':>7s} {'gb_r':>6s} | {'lock_WR':>8s} {'lock_R':>7s} {'lock_cap':>9s} | {'run_WR':>8s} {'run_R':>7s} {'run_cap':>8s}")
    print("-" * 90)
    best_micro = None
    for p in micro_grid:
        s = score_params(p, "micro")
        lm, rm = s["lock_metrics"], s["run_metrics"]
        # score: high capture on lock scenarios (micro should lock aggressively)
        composite = lm.get("capture_ratio", 0) * 0.6 + rm.get("capture_ratio", 0) * 0.2 + lm.get("win_rate", 0) * 0.2
        if best_micro is None or composite > best_micro[1]:
            best_micro = (p, composite, s)
        print(f"{p['min_profit_r']:7.2f} {p['lock_r']:7.2f} {p['giveback_r']:6.2f} | "
              f"{lm.get('win_rate',0):8.1%} {lm.get('avg_r',0):+7.3f} {lm.get('capture_ratio',0):9.1%} | "
              f"{rm.get('win_rate',0):8.1%} {rm.get('avg_r',0):+7.3f} {rm.get('capture_ratio',0):8.1%}")
    print(f"\nBEST MICRO: {best_micro[0]}  (composite={best_micro[1]:.3f})")

    print("\n" + "=" * 90)
    print("RECOMMENDED PARAMS:")
    print(f"  trend: {best_trend[0]}")
    print(f"  micro: {best_micro[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
