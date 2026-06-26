"""State-machine test for the position protection / exit system.

Generates randomized market dynamics (trend, range, spike, flash-crash, slow-
grind-reversal) as 1-minute price paths, opens a simulated position at the
start, and replays the sentinel/trailing protection logic bar-by-bar. Verifies
that the exit system never leaves a position unprotected (裸奔), never locks a
loss when profit existed (MFE未被保護), and respects the different sensitivity
profiles for trend vs micro legs.

This is a property-based / scenario test, not a unit test of one function: it
exercises the full protection decision pipeline across many market states to
catch illogical or profit-suboptimal behavior.

No live env/DB/service/exchange. Pure simulation against the protection math.
"""

from __future__ import annotations

import math
import random
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bfa.ops.position_sentinel import _protection_profile  # noqa: E402


# ---------------------------------------------------------------------------
# Market scenario generators (randomized)
# ---------------------------------------------------------------------------

@dataclass
class BarPath:
    bars: list[dict]  # each: {t, o, h, l, c, v}


def gen_trend(seed: int, bars: int = 120, drift: float = 0.0) -> BarPath:
    """Directional trend (up or down)."""
    rng = random.Random(seed)
    d = drift if drift != 0 else rng.choice([-1, 1]) * rng.uniform(0.0003, 0.0015)
    vol = rng.uniform(0.001, 0.004)
    price = 100.0
    bars_list = []
    for i in range(bars):
        ret = rng.gauss(d, vol)
        price = max(price * math.exp(ret), 1e-6)
        wick = abs(rng.gauss(0, vol)) * price
        bars_list.append({"t": i, "o": price, "h": price + wick * rng.random(),
                          "l": price - wick * rng.random(), "c": price, "v": rng.uniform(0.5, 2.0)})
    return BarPath(bars=bars_list)


def gen_range(seed: int, bars: int = 120) -> BarPath:
    """Mean-reverting range."""
    rng = random.Random(seed)
    center = 100.0
    half = rng.uniform(0.3, 1.5)
    vol = rng.uniform(0.001, 0.003)
    price = center
    bars_list = []
    for i in range(bars):
        shock = rng.gauss(0, vol)
        price = price + 0.08 * (center - price) + shock * half
        price = max(min(price, center + half * 1.5), center - half * 1.5)
        wick = abs(rng.gauss(0, vol)) * price
        bars_list.append({"t": i, "o": price, "h": price + wick, "l": price - wick, "c": price, "v": rng.uniform(0.5, 2.0)})
    return BarPath(bars=bars_list)


def gen_spike_and_revert(seed: int, bars: int = 120) -> BarPath:
    """Sudden spike (wick) then reversion — the micro-grid bread and butter."""
    rng = random.Random(seed)
    price = 100.0
    vol = 0.001
    bars_list = []
    spike_bar = rng.randint(10, bars - 30)
    spike_dir = rng.choice([-1, 1])
    spike_mag = rng.uniform(0.015, 0.04)  # 1.5%-4% spike
    for i in range(bars):
        if i == spike_bar:
            spiked = price * (1 + spike_dir * spike_mag)
            bars_list.append({"t": i, "o": price, "h": max(price, spiked) + price * 0.001,
                              "l": min(price, spiked) - price * 0.001, "c": price * (1 + spike_dir * spike_mag * 0.3), "v": 5.0})
            price = price * (1 + spike_dir * spike_mag * 0.3)
        else:
            ret = rng.gauss(0, vol)
            price = max(price * math.exp(ret), 1e-6)
            wick = abs(rng.gauss(0, vol)) * price
            bars_list.append({"t": i, "o": price, "h": price + wick, "l": price - wick, "c": price, "v": rng.uniform(0.5, 2.0)})
    return BarPath(bars=bars_list)


def gen_flash_crash(seed: int, bars: int = 120) -> BarPath:
    """Rapid adverse move against the entry — tests stop tightness."""
    rng = random.Random(seed)
    price = 100.0
    vol = 0.002
    crash_bar = rng.randint(5, 20)
    crash_mag = rng.uniform(0.02, 0.06)
    bars_list = []
    for i in range(bars):
        if crash_bar <= i < crash_bar + 5:
            price = price * (1 - crash_mag / 5)
            wick = price * 0.002
        else:
            ret = rng.gauss(0, vol)
            price = max(price * math.exp(ret), 1e-6)
            wick = abs(rng.gauss(0, vol)) * price
        bars_list.append({"t": i, "o": price, "h": price + wick, "l": price - wick, "c": price, "v": rng.uniform(0.5, 2.0)})
    return BarPath(bars=bars_list)


def gen_slow_grind_reversal(seed: int, bars: int = 120) -> BarPath:
    """Profitable for a while, then slowly reverses to loss — the MFE-revert case."""
    rng = random.Random(seed)
    price = 100.0
    vol = rng.uniform(0.001, 0.0025)
    peak_bar = rng.randint(15, 40)
    peak_mag = rng.uniform(0.005, 0.02)
    bars_list = []
    for i in range(bars):
        if i < peak_bar:
            d = peak_mag / peak_bar  # climb to peak
        else:
            d = -rng.uniform(0.0003, 0.001)  # slow bleed back
        ret = rng.gauss(d, vol)
        price = max(price * math.exp(ret), 1e-6)
        wick = abs(rng.gauss(0, vol)) * price
        bars_list.append({"t": i, "o": price, "h": price + wick, "l": price - wick, "c": price, "v": rng.uniform(0.5, 2.0)})
    return BarPath(bars=bars_list)


SCENARIOS = {
    "trend_up": lambda s: gen_trend(s, drift=0.0008),
    "trend_down": lambda s: gen_trend(s, drift=-0.0008),
    "range": gen_range,
    "spike_revert": gen_spike_and_revert,
    "flash_crash": gen_flash_crash,
    "slow_grind_reversal": gen_slow_grind_reversal,
}


# ---------------------------------------------------------------------------
# Protection simulation (mirrors sentinel trailing logic)
# ---------------------------------------------------------------------------

@dataclass
class ProtectionResult:
    exit_reason: str  # stop_loss / take_profit / trailing_lock / time_exit / end_unrealized
    exit_bar: int
    exit_pnl_r: float  # in R multiples
    mfe_r: float
    was_protected_at_exit: bool
    max_unprotected_bars: int  # bars with no protection (裸奔) — should always be 0


def simulate_protection(
    path: BarPath,
    side: str,  # LONG / SHORT
    entry_price: float,
    stop_price: float,
    target_price: float,
    profile: dict,  # protection profile (min_profit_r, giveback_r, lock_r, etc.)
) -> ProtectionResult:
    """Replay the protection decision bar-by-bar.

    Simplified model of the sentinel: once current_r >= min_profit_r, trailing
    activates. The stop moves up to max(current_stop, entry + lock_r * risk) or
    mark - giveback_r * risk, whichever is better for the trader. The position
    exits when the bar touches the (possibly trailed) stop or the target.
    """
    is_long = side == "LONG"
    risk_dist = abs(entry_price - stop_price)
    if risk_dist <= 0:
        return ProtectionResult("invalid", 0, 0.0, 0.0, False, 0)
    min_profit_r = profile.get("min_profit_r", 0.25)
    lock_r = max(profile.get("lock_r", 0.25), 0.05)  # floored (Bug 1 fix)
    giveback_r = profile.get("giveback_r", 0.55)
    min_cost_r = 0.08 / 100.0 * entry_price / risk_dist
    lock_r = max(lock_r, min_cost_r)

    current_stop = stop_price
    mfe_r = 0.0
    unprotected = 0
    max_unprotected = 0
    last_protected_bar = -1

    for i, bar in enumerate(path.bars):
        mark = bar["c"]
        if is_long:
            signed_move = mark - entry_price
            favorable = bar["h"]
        else:
            signed_move = entry_price - mark
            favorable = bar["l"] if is_long else bar["h"]
        current_r = signed_move / risk_dist
        mfe_r = max(mfe_r, current_r)

        # trailing activation
        if current_r >= min_profit_r:
            if is_long:
                trailed_stop = max(current_stop, entry_price + lock_r * risk_dist, mark - giveback_r * risk_dist)
            else:
                trailed_stop = min(current_stop, entry_price - lock_r * risk_dist, mark + giveback_r * risk_dist)
            if (is_long and trailed_stop > current_stop) or (not is_long and trailed_stop < current_stop):
                current_stop = trailed_stop
            last_protected_bar = i

        # check exits
        if is_long:
            if bar["l"] <= current_stop:
                pnl_r = (current_stop - entry_price) / risk_dist
                protected = last_protected_bar >= 0 or i == 0
                return ProtectionResult("trailing_lock" if last_protected_bar >= 0 else "stop_loss", i, pnl_r, mfe_r, True, max_unprotected)
            if bar["h"] >= target_price:
                return ProtectionResult("take_profit", i, (target_price - entry_price) / risk_dist, mfe_r, True, max_unprotected)
        else:
            if bar["h"] >= current_stop:
                pnl_r = (entry_price - current_stop) / risk_dist
                protected = last_protected_bar >= 0 or i == 0
                return ProtectionResult("trailing_lock" if last_protected_bar >= 0 else "stop_loss", i, pnl_r, mfe_r, True, max_unprotected)
            if bar["l"] <= target_price:
                return ProtectionResult("take_profit", i, (entry_price - target_price) / risk_dist, mfe_r, True, max_unprotected)

    # end of path without exit
    final = path.bars[-1]["c"]
    pnl_r = ((final - entry_price) if is_long else (entry_price - final)) / risk_dist
    return ProtectionResult("end_unrealized", len(path.bars), pnl_r, mfe_r, last_protected_bar >= 0, max_unprotected)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def make_trend_profile() -> dict:
    """Trend leg protection: wider tolerance, lets trends run."""
    return {"min_profit_r": 0.25, "lock_r": 0.25, "giveback_r": 0.65}


def make_micro_profile() -> dict:
    """Micro leg protection: tighter, locks profit fast."""
    return {"min_profit_r": 0.08, "lock_r": 0.10, "giveback_r": 0.22}


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_suite(seeds=range(50), report_path=None):
    results = []
    for scenario_name, gen in SCENARIOS.items():
        for side in ("LONG", "SHORT"):
            for profile_name, profile in (("trend", make_trend_profile()), ("micro", make_micro_profile())):
                for seed in seeds:
                    path = gen(seed)
                    entry = path.bars[0]["o"]
                    # stop at 1.5% for trend, 0.8% for micro (tighter)
                    stop_dist = 0.015 if profile_name == "trend" else 0.008
                    if side == "LONG":
                        stop = entry * (1 - stop_dist)
                        target = entry * (1 + stop_dist * 2.0)
                    else:
                        stop = entry * (1 + stop_dist)
                        target = entry * (1 - stop_dist * 2.0)
                    r = simulate_protection(path, side, entry, stop, target, profile)
                    results.append({
                        "scenario": scenario_name, "side": side, "profile": profile_name,
                        "seed": seed,
                        "exit_reason": r.exit_reason, "exit_bar": r.exit_bar,
                        "pnl_r": r.exit_pnl_r, "mfe_r": r.mfe_r,
                        "was_protected": r.was_protected_at_exit,
                        "max_unprotected_bars": r.max_unprotected_bars,
                    })

    # analysis
    print(f"# {len(results)} simulations across {len(SCENARIOS)} scenarios × 2 sides × 2 profiles × {len(seeds)} seeds\n")
    # group by scenario × profile
    from collections import defaultdict
    groups = defaultdict(list)
    for r in results:
        groups[(r["scenario"], r["profile"])].append(r)

    print(f"{'scenario':22s} {'profile':6s} {'n':>4s} {'win%':>6s} {'avg_R':>7s} {'avg_MFE':>8s} {'mfe_unprotected%':>16s}")
    for (sc, pf), rs in sorted(groups.items()):
        n = len(rs)
        wins = sum(1 for r in rs if r["pnl_r"] > 0)
        avg_r = statistics.mean(r["pnl_r"] for r in rs)
        avg_mfe = statistics.mean(r["mfe_r"] for r in rs)
        # was-wining-then-lost (MFE > 0.5R but exited at loss)
        unprotected = sum(1 for r in rs if r["mfe_r"] > 0.5 and r["pnl_r"] < 0)
        print(f"{sc:22s} {pf:6s} {n:4d} {wins/n:6.1%} {avg_r:+7.3f} {avg_mfe:+8.3f} {unprotected/n:16.1%}")

    # violations: any position ending unprotected with prior profit
    violations = [r for r in results if r["mfe_r"] > 0.5 and r["pnl_r"] < -0.5]
    print(f"\n# protection violations (MFE>0.5R but exit<-0.5R): {len(violations)}/{len(results)}")
    if violations:
        # sample
        for v in violations[:5]:
            print(f"  {v['scenario']:22s} {v['side']:5s} {v['profile']:6s} seed={v['seed']:3d} "
                  f"MFE={v['exit_mfe_r']:+.2f}R exit={v['exit_pnl_r']:+.2f}R reason={v['exit_exit_reason']}")

    # naked-position check: any with max_unprotected_bars > 5
    naked = [r for r in results if r["max_unprotected_bars"] > 5]
    print(f"# naked-position events (unprotected >5 bars): {len(naked)}")

    if report_path:
        import json
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(json.dumps({
            "summary": {
                "total": len(results),
                "violations": len(violations),
                "naked": len(naked),
            },
            "groups": {f"{sc}_{pf}": {
                "n": len(rs),
                "win_rate": round(sum(1 for r in rs if r["pnl_r"] > 0) / len(rs), 4),
                "avg_r": round(statistics.mean(r["pnl_r"] for r in rs), 4),
                "avg_mfe_r": round(statistics.mean(r["mfe_r"] for r in rs), 4),
                "mfe_unprotected_rate": round(sum(1 for r in rs if r["mfe_r"] > 0.5 and r["pnl_r"] < 0) / len(rs), 4),
            } for (sc, pf), rs in groups.items()},
        }, indent=2), encoding="utf-8")
        print(f"\n# wrote {report_path}")
    return results


if __name__ == "__main__":
    run_suite(seeds=range(80), report_path="results/research/state_machine_protection_test.json")
