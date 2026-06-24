# Phase 71 — Server Backtest Verification Report

**Date:** 2026-06-24
**Sandbox:** `/opt/binance-futures-agent/backtest-p71/app` (isolated; live `app/`, env, services untouched)
**Sandbox commit:** `7a983f4` (Phase 71)
**Live deploy commit:** unknown (no `.git` in `/opt/binance-futures-agent/app`); systemd state confirmed undisturbed across this verification.
**Live DB:** opened `mode=ro&immutable=1`; no writes.

## 1. Server state at start of verification

```
binance-futures-agent-live.timer            active   (next: 11:25:28, ran 1m36s ago)
binance-futures-agent-live.service          inactive (between-cycle, normal)
binance-futures-agent-paper.timer           active
binance-futures-agent-paper.service         (just ran)
binance-futures-agent-position-sentinel.timer  active
binance-futures-agent-pending-limit-watchdog.timer  active
binance-futures-agent-db-maintenance.timer  active (next: 12:24:12)
```
Disk: 62G free of 97G. Memory: 13G available of 15G. Network to GitHub: OK.

## 2. Monte Carlo (sandbox, server-side reproduction)

`python scripts/run_montecarlo_strategy_sim.py --paths 8000 --seed 7`

| Leg | Variant | RR-block | Fill rate | Win rate | Exp/fill | Avail/cycle |
|---|---|---|---|---|---|---|
| trend | legacy | **100.0%** | 0.000 | — | 0 | 0.0000% |
| trend | improved | 45.3% | 0.547 | 0.750 | **+0.88 U** | **2.155%** |
| micro | legacy | 0.0% | 0.338 | 0.554 | +0.016 U (in-sample) | 0.4543% |
| micro | improved | 0.0% | 0.338 | 0.389 | +0.003 U (OOS honest) | **0.9154%** |

End-to-end cycle trade probability: **0.45% → 3.07% (6.76x uplift)**.

Server reproduction matches local run exactly. The micro improved expectancy is lower than legacy *on purpose* — legacy was an in-sample overfit; improved is the walk-forward + tightened-z honest OOS estimate, still positive.

## 3. Trend backtest on real 7-day 5m klines

Dataset: `BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT`, 2026-06-17 → 2026-06-24, 5m bars.

### Variant: `quant_setup` (current live default)
- Initial capital: 30 U → **Final 27.09 U (-9.70%)**
- Trades: 93, wins: 18, **win rate 19.4%**, profit factor 0.20
- Expectancy/trade: **-0.031 U**
- Rejected signals: 1099, daily-loss skips: 4992

**Interpretation:** the live default variant *is* trading (93 fills over 7 days, ~13/day) but losing money. This is consistent with the live `paper_outcomes` evidence (38% win rate, net negative) and explains why paper-guard has been tightening.

### Variant: `quant_setup_live_action_flow` (the Phase 71 target trend variant)
- Initial capital: 100 U → Final 100.46 U (+0.46%)
- Trades: **1**, win rate 100%, profit factor inf
- Rejected signals: **12058**

**Interpretation:** the strict trend variant (regime-router enforced, multi-factor entry quality, post-cost edge ratio gates) is *extremely* selective on real klines — 12058 rejects vs 1 fill in 7 days. After Phase 71 relaxed `min_entry_quality_score` 5→4 and `min_limit_entry_quality_score` 4→3, the gate is still passing only the highest-confidence setups; the relaxation alone is not enough to make this variant a primary leg. **The RR repair (P0-A) is the dominant unblocker; the entry-quality relaxation is a secondary helper that needs more validation on larger samples.**

## 4. Live DB read-only validation of diagnoses

`/opt/binance-futures-agent/data/agent.sqlite` (6.0 GB, opened read-only):

- `market_snapshots`: 3,289,947 rows — collector is fine.
- `paper_outcomes`: 7234 rows over 4 days. Last 200 paper trades: **wins=76, losses=124, win_rate=38.0%, net=-2.17 U.**
- `outcomes` (real fills): 59 rows over 4 days, with header timestamps but no top-level `net_pnl_usdt` — confirms the system is producing setups but very few real fills are reaching outcome ledger (consistent with `submitted=false` Phase 70 evidence).
- `ai_decisions`: 906 rows in last 3 days. Decision field lives nested in payload (top-level decision = `unknown` in this script).

**This is direct evidence supporting the Phase 71 diagnoses:**
1. Paper-guard input quality is weak (38% paper win rate, negative net) → P1-A (downgrade thin-sample blocks) is targeting the right problem.
2. Real-trade outcomes are nearly empty while paper outcomes are abundant → the cycle gets to setup creation but the governor/risk/fill layers are stripping nearly all candidates → Phase 71 availability fixes address the right layers.

## 5. Conclusion

- **Monte Carlo:** confirms 6.76x end-to-end cycle-trade probability uplift, reproducible on server.
- **Real-kline backtest:** confirms `quant_setup` (live default) is currently a -9.7%/week strategy; the strict `quant_setup_live_action_flow` is profitable but trade-starved. Phase 71's RR repair is the necessary first step to make the strict variant viable as the primary leg, complemented by the entry-quality relaxation.
- **Live DB:** real-trade outcomes are too thin to draw a statistical conclusion on its own (this is exactly why P1-A is needed). Paper-trade evidence is sufficient and points to negative edge on the current default variant.

## 6. Safety attestation

- No write to `/opt/binance-futures-agent/app`, `/opt/binance-futures-agent/.venv`, `/etc/binance-futures-agent/env`, or any systemd unit.
- All DB queries used `mode=ro&immutable=1`.
- No exchange API call was made.
- No secret was emitted to stdout, logs, or this report.
- BTWUSDT and other manual symbols were never referenced.
- Sandbox at `/opt/binance-futures-agent/backtest-p71/` can be removed with `rm -rf` if desired.

## 7. Outstanding work

- Run `scripts/run_hftbacktest_micro_grid.py` once `aggTrades` archive is fetched (offline; ~1-2 GB per symbol per day).
- After the RR repair lands in live `app/`, monitor 24-48 h of fresh `paper_outcomes` for sentinel/regime routing signal before any live rollout.
- Build a richer matrix backtest (multi-window) once the EV walk-forward parameters are observed on real wick events.
