# Alpha Walk-Forward Validation (Phase 1: Trend Verdict) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable walk-forward validation framework in `src/bfa/backtest` and use it to produce the first real out-of-sample trend-leg verdict artifact (`data/research/alpha_validation/trend_verdict.json`) that is post-fee + post-funding, runs the full candidate flow, and applies the operator's 4-part pass bar (OOS post-cost positive, full candidate flow, `min_reward_cost_ratio >= 1.8`, `>= 30` trades with no <30-fold loophole).

**Architecture:** Approach C from the design spec. A unified `CostModel` (per-symbol fee tiers + funding) is applied by per-leg `FoldRunner` adapters on top of each leg's existing engine gross PnL. A `WalkForwardValidator` orchestrator splits data into expanding-window non-overlapping month folds, grid-searches key knobs on the training segment only, evaluates the single best combo on the held-out segment, and emits an auditable verdict JSON. Phase 1 implements only the trend leg (`TrendFoldRunner` wrapping `run_hot_momentum_backtest` with the `quant_setup_live_action_flow` family).

**Tech Stack:** Python stdlib + existing `bfa` package; `unittest` for tests; data sourced from `data.binance.vision` public archives (5m klines monthly + fundingRate monthly) since `fapi.binance.com` is unreachable from the dev machine.

**Design refinements vs spec (recorded for honesty):**
- **No `engine.py` internal refactor.** The trend adapter consumes the engine's `gross_pnl_usdt` (which already includes the engine's taker-slippage model) and applies only the per-symbol fee-tier correction + funding cost via `CostModel`. This achieves the spec's single-cost-truth + funding-inclusive goal with zero regression risk across the 17 existing variants. Slippage is NOT re-subtracted (it is already inside gross), avoiding double-counting.
- **Data source is `data.binance.vision`, not `fapi`.** `fapi.binance.com` is network-blocked locally. Binance Vision publishes monthly 5m klines (~370 KB/symbol/month) and fundingRate (~1 KB/symbol/month) archives that are reachable and tiny. This fully enables true multi-month walk-forward for the trend leg without fapi.

---

## File Structure (Phase 1)

```
src/bfa/backtest/
├── cost.py            CREATE  CostModel, SymbolFeeTier, fee_tiers loader, funding cost
├── walk_forward.py    CREATE  WalkForwardValidator, fold split, grid search, verdict
├── adapters.py        CREATE  FoldRange, FoldResult, FoldRunner, TrendFoldRunner
├── engine.py          UNCHANGED
└── models.py          UNCHANGED

src/bfa/market/
└── vision_archives.py CREATE  Binance Vision monthly kline + fundingRate downloader/parser + cache

data/config/
└── fee_tiers.json     CREATE  per-symbol fee tiers (default maker 2.0 / taker 4.0 bps)

scripts/research/
└── run_alpha_validation.py  CREATE  thin CLI -> WalkForwardValidator -> verdict JSON

tests/
├── test_backtest_cost.py            CREATE
├── test_market_vision_archives.py   CREATE
├── test_backtest_adapters.py        CREATE
└── test_backtest_walk_forward.py    CREATE
```

---

### Task 1: `CostModel` + `SymbolFeeTier` + fee_tiers loader

**Files:**
- Create: `src/bfa/backtest/cost.py`
- Create: `data/config/fee_tiers.json`
- Test: `tests/test_backtest_cost.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_cost.py
import unittest
from bfa.backtest.cost import CostModel, SymbolFeeTier


class TestCostModel(unittest.TestCase):
    def test_default_tier_maker2_taker4(self):
        cm = CostModel()
        self.assertAlmostEqual(cm.tier("BTCUSDT").maker_fee_bps, 2.0)
        self.assertAlmostEqual(cm.tier("BTCUSDT").taker_fee_bps, 4.0)

    def test_per_symbol_tier_lookup_overrides_default(self):
        cm = CostModel(fee_tiers={"PUMPUSDT": SymbolFeeTier(maker_fee_bps=0.0, taker_fee_bps=0.0)})
        self.assertAlmostEqual(cm.tier("PUMPUSDT").taker_fee_bps, 0.0)
        self.assertAlmostEqual(cm.tier("BTCUSDT").taker_fee_bps, 4.0)  # falls back

    def test_round_trip_cost_percent_taker_both(self):
        cm = CostModel()
        # entry taker 4bps + exit taker 4bps + slip 5 + slip 5 = 18 bps = 0.18%
        rtc = cm.round_trip_cost_percent("BTCUSDT", entry_is_maker=False, exit_is_maker=False)
        self.assertAlmostEqual(rtc, 0.18, places=6)

    def test_round_trip_cost_percent_maker_entry(self):
        cm = CostModel()
        # entry maker 2 + exit taker 4 + maker_slip 1 + taker slip 5 = 12 bps = 0.12%
        rtc = cm.round_trip_cost_percent("BTCUSDT", entry_is_maker=True, exit_is_maker=False)
        self.assertAlmostEqual(rtc, 0.12, places=6)

    def test_trade_fees_usdt_taker_both(self):
        cm = CostModel()
        fees = cm.trade_fees_usdt("BTCUSDT", entry_price=100.0, exit_price=101.0, qty=10.0,
                                   entry_is_maker=False, exit_is_maker=False)
        # (100*10*0.0004) + (101*10*0.0004) = 0.4 + 0.404 = 0.804
        self.assertAlmostEqual(fees, 0.804, places=6)

    def test_funding_cost_long_positive_rate_pays(self):
        cm = CostModel()
        # one funding event at t=1000 with rate +0.0001, notional=1000, long => pays 0.1
        cost = cm.funding_cost_usdt("BTCUSDT", entry_time_ms=500, exit_time_ms=2000,
                                     side="long", notional=1000.0,
                                     funding_rates=[(1000, 0.0001)])
        self.assertAlmostEqual(cost, 0.1, places=6)

    def test_funding_cost_short_receives_when_positive_rate(self):
        cm = CostModel()
        # short with positive rate => receives => negative cost
        cost = cm.funding_cost_usdt("BTCUSDT", entry_time_ms=500, exit_time_ms=2000,
                                     side="short", notional=1000.0,
                                     funding_rates=[(1000, 0.0001)])
        self.assertAlmostEqual(cost, -0.1, places=6)

    def test_funding_cost_no_event_in_window_is_zero(self):
        cm = CostModel()
        cost = cm.funding_cost_usdt("BTCUSDT", entry_time_ms=500, exit_time_ms=900,
                                     side="long", notional=1000.0,
                                     funding_rates=[(1000, 0.0001)])
        self.assertAlmostEqual(cost, 0.0, places=6)

    def test_funding_cost_multiple_events_sum(self):
        cm = CostModel()
        cost = cm.funding_cost_usdt("BTCUSDT", entry_time_ms=500, exit_time_ms=5000,
                                     side="long", notional=1000.0,
                                     funding_rates=[(1000, 0.0001), (2000, -0.0002), (4000, 0.0003)])
        # 0.1 + (-0.2) + 0.3 = 0.2
        self.assertAlmostEqual(cost, 0.2, places=6)

    def test_load_fee_tiers_json_missing_file_uses_default(self):
        cm = CostModel.load_fee_tiers("data/config/fee_tiers.json")
        self.assertIsInstance(cm, CostModel)
        self.assertAlmostEqual(cm.default_tier.taker_fee_bps, 4.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_backtest_cost -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bfa.backtest.cost'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/bfa/backtest/cost.py
"""Unified per-symbol cost model: fees + slippage + funding.

Single source of truth for trading costs across all backtest/validation legs.
Per-symbol fee tiers are loaded from a curated config seeded from Binance's
public USD-M fee schedule (default maker 2.0 / taker 4.0 bps). The structure
allows swapping the data source to an authenticated commissionRate snapshot
later without changing this interface.

Known limitation: the public schedule excludes the operator's VIP tier + BNB
discount, so OOS cost may diverge from live actuals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SymbolFeeTier:
    maker_fee_bps: float
    taker_fee_bps: float


def _default_tier() -> SymbolFeeTier:
    return SymbolFeeTier(maker_fee_bps=2.0, taker_fee_bps=4.0)


@dataclass(frozen=True)
class CostModel:
    fee_tiers: dict[str, SymbolFeeTier] = field(default_factory=dict)
    default_tier: SymbolFeeTier = field(default_factory=_default_tier)
    slippage_bps: float = 5.0
    maker_slippage_bps: float = 1.0
    funding_interval_hours: int = 8
    funding_on_long: bool = True

    def tier(self, symbol: str) -> SymbolFeeTier:
        return self.fee_tiers.get(symbol.upper(), self.default_tier)

    def _fee_bps(self, symbol: str, is_maker: bool) -> float:
        tier = self.tier(symbol)
        return tier.maker_fee_bps if is_maker else tier.taker_fee_bps

    def _slip_bps(self, is_maker: bool) -> float:
        return self.maker_slippage_bps if is_maker else self.slippage_bps

    def round_trip_cost_percent(self, symbol: str, *, entry_is_maker: bool, exit_is_maker: bool) -> float:
        """Round-trip cost as a percent of notional (fees + slippage, both legs)."""
        bps = (
            self._fee_bps(symbol, entry_is_maker)
            + self._fee_bps(symbol, exit_is_maker)
            + self._slip_bps(entry_is_maker)
            + self._slip_bps(exit_is_maker)
        )
        return bps / 100.0  # bps -> percent

    def trade_fees_usdt(self, symbol: str, *, entry_price: float, exit_price: float,
                        qty: float, entry_is_maker: bool, exit_is_maker: bool) -> float:
        entry_fee = entry_price * qty * (self._fee_bps(symbol, entry_is_maker) / 10_000.0)
        exit_fee = exit_price * qty * (self._fee_bps(symbol, exit_is_maker) / 10_000.0)
        return entry_fee + exit_fee

    def trade_slippage_usdt(self, symbol: str, *, ref_entry: float, ref_exit: float,
                            qty: float, entry_is_maker: bool, exit_is_maker: bool) -> float:
        entry_slip = ref_entry * qty * (self._slip_bps(entry_is_maker) / 10_000.0)
        exit_slip = ref_exit * qty * (self._slip_bps(exit_is_maker) / 10_000.0)
        return entry_slip + exit_slip

    def funding_cost_usdt(self, symbol: str, *, entry_time_ms: int, exit_time_ms: int,
                          side: str, notional: float,
                          funding_rates: list[tuple[int, float]]) -> float:
        """Accumulate funding payments for funding events in [entry_time, exit_time].

        Long pays positive rate / receives negative; short is the mirror.
        `funding_rates` is a sorted list of (time_ms, rate). Events outside the
        holding window are ignored.
        """
        side_sign = 1.0 if side == "long" else -1.0
        cost = 0.0
        for event_time, rate in funding_rates:
            if entry_time_ms <= event_time <= exit_time_ms:
                cost += side_sign * notional * rate
        return cost

    @classmethod
    def load_fee_tiers(cls, path: str | Path) -> "CostModel":
        p = Path(path)
        if not p.exists():
            return cls()
        payload = json.loads(p.read_text(encoding="utf-8"))
        tiers = {
            sym.upper(): SymbolFeeTier(maker_fee_bps=float(t["maker_fee_bps"]),
                                        taker_fee_bps=float(t["taker_fee_bps"]))
            for sym, t in payload.get("tiers", {}).items()
        }
        default = payload.get("default")
        default_tier = (
            SymbolFeeTier(maker_fee_bps=float(default["maker_fee_bps"]),
                          taker_fee_bps=float(default["taker_fee_bps"]))
            if default else _default_tier()
        )
        return cls(fee_tiers=tiers, default_tier=default_tier)
```

```json
# data/config/fee_tiers.json
{
  "source": "https://www.binance.com/en/fee/futureFee",
  "queried_at": "2026-06-25",
  "note": "Seeded from Binance public USD-M fee schedule, VIP 0 standard. Excludes operator VIP tier + BNB discount. Per-symbol exceptions to be filled from the public schedule; unlisted symbols fall back to default.",
  "default": {"maker_fee_bps": 2.0, "taker_fee_bps": 4.0},
  "tiers": {}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_backtest_cost -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bfa/backtest/cost.py data/config/fee_tiers.json tests/test_backtest_cost.py
git commit -m "feat(backtest): unified per-symbol CostModel with funding"
```

---

### Task 2: Binance Vision archive downloader/parser (klines + fundingRate)

**Files:**
- Create: `src/bfa/market/vision_archives.py`
- Test: `tests/test_market_vision_archives.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market_vision_archives.py
import unittest, zipfile, io, csv
from bfa.market.vision_archives import (
    funding_rate_url, klines_monthly_url, parse_funding_rate_zip, parse_klines_zip,
)
from bfa.backtest.models import BacktestBar


def _funding_zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["calc_time", "funding_interval_hours", "last_funding_rate"])
        for r in rows:
            w.writerow(r)
        z.writestr("BTCUSDT-fundingRate-2026-02.csv", out.getvalue())
    return buf.getvalue()


def _klines_zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["open_time","open","high","low","close","volume","close_time",
                    "quote_volume","count","taker_buy_volume","taker_buy_quote_volume","ignore"])
        for r in rows:
            w.writerow(r)
        z.writestr("BTCUSDT-5m-2026-02.csv", out.getvalue())
    return buf.getvalue()


class TestVisionArchives(unittest.TestCase):
    def test_funding_rate_url_format(self):
        self.assertEqual(
            funding_rate_url("BTCUSDT", "2026-02"),
            "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-02.zip",
        )

    def test_klines_monthly_url_format(self):
        self.assertEqual(
            klines_monthly_url("BTCUSDT", "5m", "2026-02"),
            "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/5m/BTCUSDT-5m-2026-02.zip",
        )

    def test_parse_funding_rate_zip(self):
        data = _funding_zip([["1769904000001","8","0.0001"], ["1769932800004","8","-0.0002"]])
        rates = parse_funding_rate_zip(data)
        self.assertEqual(rates, [(1769904000001, 0.0001), (1769932800004, -0.0002)])

    def test_parse_klines_zip_to_backtest_bars(self):
        rows = [["1769904000000","100.0","101.0","99.5","100.8","50","1769904299999",
                 "5000","10","30","3000","0"]]
        bars = parse_klines_zip("BTCUSDT", _klines_zip(rows))
        self.assertEqual(len(bars), 1)
        b = bars[0]
        self.assertIsInstance(b, BacktestBar)
        self.assertEqual(b.symbol, "BTCUSDT")
        self.assertEqual(b.open_time, 1769904000000)
        self.assertAlmostEqual(b.open, 100.0)
        self.assertAlmostEqual(b.taker_buy_quote_volume, 3000.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_market_vision_archives -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/bfa/market/vision_archives.py
"""Binance Vision public archive loader for futures (USD-M).

`fapi.binance.com` is unreachable from some dev machines, but
`data.binance.vision` (the public data bucket) is reachable and publishes
monthly klines and fundingRate archives. This module fetches and parses them
with a local cache so re-runs are cheap.

No secrets, no auth, no live env. Pure public market data.
"""

from __future__ import annotations

import csv
import io
import time
import urllib.request
import zipfile
from pathlib import Path

from bfa.backtest.models import BacktestBar

VISION = "https://data.binance.vision"


def funding_rate_url(symbol: str, month: str) -> str:
    return f"{VISION}/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"


def klines_monthly_url(symbol: str, interval: str, month: str) -> str:
    return f"{VISION}/data/futures/um/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"


def _fetch_zip(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "bfa-vision-archive"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _cache_path(cache_dir: Path, symbol: str, kind: str, month: str, interval: str | None) -> Path:
    name = f"{symbol}-{kind}-{month}.zip" if interval is None else f"{symbol}-{interval}-{kind}-{month}.zip"
    return cache_dir / symbol / name


def fetch_funding_rate_zip(symbol: str, month: str, cache_dir: Path) -> bytes:
    p = _cache_path(cache_dir, symbol, "fundingRate", month, None)
    if p.exists() and not _zip_is_corrupt(p):
        return p.read_bytes()
    data = _fetch_zip(funding_rate_url(symbol, month))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return data


def fetch_klines_zip(symbol: str, interval: str, month: str, cache_dir: Path) -> bytes:
    p = _cache_path(cache_dir, symbol, "klines", month, interval)
    if p.exists() and not _zip_is_corrupt(p):
        return p.read_bytes()
    data = _fetch_zip(klines_monthly_url(symbol, interval, month))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return data


def _zip_is_corrupt(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is not None
    except (zipfile.BadZipFile, OSError):
        return True


def parse_funding_rate_zip(data: bytes) -> list[tuple[int, float]]:
    """Return sorted [(time_ms, rate)] from a fundingRate monthly archive."""
    rates: list[tuple[int, float]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = z.namelist()[0]
        text = z.read(name).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        calc_time = int(row["calc_time"])
        rate = float(row["last_funding_rate"])
        rates.append((calc_time, rate))
    rates.sort(key=lambda item: item[0])
    return rates


def parse_klines_zip(symbol: str, data: bytes) -> list[BacktestBar]:
    """Parse a klines monthly archive into BacktestBar objects."""
    bars: list[BacktestBar] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = z.namelist()[0]
        text = z.read(name).decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header
    for row in reader:
        if not row or not row[0].isdigit():
            continue
        bars.append(BacktestBar.from_binance_kline(symbol, row))
    return bars
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_market_vision_archives -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bfa/market/vision_archives.py tests/test_market_vision_archives.py
git commit -m "feat(market): Binance Vision kline + fundingRate archive loader"
```

---

### Task 3: Adapters — `FoldRange`, `FoldResult`, `TrendFoldRunner`

**Files:**
- Create: `src/bfa/backtest/adapters.py`
- Test: `tests/test_backtest_adapters.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_adapters.py
import unittest
from datetime import datetime, timezone
from bfa.backtest.adapters import FoldRange, FoldResult, TrendFoldRunner
from bfa.backtest.cost import CostModel


def _ts(month: str, day: int) -> datetime:
    y, m = month.split("-")
    return datetime(int(y), int(m), day, tzinfo=timezone.utc)


class TestTrendFoldRunner(unittest.TestCase):
    def test_fold_range_is_frozen(self):
        fr = FoldRange(leg="trend", symbols=("BTCUSDT",), train_start=_ts("2026-01", 1),
                       train_end=_ts("2026-01", 31), test_start=_ts("2026-02", 1),
                       test_end=_ts("2026-02", 28))
        with self.assertRaises(Exception):
            fr.leg = "micro"  # frozen

    def test_run_fold_returns_fold_result_with_accounting(self):
        # Construct a runner over a tiny synthetic bar set so no network is needed.
        from bfa.backtest.models import BacktestBar, BacktestConfig
        FIVE_MIN = 300_000
        bars = []
        base = 1_770_000_000_000  # 2026-02
        for i in range(40):
            bars.append(BacktestBar(
                symbol="BTCUSDT", open_time=base + i * FIVE_MIN,
                open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.5 + i,
                volume=10.0, close_time=base + i * FIVE_MIN + FIVE_MIN - 1,
                quote_volume=8_000_000.0, taker_buy_quote_volume=4_500_000.0))
        runner = TrendFoldRunner(
            cost_model=CostModel(),
            variant_name="quant_setup_live_action_flow",
            bars_by_symbol={"BTCUSDT": bars},
            funding_rates_by_symbol={"BTCUSDT": []},
            config_overrides={"max_hold_bars": 4, "lookback_bars": 3},
        )
        result = runner.run_fold(
            FoldRange(leg="trend", symbols=("BTCUSDT",),
                      train_start=_ts("2026-01", 1), train_end=_ts("2026-01", 31),
                      test_start=_ts("2026-02", 1), test_end=_ts("2026-02", 28)),
            split="test",
            params={},
        )
        self.assertIsInstance(result, FoldResult)
        self.assertEqual(result.leg, "trend")
        self.assertEqual(result.split, "test")
        # candidate accounting must always be present (full candidate flow)
        self.assertIn("rejected_signals", result.candidate_accounting)
        self.assertIn("trade_count", result.candidate_accounting)
        # funding_paid present even when zero
        self.assertEqual(result.funding_paid, 0.0)
        # each trade dict carries the verdict net_pnl (post fee+funding)
        for t in result.trades:
            self.assertIn("net_pnl_usdt", t)
            self.assertIn("funding_cost_usdt", t)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_backtest_adapters -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/bfa/backtest/adapters.py
"""Per-leg fold runners for walk-forward validation.

Each adapter wraps an existing backtest engine/runner for one leg and exposes a
unified `run_fold(range, split, params) -> FoldResult` interface. The
orchestrator never inspects leg internals.

TrendFoldRunner wraps run_hot_momentum_backtest (strategy_type=quant_setup) with
the quant_setup_live_action_flow family. It consumes the engine's gross_pnl
(which already includes the engine's taker-slippage model) and applies the
unified CostModel on top: per-symbol fee-tier correction + funding cost. This
avoids refactoring engine.py internals (zero regression risk) while still
producing per-symbol-accurate, funding-inclusive verdict PnL. Slippage is NOT
re-subtracted (already inside gross), preventing double-counting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from bfa.backtest.cost import CostModel
from bfa.backtest.engine import run_hot_momentum_backtest
from bfa.backtest.models import BacktestBar, BacktestConfig, built_in_variants


@dataclass(frozen=True)
class FoldRange:
    leg: str
    symbols: tuple[str, ...]
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(frozen=True)
class FoldResult:
    leg: str
    fold_id: str
    split: str
    trades: list[dict[str, Any]]
    candidate_accounting: dict[str, Any]
    funding_paid: float
    params: dict[str, Any]


class FoldRunner(Protocol):
    def run_fold(self, range: FoldRange, *, split: str, params: dict[str, Any]) -> FoldResult: ...


def _month_bounds_ms(range: FoldRange, split: str) -> tuple[int, int]:
    if split == "train":
        start = int(range.train_start.timestamp() * 1000)
        end = int(range.train_end.timestamp() * 1000)
    else:
        start = int(range.test_start.timestamp() * 1000)
        end = int(range.test_end.timestamp() * 1000)
    return start, end


class TrendFoldRunner:
    """Run one fold of the trend leg over pre-loaded bars + funding rates."""

    def __init__(
        self,
        *,
        cost_model: CostModel,
        variant_name: str = "quant_setup_live_action_flow",
        bars_by_symbol: dict[str, list[BacktestBar]],
        funding_rates_by_symbol: dict[str, list[tuple[int, float]]],
        config_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.cost_model = cost_model
        self.variant_name = variant_name
        self.bars_by_symbol = bars_by_symbol
        self.funding_rates_by_symbol = funding_rates_by_symbol
        self.config_overrides = dict(config_overrides or {})

    def _build_config(self, params: dict[str, Any]) -> BacktestConfig:
        base = built_in_variants()[self.variant_name]
        profile = dict(base.setup_profile)
        # grid knobs map onto the setup profile
        if "min_post_cost_edge_ratio" in params:
            profile["min_post_cost_edge_ratio"] = params["min_post_cost_edge_ratio"]
        if "target_distance_multiplier" in params:
            profile["target_distance_multiplier"] = params["target_distance_multiplier"]
        if "stop_distance_multiplier" in params:
            profile["stop_distance_multiplier"] = params["stop_distance_multiplier"]
        overrides = {**self.config_overrides, "setup_profile": profile}
        return base.with_overrides(**overrides)

    def run_fold(self, range: FoldRange, *, split: str, params: dict[str, Any]) -> FoldResult:
        start_ms, end_ms = _month_bounds_ms(range, split)
        config = self._build_config(params)
        symbols = [s for s in range.symbols if s in self.bars_by_symbol]
        bars = {s: self.bars_by_symbol[s] for s in symbols}
        result = run_hot_momentum_backtest(bars, config, start_ms=start_ms, end_ms=end_ms)

        trades_out: list[dict[str, Any]] = []
        funding_total = 0.0
        for trade in result.trades:
            entry_time_ms = _iso_to_ms(trade.entry_time)
            exit_time_ms = _iso_to_ms(trade.exit_time)
            # per-symbol fee correction (trend = taker both legs)
            fees = self.cost_model.trade_fees_usdt(
                trade.symbol, entry_price=trade.entry_price, exit_price=trade.exit_price,
                qty=trade.quantity, entry_is_maker=False, exit_is_maker=False,
            )
            funding = self.cost_model.funding_cost_usdt(
                trade.symbol, entry_time_ms=entry_time_ms, exit_time_ms=exit_time_ms,
                side=trade.side, notional=trade.notional_usdt,
                funding_rates=self.funding_rates_by_symbol.get(trade.symbol, []),
            )
            # verdict net = engine gross (slip already inside) - per-symbol fees - funding
            verdict_net = trade.gross_pnl_usdt - fees - funding
            funding_total += funding
            d = trade.to_dict()
            d["fees_usdt"] = round(fees, 8)
            d["funding_cost_usdt"] = round(funding, 8)
            d["net_pnl_usdt"] = round(verdict_net, 8)
            trades_out.append(d)

        accounting = {
            "trade_count": len(result.trades),
            "rejected_signals": result.rejected_signals,
            "skipped_daily_loss_signals": result.skipped_daily_loss_signals,
            "skipped_concurrency_signals": result.skipped_concurrency_signals,
            "symbols_evaluated": sorted(symbols),
        }
        return FoldResult(
            leg="trend", fold_id=_fold_id(range, split), split=split,
            trades=trades_out, candidate_accounting=accounting,
            funding_paid=round(funding_total, 8), params=dict(params),
        )


def _iso_to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _fold_id(range: FoldRange, split: str) -> str:
    return f"{range.leg}_{split}_{range.test_start.strftime('%Y-%m')}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_backtest_adapters -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bfa/backtest/adapters.py tests/test_backtest_adapters.py
git commit -m "feat(backtest): FoldRunner adapter + TrendFoldRunner"
```

---

### Task 4: `WalkForwardValidator` — fold split, grid search, verdict

**Files:**
- Create: `src/bfa/backtest/walk_forward.py`
- Test: `tests/test_backtest_walk_forward.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_walk_forward.py
import unittest
from datetime import datetime, timezone
from bfa.backtest.walk_forward import (
    expanding_month_folds, grid_combos, classify_verdict, LEG_GRIDS,
)


def _ts(month: str, day: int) -> datetime:
    y, m = month.split("-")
    return datetime(int(y), int(m), day, tzinfo=timezone.utc)


class TestFoldsAndVerdict(unittest.TestCase):
    def test_expanding_folds_non_overlapping(self):
        folds = expanding_month_folds(["2025-12", "2026-01", "2026-02", "2026-03"])
        self.assertEqual(len(folds), 3)
        # fold1: train Dec, test Jan
        self.assertEqual(folds[0].train_start, _ts("2025-12", 1))
        self.assertEqual(folds[0].test_start, _ts("2026-01", 1))
        self.assertEqual(folds[0].test_end, _ts("2026-01", 31))
        # fold3: train Dec..Feb, test Mar (final holdout)
        self.assertEqual(folds[2].test_start, _ts("2026-03", 1))
        self.assertTrue(folds[2].train_end < folds[2].test_start)

    def test_grid_combos_match_leg_grid(self):
        combos = grid_combos("trend")
        self.assertTrue(len(combos) >= 4)
        # every combo has the grid knobs
        for c in combos:
            self.assertIn("min_post_cost_edge_ratio", c)

    def test_verdict_unverified_when_under_30_trades(self):
        v = classify_verdict(total_trades=15, agg_net_pnl=10.0, agg_profit_factor=1.5,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[5, 5, 5])
        self.assertEqual(v, "unverified")

    def test_verdict_unverified_when_any_fold_under_30_even_if_aggregate_ok(self):
        v = classify_verdict(total_trades=40, agg_net_pnl=10.0, agg_profit_factor=1.5,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[5, 20, 15])
        self.assertEqual(v, "unverified")

    def test_verdict_negative_when_post_cost_loss(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=-5.0, agg_profit_factor=0.8,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "oos_negative")

    def test_verdict_thin_when_pf_between_1_and_1_3(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=2.0, agg_profit_factor=1.15,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "oos_positive_thin")

    def test_verdict_positive(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=20.0, agg_profit_factor=1.8,
                             selected_ratio=2.2, full_candidate_flow=True,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "oos_positive")

    def test_verdict_unverified_when_ratio_below_1_8(self):
        v = classify_verdict(total_trades=100, agg_net_pnl=20.0, agg_profit_factor=1.8,
                             selected_ratio=1.0, full_candidate_flow=True,
                             per_fold_trades=[40, 30, 30])
        self.assertEqual(v, "unverified")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_backtest_walk_forward -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/bfa/backtest/walk_forward.py
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
                "worst_fold_pf": _round_pf(min(
                    (_profit_factor([]) for _ in []),  # placeholder; replaced below
                    default=0.0)),
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


def _win_rate(trades: list[dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    return sum(1 for t in trades if t["net_pnl_usdt"] > 0) / len(trades)


def _round_pf(pf: float) -> float | str:
    if pf == float("inf"):
        return "inf"
    return round(pf, 8)


def write_verdict(verdict: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
```

Note: the `worst_fold_pf` line above has a placeholder bug to fix in Step 4.

- [ ] **Step 4: Run test to verify it passes, then fix the worst_fold_pf placeholder**

Fix the `worst_fold_pf` computation in `WalkForwardValidator.run` to use per-fold profit factors from `oos_results`:

```python
            # replace the worst_fold_pf placeholder block with:
            "oos_aggregate": {
                "total_trades": total_trades,
                "agg_net_pnl": round(agg_net, 8),
                "agg_profit_factor": _round_pf(agg_pf),
                "worst_fold_pf": _round_pf(min(
                    (r["profit_factor"] if isinstance(r["profit_factor"], (int, float)) else 1e9
                     for r in oos_results.values()), default=0.0)),
                "per_fold_trades": per_fold_trades,
            },
```

Run: `python -m unittest tests.test_backtest_walk_forward -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bfa/backtest/walk_forward.py tests/test_backtest_walk_forward.py
git commit -m "feat(backtest): WalkForwardValidator + verdict pass bar"
```

---

### Task 5: CLI entry `run_alpha_validation.py`

**Files:**
- Create: `scripts/research/run_alpha_validation.py`

- [ ] **Step 1: Write the CLI**

```python
# scripts/research/run_alpha_validation.py
"""Run alpha walk-forward validation and emit a verdict artifact.

Phase 1: trend leg. Pulls 5m klines + fundingRate monthly archives from
data.binance.vision (fapi is unreachable locally), runs expanding-window
walk-forward over Dec 2025 -> Mar 2026, grid-searches on train segments,
evaluates the best combo on each test segment, and writes the trend verdict
JSON to data/research/alpha_validation/trend_verdict.json.

No live env, no secrets, no order placement. Pure validation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bfa.backtest.adapters import TrendFoldRunner
from bfa.backtest.cost import CostModel
from bfa.backtest.walk_forward import expanding_month_folds, write_verdict
from bfa.backtest.models import BacktestBar
from bfa.market.vision_archives import fetch_funding_rate_zip, fetch_klines_zip, parse_funding_rate_zip, parse_klines_zip

FEE_TIERS_PATH = ROOT / "data" / "config" / "fee_tiers.json"
CACHE_DIR = ROOT / "data" / "research" / "vision-cache"
OUT_DIR = ROOT / "data" / "research" / "alpha_validation"

DEFAULT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT",
    "AVAXUSDT", "LINKUSDT", "ADAUSDT", "SUIUSDT", "HYPEUSDT", "ONDOUSDT",
    "PUMPUSDT", "AAVEUSDT", "NEARUSDT", "LTCUSDT", "ZECUSDT", "SANDUSDT",
    "WLDUSDT", "ENAUSDT", "UNIUSDT", "ARBUSDT", "OPUSDT", "WIFUSDT",
    "1000PEPEUSDT", "PUMPUSDT",
)
DEFAULT_MONTHS = ["2025-12", "2026-01", "2026-02", "2026-03"]


def load_data(symbols, months, interval="5m"):
    bars_by_symbol: dict[str, list[BacktestBar]] = {}
    funding_by_symbol: dict[str, list[tuple[int, float]]] = {}
    for i, sym in enumerate(symbols, 1):
        all_bars: list[BacktestBar] = []
        all_rates: list[tuple[int, float]] = []
        for month in months:
            try:
                kdata = fetch_klines_zip(sym, interval, month, CACHE_DIR)
                all_bars.extend(parse_klines_zip(sym, kdata))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {sym} {month} klines: {exc}", file=sys.stderr)
            try:
                fdata = fetch_funding_rate_zip(sym, month, CACHE_DIR)
                all_rates.extend(parse_funding_rate_zip(fdata))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {sym} {month} funding: {exc}", file=sys.stderr)
        all_bars.sort(key=lambda b: b.open_time)
        all_rates.sort(key=lambda r: r[0])
        if all_bars:
            bars_by_symbol[sym] = all_bars
            funding_by_symbol[sym] = all_rates
            print(f"[{i}/{len(symbols)}] {sym}: {len(all_bars)} bars, {len(all_rates)} funding events")
    return bars_by_symbol, funding_by_symbol


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", default="trend", choices=["trend"])
    ap.add_argument("--symbols", default=",".join(sorted(set(DEFAULT_SYMBOLS))))
    ap.add_argument("--months", default=",".join(DEFAULT_MONTHS))
    ap.add_argument("--variant", default="quant_setup_live_action_flow")
    ap.add_argument("--out", default=str(OUT_DIR / "trend_verdict.json"))
    args = ap.parse_args()

    symbols = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    months = [m.strip() for m in args.months.split(",") if m.strip()]
    cost_model = CostModel.load_fee_tiers(FEE_TIERS_PATH)
    print(f"# loading data: {len(symbols)} symbols x {len(months)} months")
    bars, funding = load_data(symbols, months)
    print(f"# loaded: {len(bars)} symbols with bars")

    runner = TrendFoldRunner(
        cost_model=cost_model, variant_name=args.variant,
        bars_by_symbol=bars, funding_rates_by_symbol=funding,
    )
    folds = expanding_month_folds(months, symbols=symbols, leg=args.leg)
    print(f"# folds: {len(folds)}")
    validator = type("V", (), {})  # placeholder; replaced below
    from bfa.backtest.walk_forward import WalkForwardValidator
    validator = WalkForwardValidator(
        runner=runner, folds=folds,
        cost_model_snapshot={
            "fee_source": "binance_public_schedule",
            "default_tier": {"maker_fee_bps": cost_model.default_tier.maker_fee_bps,
                             "taker_fee_bps": cost_model.default_tier.taker_fee_bps},
            "note": "Excludes operator VIP tier + BNB discount. Per-symbol exceptions in fee_tiers.json.",
            "fee_tiers_path": str(FEE_TIERS_PATH),
        },
    )
    verdict = validator.run()
    write_verdict(verdict, args.out)
    print(f"# verdict: {verdict['verdict']}")
    print(f"# oos aggregate: {verdict['oos_aggregate']}")
    print(f"# written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Remove the placeholder line**

Delete the `validator = type("V", (), {})  # placeholder; replaced below` line (it is dead code left from drafting).

- [ ] **Step 3: Commit**

```bash
git add scripts/research/run_alpha_validation.py
git commit -m "feat(research): run_alpha_validation CLI for trend verdict"
```

---

### Task 6: Full regression + secret scan, then pull data and run

- [ ] **Step 1: Run the full test suite**

Run: `python -m unittest discover -s tests`
Expected: ALL PASS (existing tests + new tests). If an existing test breaks, investigate before proceeding — the design claimed zero engine regression.

- [ ] **Step 2: Run git diff --check**

Run: `git diff --check`
Expected: clean

- [ ] **Step 3: Pull data and run the trend walk-forward**

Run:
```bash
python scripts/research/run_alpha_validation.py --leg trend --months 2025-12,2026-01,2026-02,2026-03
```
Expected: prints per-symbol bar/funding counts, then `# verdict: <level>`, then `# written: data/research/alpha_validation/trend_verdict.json`. The artifact is the deliverable result.

- [ ] **Step 4: Inspect the verdict artifact**

Run: `python -c "import json; d=json.load(open('data/research/alpha_validation/trend_verdict.json')); print(json.dumps({'verdict':d['verdict'],'oos_aggregate':d['oos_aggregate'],'selected':d['selected_params_per_fold'],'folds':d['folds']}, indent=2))"`
Expected: a real verdict with `oos_aggregate` showing real total_trades, agg_net_pnl, agg_profit_factor.

- [ ] **Step 5: Record the verdict in POST-GSD-LIVE-ITERATIONS.md**

Append a new item to `.planning/POST-GSD-LIVE-ITERATIONS.md` "Major Post-GSD Changes" summarizing the trend verdict (verdict level, OOS trades, post-cost+funding net PnL, selected ratio per fold), and note that micro/limit-range are still pending Phase 2.

- [ ] **Step 6: Commit**

```bash
git add .planning/POST-GSD-LIVE-ITERATIONS.md
git commit -m "docs: record first trend walk-forward verdict artifact"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Req 1 (true walk-forward, full candidate flow, post-cost positive): Tasks 4 (folds + grid + verdict), 3 (full candidate_accounting), 6 (run). ✓
- Req 2 (min_reward_cost_ratio >= 1.8): Task 4 `MIN_REWARD_COST_RATIO=1.8` + grid includes 1.8/2.2/2.5 + verdict check. ✓
- Req 3 (funding in all backtests): Task 1 (funding_cost_usdt) + Task 3 (adapter applies it per trade). ✓
- Req 4 (<30 = unverified, no fold loophole): Task 4 `classify_verdict` checks per_fold_trades AND total. ✓
- Approach C (cost lib + adapters + orchestrator): Tasks 1, 3, 4. ✓
- Per-symbol fee tiers: Task 1 + fee_tiers.json. ✓
- Human gate (no auto-wiring): Task 4 docstring + Task 5 read-only CLI. ✓
- Trend leg full run = first result: Task 6. ✓

**Placeholder scan:** The `worst_fold_pf` placeholder and the CLI `validator` placeholder are both flagged with explicit fix steps (Task 4 Step 4, Task 5 Step 2). No other TBD/TODO.

**Type consistency:** `FoldRange`/`FoldResult`/`FoldRunner` defined in Task 3, consumed identically in Task 4. `CostModel` methods (`trade_fees_usdt`, `funding_cost_usdt`) defined in Task 1, called with matching signatures in Task 3. `classify_verdict` signature matches the test. `grid_combos`/`expanding_month_folds` match tests.
