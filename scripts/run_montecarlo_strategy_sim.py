"""Monte Carlo simulation for the fused trend / micro-grid strategy geometry.

This script is research-only: it generates synthetic price paths (trend +
mean-reverting regimes), replays the trend-leg entry/stop/target geometry and
the micro-grid edge-reversion geometry on them, and reports the expected net
PnL, win rate, fill rate, and cycle availability under

  (a) the pre-improvement target ceiling (`legacy`)
  (b) the floor-protected target ceiling (`improved`)

plus a micro-grid leg comparison. It does NOT touch the event store, live
config, exchange state, or any service. It exists to quantify the
availability / reliability claims made in the strategy review.

Usage:
    python scripts/run_montecarlo_strategy_sim.py --paths 4000 --seed 7
    python scripts/run_montecarlo_strategy_sim.py --json --output results/montecarlo-strategy-sim.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimConfig:
    # Bar / path parameters (a "bar" is one 5m candle for the trend leg and
    # one 1s tick for the micro leg).
    bars_per_path: int = 120  # 10h of 5m bars for trend leg
    seconds_per_path: int = 1200  # 20min of 1s ticks for micro leg
    seed: int = 7

    # Trend-leg geometry (mirrors setup.py live_action_flow + standard profile).
    trend_stop_distance_percent: float = 1.5  # adaptive base ~ vol*1.15
    trend_reward_multiple: float = 1.8  # edge-driven reward multiple
    trend_min_risk_reward: float = 2.0  # live_action_flow min_rr
    trend_volatility_ceiling_multiple: float = 2.0  # the contested `vol*2.0`
    trend_stop_floor_multiple: float = 1.25  # the contested `stop*1.25`
    trend_fee_bps: float = 2.0  # maker entry
    trend_exit_fee_bps: float = 4.0  # taker exit (stop/target market)
    trend_slippage_bps: float = 2.0
    trend_max_hold_bars: int = 144

    # Micro-leg geometry (mirrors run_micro_grid_research edge reversion).
    micro_width_percent: float = 0.6  # typical tradeable range width
    micro_stop_fraction: float = 0.20  # stop as fraction of span (legacy)
    micro_target_fraction: float = 0.50  # target as fraction of span (legacy)
    # Improved geometry: cost-aware. When the round-trip cost is a large share
    # of the span the legacy 0.20/0.50 stop/target makes losing trades cost
    # ~2x (stop + fees), driving expectancy negative. The improved leg widens
    # the target and tightens the stop so the break-even win rate falls below
    # the (discounted) reversal response rate even after costs.
    micro_stop_fraction_improved: float = 0.16
    micro_target_fraction_improved: float = 0.62
    micro_entry_edge_fraction: float = -0.05  # passive post-only depth
    micro_maker_fee_bps: float = 2.0
    micro_taker_fee_bps: float = 4.0
    micro_slippage_bps: float = 1.0
    micro_reversal_response_rate: float = 0.55  # base edge success rate
    micro_max_hold_seconds: int = 420
    # Out-of-sample discount applied to the in-sample reversal_response_rate to
    # emulate the overfit gap the walk-forward + tighter z were added to close.
    micro_oos_discount: float = 0.70

    # Regime mix (probability a path is a clean trend vs a range vs chop).
    trend_regime_probability: float = 0.30
    range_regime_probability: float = 0.45
    chop_regime_probability: float = 0.25

    # Per-layer pass probabilities for the end-to-end availability product.
    # These are conservative point estimates from the strategy review; the
    # Monte Carlo quantifies the *geometry* layer and then multiplies.
    p_candidate_pass: float = 0.30
    p_regime_allow_trend: float = 0.55
    p_regime_allow_micro: float = 0.80
    p_governor_accept_legacy: float = 0.40
    p_governor_accept_improved: float = 0.62
    p_risk_accept: float = 0.70
    p_fill_limit_trend: float = 0.55
    p_fill_limit_micro_legacy: float = 0.20
    p_fill_limit_micro_improved: float = 0.26

    notional_usdt: float = 50.0  # representative live pilot notional


# ---------------------------------------------------------------------------
# Synthetic price path generation
# ---------------------------------------------------------------------------


def _generate_trend_path(rng: random.Random, bars: int, drift_per_bar: float, vol_per_bar: float) -> list[float]:
    price = 100.0
    closes: list[float] = [price]
    for _ in range(bars):
        shock = rng.gauss(drift_per_bar, vol_per_bar)
        price = max(price * math.exp(shock), 1e-6)
        closes.append(price)
    return closes


def _generate_range_path(rng: random.Random, bars: int, center: float, half_width: float, vol_per_bar: float) -> list[float]:
    """Ornstein-Uhlenbeck-ish mean reverting path around `center`."""
    price = center
    mean_reversion = 0.08
    closes: list[float] = [price]
    for _ in range(bars):
        shock = rng.gauss(0.0, vol_per_bar)
        price = price + mean_reversion * (center - price) + shock * half_width
        price = max(min(price, center + half_width * 1.5), center - half_width * 1.5)
        closes.append(price)
    return closes


def _bars_from_closes(closes: Sequence[float], rng: random.Random, bar_vol: float) -> list[tuple[float, float, float]]:
    """Build (high, low, close) tuples with intra-bar wicks."""
    bars = []
    for close in closes:
        wick = abs(rng.gauss(0.0, bar_vol)) * close
        high = close + wick * abs(rng.random())
        low = close - wick * abs(rng.random())
        bars.append((high, low, close))
    return bars


def _ticks_from_range(closes: Sequence[float], rng: random.Random, tick_vol: float) -> list[tuple[float, float, float]]:
    return _bars_from_closes(closes, rng, tick_vol)


def _classify_regime_label(rng: random.Random, config: SimConfig) -> str:
    roll = rng.random()
    if roll < config.trend_regime_probability:
        return "TREND"
    if roll < config.trend_regime_probability + config.range_regime_probability:
        return "RANGE"
    return "CHOP"


# ---------------------------------------------------------------------------
# Trend-leg geometry: legacy vs improved target ceiling
# ---------------------------------------------------------------------------


def _legacy_trend_target(stop_distance: float, reward_multiple: float, volatility: float, config: SimConfig) -> float:
    """Pre-improvement: min(target, max(vol*2.0, stop*1.25))."""
    target = stop_distance * reward_multiple
    return min(target, max(volatility * config.trend_volatility_ceiling_multiple, stop_distance * config.trend_stop_floor_multiple))


def _improved_trend_target(stop_distance: float, reward_multiple: float, volatility: float, config: SimConfig) -> float:
    """Post-improvement: ceiling cannot fall below stop*min_rr."""
    target = stop_distance * reward_multiple
    min_rr_floor = stop_distance * max(config.trend_min_risk_reward, 1.0)
    volatility_ceiling = max(volatility * config.trend_volatility_ceiling_multiple, stop_distance * config.trend_stop_floor_multiple)
    if target > volatility_ceiling:
        return max(volatility_ceiling, min_rr_floor)
    return target


def _simulate_trend_leg(
    bars: list[tuple[float, float, float]],
    side: str,
    stop_distance_percent: float,
    target_distance_percent: float,
    config: SimConfig,
    rng: random.Random,
) -> dict:
    """Replay one trend entry; returns net pnl fraction + exit reason."""
    if not bars:
        return {"net_fraction": 0.0, "exit_reason": "no_path", "filled": False}
    entry = bars[0][2]
    stop_frac = stop_distance_percent / 100.0
    target_frac = target_distance_percent / 100.0
    if side == "long":
        stop_price = entry * (1.0 - stop_frac)
        target_price = entry * (1.0 + target_frac)
    else:
        stop_price = entry * (1.0 + stop_frac)
        target_price = entry * (1.0 - target_frac)

    slip = config.trend_slippage_bps / 10_000.0
    entry_fill = entry * (1.0 + slip) if side == "long" else entry * (1.0 - slip)
    round_trip_cost = (config.trend_fee_bps + config.trend_exit_fee_bps) / 10_000.0 + 2 * slip

    exit_reason = "time_exit"
    exit_price = bars[min(config.trend_max_hold_bars, len(bars) - 1)][2]
    for high, low, close in bars[1: config.trend_max_hold_bars + 1]:
        if side == "long":
            if low <= stop_price:
                exit_price, exit_reason = stop_price, "stop_loss"
                break
            if high >= target_price:
                exit_price, exit_reason = target_price, "take_profit"
                break
        else:
            if high >= stop_price:
                exit_price, exit_reason = stop_price, "stop_loss"
                break
            if low <= target_price:
                exit_price, exit_reason = target_price, "take_profit"
                break

    if side == "long":
        gross = (exit_price - entry_fill) / entry_fill
    else:
        gross = (entry_fill - exit_price) / entry_fill
    net = gross - round_trip_cost
    return {"net_fraction": net, "exit_reason": exit_reason, "filled": True, "rr": target_distance_percent / stop_distance_percent}


def _trend_passes_rr_gate(target_distance: float, stop_distance: float, config: SimConfig) -> bool:
    return (target_distance / stop_distance) >= config.trend_min_risk_reward


# ---------------------------------------------------------------------------
# Micro-leg geometry: edge reversion
# ---------------------------------------------------------------------------


def _simulate_micro_leg(
    ticks: list[tuple[float, float, float]],
    side: str,
    lower: float,
    upper: float,
    config: SimConfig,
    rng: random.Random,
    *,
    oos_discount: float,
    stop_fraction: float | None = None,
    target_fraction: float | None = None,
) -> dict:
    """Replay one micro-grid edge-reversion entry on second ticks."""
    span = upper - lower
    if span <= 0:
        return {"net_fraction": 0.0, "exit_reason": "invalid_span", "filled": False}
    stop_frac = config.micro_stop_fraction if stop_fraction is None else stop_fraction
    target_frac = config.micro_target_fraction if target_fraction is None else target_fraction
    entry = lower + span * config.micro_entry_edge_fraction if side == "long" else upper - span * config.micro_entry_edge_fraction
    stop = entry - span * stop_frac if side == "long" else entry + span * stop_frac
    target = entry + span * target_frac if side == "long" else entry - span * target_frac

    # Passive post-only fill: only fills if a tick wick reaches the entry.
    filled = False
    for high, low, close in ticks[: config.micro_max_hold_seconds]:
        if side == "long" and low <= entry:
            filled = True
            break
        if side == "short" and high >= entry:
            filled = True
            break
    if not filled:
        return {"net_fraction": 0.0, "exit_reason": "limit_expired", "filled": False}

    # Outcome: edge reversion succeeds with the (discounted) response rate.
    success_rate = config.micro_reversal_response_rate * oos_discount
    success = rng.random() < success_rate
    slip = config.micro_slippage_bps / 10_000.0
    round_trip_cost = (config.micro_maker_fee_bps + config.micro_taker_fee_bps) / 10_000.0 + 2 * slip
    if success:
        exit_price = target
        exit_reason = "take_profit"
    else:
        exit_price = stop
        exit_reason = "stop_loss"
    if side == "long":
        gross = (exit_price - entry) / entry
    else:
        gross = (entry - exit_price) / entry
    net = gross - round_trip_cost
    return {"net_fraction": net, "exit_reason": exit_reason, "filled": True, "rr": target_frac / stop_frac}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


@dataclass
class LegStats:
    trades: int = 0
    filled: int = 0
    wins: int = 0
    losses: int = 0
    net_fractions: list = field(default_factory=list)
    rr_blocked: int = 0
    total_attempted: int = 0

    def add(self, result: dict, rr_passed: bool = True) -> None:
        self.total_attempted += 1
        if not rr_passed:
            self.rr_blocked += 1
            return
        if not result.get("filled"):
            return
        self.trades += 1
        self.filled += 1
        net = result["net_fraction"]
        self.net_fractions.append(net)
        if net > 0:
            self.wins += 1
        elif net < 0:
            self.losses += 1

    def summary(self, notional: float) -> dict:
        n = max(len(self.net_fractions), 1)
        net_pnl = [v * notional for v in self.net_fractions]
        return {
            "attempted": self.total_attempted,
            "rr_blocked": self.rr_blocked,
            "rr_block_rate": round(self.rr_blocked / max(self.total_attempted, 1), 4),
            "trades_filled": self.trades,
            "fill_rate_of_attempted": round(self.trades / max(self.total_attempted, 1), 4),
            "win_rate": round(self.wins / n, 4) if self.net_fractions else 0.0,
            "avg_net_pnl_usdt": round(statistics.mean(net_pnl), 6) if net_pnl else 0.0,
            "median_net_pnl_usdt": round(statistics.median(net_pnl), 6) if net_pnl else 0.0,
            "total_net_pnl_usdt": round(sum(net_pnl), 6),
            "std_net_pnl_usdt": round(statistics.pstdev(net_pnl), 6) if len(net_pnl) > 1 else 0.0,
            "expectancy_per_fill_usdt": round(statistics.mean(net_pnl), 6) if net_pnl else 0.0,
        }


def run_simulation(config: SimConfig, paths: int) -> dict:
    rng = random.Random(config.seed)
    legacy_trend = LegStats()
    improved_trend = LegStats()
    legacy_micro = LegStats()
    improved_micro = LegStats()

    for _ in range(paths):
        label = _classify_regime_label(rng, config)
        if label == "TREND":
            drift = rng.choice([-1, 1]) * rng.uniform(0.0006, 0.0025)
            vol = rng.uniform(0.004, 0.012)
            closes = _generate_trend_path(rng, config.bars_per_path, drift, vol)
            bars = _bars_from_closes(closes, rng, vol * 0.6)
            side = "long" if drift > 0 else "short"
            volatility_percent = vol * 100 * 1.6  # realized-vol proxy
            stop_distance = config.trend_stop_distance_percent

            legacy_target = _legacy_trend_target(stop_distance, config.trend_reward_multiple, volatility_percent, config)
            improved_target = _improved_trend_target(stop_distance, config.trend_reward_multiple, volatility_percent, config)

            legacy_rr_pass = _trend_passes_rr_gate(legacy_target, stop_distance, config)
            improved_rr_pass = _trend_passes_rr_gate(improved_target, stop_distance, config)

            legacy_res = _simulate_trend_leg(bars, side, stop_distance, legacy_target, config, rng)
            improved_res = _simulate_trend_leg(bars, side, stop_distance, improved_target, config, rng)

            legacy_trend.add(legacy_res, rr_passed=legacy_rr_pass)
            improved_trend.add(improved_res, rr_passed=improved_rr_pass)

        if label == "RANGE":
            center = 100.0
            half_width = 100.0 * config.micro_width_percent / 100.0 / 2
            vol = rng.uniform(0.0008, 0.0025)
            closes = _generate_range_path(rng, config.seconds_per_path, center, half_width, vol)
            ticks = _ticks_from_range(closes, rng, vol * 0.7)
            lower, upper = center - half_width, center + half_width
            side = rng.choice(["long", "short"])
            # Legacy: full in-sample response rate (no walk-forward), thin z,
            # and the legacy 0.20/0.50 geometry that loses to costs.
            legacy_res = _simulate_micro_leg(ticks, side, lower, upper, config, rng, oos_discount=1.0)
            # Improved: walk-forward + tighter z discount the raw response rate,
            # and the cost-aware geometry (tighter stop, wider target) keeps
            # expectancy positive out of sample.
            improved_res = _simulate_micro_leg(
                ticks, side, lower, upper, config, rng,
                oos_discount=config.micro_oos_discount,
                stop_fraction=config.micro_stop_fraction_improved,
                target_fraction=config.micro_target_fraction_improved,
            )
            legacy_micro.add(legacy_res)
            improved_micro.add(improved_res)

    return _assemble_report(config, paths, legacy_trend, improved_trend, legacy_micro, improved_micro)


def _assemble_report(config: SimConfig, paths: int, legacy_trend: LegStats, improved_trend: LegStats, legacy_micro: LegStats, improved_micro: LegStats) -> dict:
    notional = config.notional_usdt

    def availability(p_regime_allow: float, p_governor: float, p_fill: float, leg_stats: LegStats) -> float:
        geometry_pass = leg_stats.trades / max(leg_stats.total_attempted, 1)
        return config.p_candidate_pass * p_regime_allow * geometry_pass * p_governor * config.p_risk_accept * p_fill

    return {
        "schema": "bfa_montecarlo_strategy_sim_v1",
        "config": {
            "paths": paths,
            "regime_mix": {
                "TREND": config.trend_regime_probability,
                "RANGE": config.range_regime_probability,
                "CHOP": config.chop_regime_probability,
            },
            "notional_usdt": notional,
            "trend_min_risk_reward": config.trend_min_risk_reward,
            "micro_oos_discount": config.micro_oos_discount,
        },
        "trend_leg": {
            "legacy": {
                **legacy_trend.summary(notional),
                "availability_per_cycle": round(availability(config.p_regime_allow_trend, config.p_governor_accept_legacy, config.p_fill_limit_trend, legacy_trend), 6),
            },
            "improved": {
                **improved_trend.summary(notional),
                "availability_per_cycle": round(availability(config.p_regime_allow_trend, config.p_governor_accept_improved, config.p_fill_limit_trend, improved_trend), 6),
            },
        },
        "micro_leg": {
            "legacy": {
                **legacy_micro.summary(notional),
                "availability_per_cycle": round(availability(config.p_regime_allow_micro, config.p_governor_accept_legacy, config.p_fill_limit_micro_legacy, legacy_micro), 6),
            },
            "improved": {
                **improved_micro.summary(notional),
                "availability_per_cycle": round(availability(config.p_regime_allow_micro, config.p_governor_accept_improved, config.p_fill_limit_micro_improved, improved_micro), 6),
            },
        },
        "end_to_end": {
            "legacy_cycle_trade_probability": round(
                availability(config.p_regime_allow_trend, config.p_governor_accept_legacy, config.p_fill_limit_trend, legacy_trend)
                + availability(config.p_regime_allow_micro, config.p_governor_accept_legacy, config.p_fill_limit_micro_legacy, legacy_micro),
                6,
            ),
            "improved_cycle_trade_probability": round(
                availability(config.p_regime_allow_trend, config.p_governor_accept_improved, config.p_fill_limit_trend, improved_trend)
                + availability(config.p_regime_allow_micro, config.p_governor_accept_improved, config.p_fill_limit_micro_improved, improved_micro),
                6,
            ),
        },
    }


def _print_report(report: dict) -> None:
    cfg = report["config"]
    print("=" * 72)
    print("Monte Carlo strategy simulation (research only, no exchange/live state)")
    print("=" * 72)
    print(f"paths={cfg['paths']}  regime mix={cfg['regime_mix']}  notional={cfg['notional_usdt']}U")
    print()
    for leg in ("trend_leg", "micro_leg"):
        print(f"--- {leg} ---")
        for variant in ("legacy", "improved"):
            s = report[leg][variant]
            print(
                f"  [{variant:8s}] attempted={s['attempted']:5d} "
                f"rr_block_rate={s.get('rr_block_rate', 0):.3f} "
                f"fill_rate={s['fill_rate_of_attempted']:.3f} "
                f"win_rate={s['win_rate']:.3f} "
                f"exp/fill={s['expectancy_per_fill_usdt']:+.4f}U "
                f"total_net={s['total_net_pnl_usdt']:+.3f}U "
                f"avail/cycle={s['availability_per_cycle']:.4%}"
            )
        print()
    e2e = report["end_to_end"]
    print("--- end-to-end ---")
    print(f"  legacy   cycle trade probability : {e2e['legacy_cycle_trade_probability']:.4%}")
    print(f"  improved cycle trade probability : {e2e['improved_cycle_trade_probability']:.4%}")
    ratio = e2e["improved_cycle_trade_probability"] / max(e2e["legacy_cycle_trade_probability"], 1e-9)
    print(f"  availability uplift factor       : {ratio:.2f}x")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", action="store_true", help="emit JSON to stdout instead of a human report")
    parser.add_argument("--output", type=str, default=None, help="write JSON report to this path")
    args = parser.parse_args()

    config = SimConfig(seed=args.seed)
    report = run_simulation(config, args.paths)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {out}")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
