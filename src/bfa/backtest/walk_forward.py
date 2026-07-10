"""Walk-forward validation orchestrator.

Expanding-window non-overlapping month folds. Grid search key knobs on the
training segment only; the held-out segment evaluates the single best combo.
The test runner never sees the grid (anti-overfit enforced in code).

Verdict pass bar (operator requirements):
1. OOS post-cost+funding positive: agg_net_pnl > 0 AND agg_profit_factor > 1.0
2. Full candidate flow, not post-hoc filtered (candidate_accounting present)
3. Edge covers stop probability: selected min_reward_cost_ratio >= 1.8
4. Sufficient sample: total_trades >= 30; ANY fold <30 -> unverified (no loophole)

Human gate: the verdict is a report; operator reviews before live resume. No
auto-wiring into strategy_promotion / live_resume_readiness.
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bfa.backtest.adapters import FoldRange, FoldResult, FoldRunner


# Grid knobs per leg. For trend, min_reward_cost_ratio maps to the live
# min_post_cost_edge_ratio knob (the live analog).
LEG_GRIDS: dict[str, dict[str, list[Any]]] = {
    "trend": {
        "min_post_cost_edge_ratio": [1.0, 1.8, 2.2, 2.5],
        "target_distance_multiplier": [1.5, 1.8],
        "stop_distance_multiplier": [0.82, 1.0],
    },
    "micro": {
        "min_reward_cost_ratio": [1.0, 1.8, 2.2, 2.5],
        "target_fraction": [0.5, 0.8, 1.0],
        "wick_depth_gate": ["current", "strict"],
    },
    "limit_range": {
        "min_reward_cost_ratio": [1.0, 1.8, 2.2, 2.5],
        "target_stop_geometry": ["a", "b"],
    },
}

# operator requirement 4: <30 trades => unverified
MIN_OOS_TRADES = 30
# operator requirement 2: edge must cover stop probability
MIN_REWARD_COST_RATIO = 1.8
# training-sample anti-overfit floor
MIN_TRAIN_TRADES = 10
THIN_PF_CEILING = 1.3


def grid_combos(leg: str) -> list[dict[str, Any]]:
    grid = LEG_GRIDS[leg]
    keys = list(grid.keys())
    combos: list[dict[str, Any]] = [{}]
    for key in keys:
        combos = [dict(c, **{key: val}) for c in combos for val in grid[key]]
    return combos


def _month_start(month: str) -> datetime:
    y, m = month.split("-")
    return datetime(int(y), int(m), 1, tzinfo=timezone.utc)


def _month_end(month: str) -> datetime:
    y, m = month.split("-")
    last_day = calendar.monthrange(int(y), int(m))[1]
    return datetime(int(y), int(m), last_day, 23, 59, 59, tzinfo=timezone.utc)


def expanding_month_folds(months: list[str], *, symbols: tuple[str, ...],
                          leg: str = "trend") -> list[FoldRange]:
    """Expanding window: fold k trains on months[0..k], tests on months[k+1]."""
    folds: list[FoldRange] = []
    for k in range(1, len(months)):
        train_months = months[:k]
        test_month = months[k]
        folds.append(FoldRange(
            leg=leg, symbols=symbols,
            train_start=_month_start(train_months[0]),
            train_end=_month_end(train_months[-1]),
            test_start=_month_start(test_month),
            test_end=_month_end(test_month),
        ))
    return folds


def classify_verdict(*, total_trades: int, agg_net_pnl: float, agg_profit_factor: float,
                     selected_ratio: float, full_candidate_flow: bool,
                     per_fold_trades: list[int]) -> str:
    if not full_candidate_flow:
        return "unverified"
    if any(t < MIN_OOS_TRADES for t in per_fold_trades):
        return "unverified"
    if total_trades < MIN_OOS_TRADES:
        return "unverified"
    if selected_ratio < MIN_REWARD_COST_RATIO:
        return "unverified"
    if agg_net_pnl <= 0 or agg_profit_factor <= 1.0:
        return "oos_negative"
    if agg_profit_factor <= THIN_PF_CEILING:
        return "oos_positive_thin"
    return "oos_positive"


def _profit_factor(trades: list[dict[str, Any]]) -> float:
    gp = sum(t["net_pnl_usdt"] for t in trades if t["net_pnl_usdt"] > 0)
    gl = abs(sum(t["net_pnl_usdt"] for t in trades if t["net_pnl_usdt"] < 0))
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def _win_rate(trades: list[dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    return sum(1 for t in trades if t["net_pnl_usdt"] > 0) / len(trades)


def _round_pf(pf: float) -> float | str:
    if pf == float("inf"):
        return "inf"
    return round(pf, 8)


def _numeric_pf(pf: Any) -> float:
    if isinstance(pf, (int, float)):
        return float(pf)
    return float("inf")


@dataclass
class WalkForwardValidator:
    runner: FoldRunner
    folds: list[FoldRange]
    cost_model_snapshot: dict[str, Any]
    min_train_trades: int = MIN_TRAIN_TRADES

    def _select_on_train(self, fold: FoldRange, combos: list[dict[str, Any]]) -> dict[str, Any]:
        best: dict[str, Any] | None = None
        for params in combos:
            res = self.runner.run_fold(fold, split="train", params=params)
            n = len(res.trades)
            if n < self.min_train_trades:
                continue
            pf = _profit_factor(res.trades)
            net = sum(t["net_pnl_usdt"] for t in res.trades)
            if net <= 0:
                continue
            score = pf
            if best is None or score > best["score"]:
                best = {"params": params, "score": score, "train_trades": n,
                        "train_net": net, "train_pf": pf}
        # fall back to the lowest-ratio combo if nothing met the train floor
        if best is None:
            res = self.runner.run_fold(fold, split="train", params=combos[0])
            best = {"params": combos[0], "score": 0.0, "train_trades": len(res.trades),
                    "train_net": sum(t["net_pnl_usdt"] for t in res.trades),
                    "train_pf": _profit_factor(res.trades)}
        return best

    def _ratio_from_params(self, params: dict[str, Any]) -> float:
        return float(params.get("min_post_cost_edge_ratio")
                     or params.get("min_reward_cost_ratio") or 0.0)

    def run(self) -> dict[str, Any]:
        leg = self.folds[0].leg if self.folds else "trend"
        combos = grid_combos(leg)
        selected_per_fold: dict[str, dict[str, Any]] = {}
        oos_results: dict[str, dict[str, Any]] = {}
        all_oos_trades: list[dict[str, Any]] = []
        per_fold_trades: list[int] = []
        selected_ratio = 0.0
        full_flow = True
        for fold in self.folds:
            sel = self._select_on_train(fold, combos)
            selected_per_fold[fold.test_start.strftime("%Y-%m")] = sel["params"]
            selected_ratio = max(selected_ratio, self._ratio_from_params(sel["params"]))
            test_res = self.runner.run_fold(fold, split="test", params=sel["params"])
            fold_trades = len(test_res.trades)
            per_fold_trades.append(fold_trades)
            all_oos_trades.extend(test_res.trades)
            if "trade_count" not in test_res.candidate_accounting:
                full_flow = False
            oos_results[fold.test_start.strftime("%Y-%m")] = {
                "trades": fold_trades,
                "net_pnl": round(sum(t["net_pnl_usdt"] for t in test_res.trades), 8),
                "win_rate": round(_win_rate(test_res.trades), 8),
                "profit_factor": _round_pf(_profit_factor(test_res.trades)),
                "funding_paid": test_res.funding_paid,
                "candidate_accounting": test_res.candidate_accounting,
            }
        total_trades = len(all_oos_trades)
        agg_net = sum(t["net_pnl_usdt"] for t in all_oos_trades)
        agg_pf = _profit_factor(all_oos_trades)
        verdict = classify_verdict(
            total_trades=total_trades, agg_net_pnl=agg_net, agg_profit_factor=agg_pf,
            selected_ratio=selected_ratio, full_candidate_flow=full_flow,
            per_fold_trades=per_fold_trades,
        )
        fold_pfs = [_numeric_pf(r["profit_factor"]) for r in oos_results.values()]
        worst_fold_pf = _round_pf(min(fold_pfs, default=0.0))
        return {
            "leg": leg,
            "folds": [{"fold_id": f"fold{i+1}",
                       "train": f"{fold.train_start.strftime('%Y-%m')}..{fold.train_end.strftime('%Y-%m')}",
                       "test": fold.test_start.strftime("%Y-%m")}
                      for i, fold in enumerate(self.folds)],
            "selected_params_per_fold": selected_per_fold,
            "oos_test_results": oos_results,
            "oos_aggregate": {
                "total_trades": total_trades,
                "agg_net_pnl": round(agg_net, 8),
                "agg_profit_factor": _round_pf(agg_pf),
                "worst_fold_pf": worst_fold_pf,
                "per_fold_trades": per_fold_trades,
            },
            "verdict": verdict,
            "pass_bar": {
                "min_oos_trades": MIN_OOS_TRADES,
                "min_reward_cost_ratio": MIN_REWARD_COST_RATIO,
                "min_train_trades": self.min_train_trades,
                "thin_pf_ceiling": THIN_PF_CEILING,
            },
            "cost_model_snapshot": self.cost_model_snapshot,
        }


def write_verdict(verdict: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
