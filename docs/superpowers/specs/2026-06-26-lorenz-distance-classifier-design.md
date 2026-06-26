# Lorenzian Distance Classifier (LDC) Trend-Leg Confidence Modifier — Design

**Created:** 2026-06-26
**Status:** Design (pending implementation)
**Motivation:** The trend leg already has a LightGBM filter
(`src/bfa/strategy/ml_trend_filter.py`) that predicts **P(win)** of a setup —
"will this setup pay out?" That question is orthogonal to "given a market
state most similar to the current one, which direction did price tend to move
next?" The latter is an instance-based (kNN + Lorentzian distance) direction
question that LightGBM cannot answer. Live forensics in
`docs/current-live-strategy.md` repeatedly classify trend losses as
*wrong direction / poor entry* rather than tight stops — exactly the failure
mode a historical-analogy direction check would catch. LDC is added as a
**confidence modifier** (not a hard gate) so that, when the most similar
historical market states mostly moved *against* the chosen setup side,
confidence is depressed and the existing `min_confidence` gate naturally
rejects the trade — without LDC ever hard-rejecting on its own.

## Decisions (from brainstorming)

- **Role:** Confidence modifier. LDC predicts the future price direction from
  a small feature subset via kNN over Lorentzian distance; the agreement
  between that prediction and the setup side shifts confidence symmetrically
  (aligned lifts, opposed depresses). It does **not** short-circuit the
  decision. It is **not** a pure shadow mode — adjusted confidence flows into
  the existing `min_confidence` gate and AI review, so it changes live
  decisions once enabled. Therefore the flag defaults off and the release
  path goes offline → testnet/dry-run → live (operator-gated), never a
  "live-with-flag-on-but-not-affecting-decisions" pretense.
- **Label:** Future direction (binary). `y = sign(close[i+H] - close[i])`
  with a volatility-adaptive dead zone
  (`|ret| <= dead_zone_atr_mult * atr_percent[i]` → `y = 0`, "no direction").
  This is orthogonal to the LightGBM "+1.5R before -1R win" label.
- **Feature dimensionality:** A curated 5-feature kNN-friendly subset
  (`ema_spread`, `rsi`, `atr_percent`, `taker_ratio`, `mom_6`) rather than the
  full 14. Dropped: `hour_of_day` (cyclic → distorts kNN distance), `mom_12` /
  `micro_mom` (collinear with `mom_6`), `close_position` (correlated with
  `rsi`), `vol_change` (correlated with `taker_ratio`), the 15m features
  (forward-filled pseudo-information in kNN distance). The subset is **driven
  by the artifact's `feature_names` field**, so retraining with a different
  subset requires zero inference-code change. The chosen subset is a
  semantically-reasonable starting point; whether it is *optimal* must be
  validated offline (forward-selection / ablation) — not assumed.
- **Blend mode:** First version is **linear**
  (`delta = blend_strength * agreement`). An **asymmetric** mode (opposed
  penalty steeper than aligned reward) is designed into the artifact schema
  and inference code but **defaults off**; it is enabled only after the
  offline report proves it improves net lift. Nonlinear shape is a parameter
  to be validated, not assumed into the first version — matching this
  project's existing "linear/threshold first, sweep-complexity later" rhythm.
- **Release gate:** The offline training script enforces `lift > 1.0` (with a
  minimum passed-count floor) before LDC is allowed into shadow/testnet. If
  the report cannot show marginal lift over the existing
  filter + regime + factor stack, LDC is **not wired live** — only the
  artifact and report are kept as records.

## Architecture

LDC mirrors the existing LightGBM filter's deployment shape: offline-trained
persisted artifact → stateless inference module → additive, flag-default-off
wiring into `setup.py` → diagnostics persisted into `price_basis`. The only
difference is that LDC retunes confidence rather than short-circuiting the
decision.

### Components

1. **`src/bfa/strategy/ldc_classifier.py`** (new) — stateless inference.
   Loads a persisted artifact, exposes one function:
   `ldc_confidence_modifier(features, *, side, artifact, blend_strength,
   blend_mode, min_voters, fallback_agreement) -> (confidence_delta,
   diagnostics)`. All feature-subset selection, standardization, Lorentzian
   distance, and kNN voting are encapsulated here.
2. **`scripts/research/train_ldc_classifier.py`** (new) — offline training +
   validation. Reads `data/research/klines/{symbol}_5m.csv`, builds the
   reference dataset + scaler, produces the artifact at
   `data/research/ldc/`, and writes a lift-sweep report at
   `results/research/ldc_report.json`. Reuses `train_trend_filter.py`'s
   dependency-free `ema/rsi/atr_percent/load_csv`.
3. **`src/bfa/strategy/setup.py`** (modified) — adds profile flags, a
   `_ldc_confidence_modifier()` helper, a lazy-load cache, and the single
   wiring point in `build_trade_setup`.
4. **`src/bfa/backtest/models.py`** (modified) — adds an LDC-enabled variant
   (`quant_setup_ldc`) to `built_in_variants`, mirroring how
   `quant_setup_ml_trend` enables the LightGBM filter. `src/bfa/agent.py` is
   **not** modified: `_live_quant_setup_profile` already selects the live
   variant from `BFA_LIVE_QUANT_SETUP_VARIANT`.
5. **Tests** (new) — `tests/test_strategy_ldc_classifier.py` and
   `tests/test_strategy_setup_ldc.py`, plus a small-data smoke test for the
   training script.

### Wiring point in `build_trade_setup`

```
candidate features
   |
   +-> factor scores -> long/short -> side, edge, base_confidence   (existing)
   +-> entry/stop/target/notional sizing                             (existing)
   +-> confidence = _confidence(edge, factors)                       (existing, ~L330)
   |
   +-[NEW] LDC confidence modifier  <- here, AFTER confidence recompute,
   |      BEFORE the min_confidence gate:
   |        if use_ldc_confidence_modifier:
   |            ldc_delta, ldc_diag = _ldc_confidence_modifier(...)
   |            confidence = clip(confidence + ldc_delta, 0, ceiling)
   |            (ldc_diag later merged into price_basis.ldc_diagnostics)
   |
   +-> min_edge / min_confidence / min_risk_reward gates             (existing, ~L331-339)
   +-> ML trend filter (LightGBM) / boolean gates                    (existing, ~L358+)
```

**Why this point and this scope:** Placed after confidence recompute and
before the `min_confidence` gate so adjusted confidence flows naturally into
the existing gate and AI review inputs. It does **not** touch `edge` or
sizing — the live blast radius is confined to confidence, and the existing
`min_confidence` gate absorbs the effect. Touching edge/sizing is explicitly
out of scope and reserved as a future upgrade option.

### LDC vs LightGBM ordering and independence

```
confidence = _confidence(...)                  # base
+--[NEW] LDC modifier (retunes confidence)     # before min_confidence gate
+-> min_edge / min_confidence / min_risk_reward gates
+-> if use_ml_trend_filter:                    # LightGBM P(win) hard reject
        ml_verdict = ...                       # after LDC
```

- LDC runs **before** LightGBM. LDC retunes confidence; LightGBM reads only
  features (not confidence), so the ordering has no side effect on LightGBM.
  If LightGBM ran first, LDC would wastefully retune confidence on a trade
  LightGBM had already rejected, polluting diagnostics.
- The two are **independent and may both be on** (direction prediction +
  win-rate prediction = dual confirmation). Both default off; each is
  validated and enabled on its own merits; neither is forced on by the other.

## LDC Inference Model (`ldc_classifier.py`)

### Artifact format

A persisted file (`.npz`) under `data/research/ldc/`, containing:

- `reference_X` — reference feature matrix, shape `(N, D)` with D = subset size.
- `reference_y` — per-point future-direction labels in `{-1, 0, +1}`
  (`0` = dead zone, does not vote).
- `feature_names` — ordered subset (guarantees feature alignment at inference).
- `scaler_mean`, `scaler_std` — standardization parameters **fit at train
  time**, applied (not refit) at inference. kNN is scale-sensitive; this is
  mandatory.
- `meta` — `trained_at`, symbol set, `horizon_bars`, `dead_zone_atr_mult`,
  `n_reference`, used for refresh decisions and forensics.
- `blend_mode_supported` — flags which blend modes the artifact was validated
  with.

The full reference set (including dead-zone points) is kept. Dead-zone points
do not vote, but they participate in "who are the nearest neighbors" — a
query whose nearest neighbors are mostly dead-zone is itself the signal that
historically similar states tended to go nowhere.

### Distance metric — Lorentzian

```
d(x, ref) = Σ_i ln(1 + |x_i - ref_i|)
```

Computed on standardized features. The logarithm compresses large per-dimension
differences, making the metric more robust to outliers than Euclidean distance
— the reason it suits time-series kNN.

### kNN voting

- Take the nearest `k` neighbors (`k` is a training hyperparameter baked into
  the artifact, default 8).
- Only neighbors with `reference_y != 0` vote.
- `agreement = (same-direction votes - opposite-direction votes) / voting
  neighbors`, range `[-1, +1]`, `0` = neutral.
  - For a long setup, "same direction" = neighbor label `+1` (future up).
  - For a short setup, "same direction" = neighbor label `-1` (future down).
- If voting neighbors `< min_voters` (default 3), `delta = 0` and the reason
  `ldc_insufficient_voters` is recorded — LDC does not adjust on too-thin
  evidence.

### Inference function signature

```python
def ldc_confidence_modifier(
    features: Mapping[str, float | None],
    *,
    side: str,                      # "long" | "short"
    artifact: LdcArtifact,          # lazy-loaded, cached by path
    blend_strength: float = 0.06,
    blend_mode: str = "linear",     # "linear" | "asymmetric"
    min_voters: int = 3,
    fallback_agreement: float = 0.0,
) -> tuple[float, dict[str, Any]]:
    """Return (confidence_delta, diagnostics).

    confidence_delta is symmetric for "linear" and clipped to
    [-blend_strength, +blend_strength]. diagnostics contains agreement, k,
    voters, predict_direction, matching, reason_codes.
    """
```

### Blend modes

- **`linear`** (default): `delta = blend_strength * agreement`.
  - All aligned (`agreement=+1`) → +`blend_strength`.
  - All opposed (`agreement=-1`) → -`blend_strength`.
  - Half/half (`agreement=0`) → no change.
- **`asymmetric`** (designed, default off):
  - `agreement >= 0`: `delta = blend_strength * agreement` (linear reward).
  - `agreement < 0`: `delta = blend_strength * agreement * penalty_mult`
    (steeper penalty, `penalty_mult` baked into artifact after validation).

The linear first version is the zero-assumption baseline. Asymmetric is
designed in because trading loss/reward is asymmetric (a bad trade costs more
than a missed good one), but its exact shape is a parameter to be validated by
the offline sweep, not assumed into v1 — matching the project's
"linear/threshold first" rhythm. Switching modes is a one-field artifact
change; no inference-code or `setup.py` change.

### fail-closed (every path → delta=0 + reason, no exception escapes, no rejection)

- artifact path empty → `delta=0`, `ldc_artifact_path_missing`
- artifact load failure → `delta=0`, `ldc_artifact_load_failed:<Exc>`
- feature missing → fill with 0, demote credibility, still infer,
  record `ldc_missing_features:<names>`
- voting neighbors < min_voters → `delta=0`, `ldc_insufficient_voters`
- any inference exception → `delta=0`, `ldc_unavailable:<Exc>`
- non-trend leg → `delta=0`, `ldc_leg_not_trend`

No path amplifies confidence or rejects a trade. Worst case = LDC does
nothing = as if not installed. This is the strictest blast-radius guarantee
for a confidence modifier.

## Feature Subset & Reference Dataset

### Subset (D=5, starting point — optimality to be validated offline)

| Feature | Source field | Axis |
|---|---|---|
| `ema_spread` | `ema_spread_percent` | trend structure |
| `rsi` | `rsi` | momentum state |
| `atr_percent` | `atr_percent` | volatility scale |
| `taker_ratio` | `taker_buy_sell_ratio` | order-flow direction |
| `mom_6` | `kline_momentum_percent` | short-term momentum |

Dropped dimensions and why: `hour_of_day` (cyclic, distorts kNN distance),
`mom_12`/`micro_mom` (collinear with `mom_6`), `close_position` (correlated
with `rsi`), `vol_change` (correlated with `taker_ratio`), 15m features
(forward-filled pseudo-information). The subset is driven by the artifact's
`feature_names`, so retraining with a different subset is zero-code.

### Reference dataset construction

- **Input:** `data/research/klines/{symbol}_5m.csv` (same data
  `train_trend_filter.py` already uses — no new data source).
- **Per-bar reference point:** the 5 features + a future-direction label.
- **Label:**
  ```
  entry  = close[i]
  future = close[i + HORIZON]        # HORIZON default 36 bars (3h of 5m),
  ret    = (future - entry) / entry   # aligned with train_trend_filter forward window
  dz     = dead_zone_atr_mult * atr_percent[i]   # default mult 0.3
  y      = +1 if ret > +dz else -1 if ret < -dz else 0
  ```
  The dead zone is volatility-adaptive per point rather than a fixed
  percentage, which is more stable across regimes.
- **Time split:** per symbol, last 25% is validation (matches
  `train_trend_filter.py` to avoid leakage). Train segment → reference set;
  validation segment → the "to-predict" points for the lift sweep.
- **Scaler fit:** on train `reference_X` only; stored in the artifact;
  applied (never refit) at inference.
- **Size:** ~6 months × 23 symbols × 5m ≈ 50k–100k points. Loaded once and
  cached; D=5 does not need an approximate-NN library.

### Horizon note (honest)

LDC's default horizon is 3h, while the trend leg hold time is 10–30 min
(`_hold_minutes`). The scales intentionally differ: LDC provides a
*macro* "is this wave's direction right" confirmation, not a "will this
single trade pay" micro prediction. This complementarity with LightGBM is
the point. The horizon is an artifact field and can be shortened (e.g. 12
bars = 1h) if offline validation favors it.

## Offline Training & Validation (`train_ldc_classifier.py`)

### Flow

```
1. Load 5m klines per symbol.
2. Compute the 5 features (reuse train_trend_filter.py ema/rsi/atr_percent).
3. Per bar, build a reference point (features + future-direction label).
4. Per-symbol time split: last 25% = validation.
   - train segment -> reference_X, reference_y
   - val segment   -> "to-predict" points for the lift sweep
5. Fit scaler (mean/std) on train reference_X; store in artifact.
6. Emit artifact: data/research/ldc/ldc_reference_<tag>.npz
7. Run lift sweep over val; emit results/research/ldc_report.json
```

### Validation method — lift sweep

For each validation point `i` (using **only train points before `i`** as the
kNN reference — strict no-future-leakage):

- Run kNN at `i`; compute `agreement`.
- Assume a `base_confidence` (sweep several: 0.50, 0.58, 0.66).
- Assume setup side = the side the features imply (mirror
  `train_trend_filter.py`'s side decision — a proxy, see honest note below).
- `adjusted_conf = clip(base + blend * agreement, 0, 0.95)`.
- Realized outcome: did price actually move in `y[i]`'s direction?
- Report, per `(blend_strength, blend_mode, base_conf)`:
  - `win_rate_unadjusted` (passed at `base`),
  - `win_rate_adjusted` (passed at `adjusted_conf` under a `min_confidence`
    gate),
  - `lift = win_rate_adjusted / win_rate_unadjusted`,
  - `net_rejected` / `net_promoted` counts.

### Honest note on the proxy

The lift sweep uses "the side the features imply" as a **proxy** for the real
historical setup, because historical setup-decision records are incomplete.
This is the standard kNN-class validation approach, but it is **not** the
real setup path — it is an approximation. The report must be read with that
caveat; final live authorization remains an operator decision, not an
automated verdict.

### Report JSON (`results/research/ldc_report.json`, schema `bfa_ldc_research_v1`)

```json
{
  "schema": "bfa_ldc_research_v1",
  "artifact_path": "data/research/ldc/ldc_reference_2026-06-26.npz",
  "feature_names": ["ema_spread","rsi","atr_percent","taker_ratio","mom_6"],
  "horizon_bars": 36,
  "dead_zone_atr_mult": 0.3,
  "k": 8,
  "min_voters": 3,
  "n_train_reference": 58231,
  "n_val": 19844,
  "dead_zone_fraction_train": 0.31,
  "val_base_win_rate": 0.412,
  "blend_sweep": [
    {"blend_strength":0.06,"blend_mode":"linear","base_conf":0.58,
     "n_passed_unadjusted":4200,"win_rate_unadjusted":0.441,
     "n_passed_adjusted":3850,"win_rate_adjusted":0.478,
     "lift":1.084,"net_rejected":480,"net_promoted":130},
    {"blend_strength":0.06,"blend_mode":"asymmetric","base_conf":0.58, "...": "..."}
  ],
  "recommended_blend": {"strength":0.06,"mode":"linear","lift":1.084,
                        "reason":"max_lift_subject_to_min_n_passed"}
}
```

### Release gate (hard, enforced in-script)

- `lift > 1.0` **and** `n_passed_adjusted >= min_passed` (anti-collapse floor)
  → LDC has marginal value; may proceed to shadow/testnet.
- `lift <= 1.0` → LDC adds no value over the existing
  filter + regime + factor stack → **not wired live**; only artifact + report
  are kept as records.
- Recommended config chosen by `max_lift_subject_to_min_n_passed`, mirroring
  `calibrate_threshold_from_report`.

This gate is the design's hard stop: if the script cannot show lift, the
wiring does not happen. This prevents skipping validation and flipping the
flag on faith.

### Retrain cadence

The kNN reference set is stable; monthly retrain or retrain after a clear
market-structure change suffices. `artifact_meta.trained_at` supports refresh
decisions. No online learning / incremental reference-set updates (YAGNI).

## Profile Flags & Config Wiring

### `TradeSetupProfile` additions (mirror `use_ml_trend_filter` group)

```python
use_ldc_confidence_modifier: bool = False
ldc_artifact_path: str = ""
ldc_blend_strength: float = 0.06
ldc_blend_mode: str = "linear"          # "linear" | "asymmetric"
ldc_min_voters: int = 3
ldc_confidence_ceiling: float = 0.95
```

### `build_trade_setup` wiring

```python
confidence = _confidence(edge, factor_scores)
if setup_profile.use_ldc_confidence_modifier:
    ldc_delta, ldc_diag = _ldc_confidence_modifier(features, side, setup_profile)
    confidence = min(max(confidence + ldc_delta, 0.0),
                     setup_profile.ldc_confidence_ceiling)
    price_basis_ldc = ldc_diag
else:
    price_basis_ldc = None
```

`price_basis_ldc` is merged into `price_basis["ldc_diagnostics"]` during
`_price_basis` assembly (mirrors where `ml_trend_probability` is surfaced,
but placed in `price_basis` to match the forensics read location).

### `_ldc_confidence_modifier` helper (mirrors `_ml_trend_filter_rejection`)

- Lazy-load + cache artifact (`_LDC_ARTIFACT_CACHE`, mirrors
  `_ML_TREND_MODEL_CACHE`).
- Applies only to `strategy_leg == trend`; non-trend → `delta=0`,
  `ldc_leg_not_trend`.
- Pulls the 5 features from `features`, calls
  `ldc_classifier.ldc_confidence_modifier`.
- Any exception → `delta=0`, `ldc_unavailable:<ExcClass>`, no bubble.

### Variant-based enablement (mirrors how `ml_trend_filter` is enabled)

Profile flags are **not** wired through `config.py` env keys. The existing
`ml_trend_filter` is enabled the same way: its flags live on
`TradeSetupProfile`, and a variant in `src/bfa/backtest/models.py::built_in_variants`
turns them on via its `setup_profile` dict (see the `quant_setup_ml_trend`
variant, which sets `"use_ml_trend_filter": True`). The live trend profile is
selected by `_live_quant_setup_profile(config)` in `src/bfa/agent.py`, which
reads `BFA_LIVE_QUANT_SETUP_VARIANT` and returns that variant's
`setup_profile`. `_setup_profile` in `setup.py` filters a Mapping through
`TradeSetupProfile.__dataclass_fields__`, so any new field added to the
dataclass is **automatically supported** by variant dicts with no extra
plumbing.

LDC therefore follows the identical pattern:

1. Add the `ldc_*` fields to `TradeSetupProfile` (defaults off / empty).
2. Add a new variant `quant_setup_ldc` in `built_in_variants` (mirroring
   `quant_setup_ml_trend`) whose `setup_profile` dict sets
   `"use_ldc_confidence_modifier": True` plus the artifact path and blend
   settings. Optionally a `quant_setup_ml_trend_ldc` variant enabling both
   LDC and LightGBM for dual confirmation.
3. Live enablement = operator sets `BFA_LIVE_QUANT_SETUP_VARIANT` to the
   LDC-enabled variant. No new `BFA_LDC_*` env keys are introduced; the
   existing variant-selection env is the single control.

This is more consistent with the codebase than ad-hoc env keys and keeps the
single source of truth for "which flags are on" in the variant definition.

## Diagnostics

Persisted into `price_basis.ldc_diagnostics` (no new event type, no new DB
table — reuses the existing `trade_setups` payload):

```json
{
  "ldc_enabled": true,
  "ldc_agreement": 0.375,
  "ldc_predict_direction": "up",
  "ldc_setup_side": "long",
  "ldc_matching": "aligned",
  "ldc_voters": 7,
  "ldc_k": 8,
  "ldc_k_total": 8,
  "ldc_dead_zone_neighbors": 1,
  "ldc_confidence_delta": 0.0225,
  "ldc_confidence_before": 0.5821,
  "ldc_confidence_after": 0.6046,
  "ldc_blend_strength": 0.06,
  "ldc_blend_mode": "linear",
  "ldc_artifact_meta": {
    "trained_at": "2026-06-20",
    "symbol_set": 23,
    "horizon_bars": 36,
    "n_reference": 78412,
    "feature_names": ["ema_spread","rsi","atr_percent","taker_ratio","mom_6"]
  },
  "ldc_reason_codes": ["ldc_aligned"]
}
```

`reason_codes` added to setup `reasons` (mirrors the existing reasons-accumulate
pattern): `ldc_aligned` / `ldc_opposed` / `ldc_neutral` /
`ldc_insufficient_voters` / `ldc_unavailable:<Exc>` /
`ldc_missing_features:<names>`.

## Confidence Adjustment — Properties

- `agreement` centered at `[-1, +1]`; `0` = neutral.
- Linear blend: `delta = blend_strength * agreement`, clipped to
  `[-blend_strength, +blend_strength]`.
- Confidence ceiling clip at `0.95` (mirrors regime's
  `_clamp(..., 0.0, 0.95)`).
- `min_voters` default 3: below this, `delta=0` (avoid a few neighbors
  dominating the adjustment).
- **Cascade into `min_confidence` gate (how the "soft" modifier actually
  rejects):**
  - base 0.50, `min_confidence` 0.55, LDC opposed 6% → 0.44 → rejected by
    `confidence_below_profile_min`. This is the "soft-but-actually-filters"
    mechanism — driven by the **existing** gate, not a new LDC gate.
  - base 0.60, `min_confidence` 0.55, LDC opposed 6% → 0.54 → still passes.
    This is the intended "depress, don't hard-reject" behavior.

## Testing Strategy

Mirrors existing `tests/test_strategy_*.py` granularity and the
`ml_trend_filter` test shape. Tests use synthetic small reference sets and
synthetic klines CSVs (no real-data dependency), matching
`test_micro_grid_research_script.py`'s synthetic-data approach.

### `tests/test_strategy_ldc_classifier.py` — inference layer

- Lorentzian distance correctness (known input → known distance, incl.
  log-compression verification).
- kNN voting: all-aligned → `agreement=+1`; all-opposed → `-1`; half/half
  → `0`.
- Dead-zone neighbors do not vote but participate in nearest-neighbor
  selection.
- `voters < min_voters` → `delta=0` and `ldc_insufficient_voters`.
- Feature missing → 0-filled, demoted, still infers.
- Scaler: inference uses the trained scaler; never refits at inference.
- `blend_mode=asymmetric` penalizes opposed more steeply than it rewards
  aligned.

### `tests/test_strategy_setup_ldc.py` — wiring

- flag off → no `ldc_diagnostics`, confidence unchanged (zero regression).
- flag on + aligned → confidence rises, clipped at ceiling.
- flag on + opposed → confidence falls.
- flag on + non-trend leg → `delta=0`, `ldc_leg_not_trend`.
- flag on + empty artifact path → `delta=0`,
  `ldc_artifact_path_missing`, confidence unchanged.
- flag on + load raises → `delta=0`, `ldc_unavailable:<Exc>`, no bubble.
- LDC + LightGBM both on: LDC retunes confidence first, LightGBM rejects
  second; each diagnostic appears independently in `reasons`.
- Cascade: base 0.50, `min_confidence` 0.55, LDC opposed 6% → rejected by
  `confidence_below_profile_min`.

### Training-script smoke test

- `train_ldc_classifier.py` runs on small synthetic data, emits artifact +
  report.
- Report schema complete; `recommended_blend` logic correct (lift>1.0
  recommends, else records the reason).
- Time split has no leakage: a val point's kNN reference set contains only
  train points before it.

### Verification command (per AGENTS.md)

```bash
python -m unittest discover -s tests
git diff --check
```

## Release Order

```
Stage 0 — Offline validation (no live contact)
  Run train_ldc_classifier.py -> artifact + report
  Gate: lift > 1.0 AND n_passed_adjusted >= min_passed ?
    no  -> STOP. LDC not wired. Artifact + report kept as records only.
    yes -> Stage 1

Stage 1 — Code merged, flag default off (zero live impact)
  LDC code + tests merged on the branch.
  flag default false -> all existing variants behave identically.
  Tests green; git diff --check clean.
  Live behavior at this stage == LDC not installed.

Stage 2 — testnet/dry-run with flag on (NOT a live "shadow" pretense)
  A confidence modifier is NOT a pure shadow: adjusted confidence flows
  into min_confidence and AI review and changes decisions. So Stage 2 is
  testnet/dry-run with the flag on, comparing against the same-period
  baseline (flag off). Per AGENTS.md, testnet/dry-run/replay/live stay
  separated. A true zero-live-impact "shadow" is only the offline replay
  in Stage 0's val segment — there is no fake live-shadow mode here.

Stage 3 — Live enablement (explicit operator authorization)
  After testnet validation, the operator switches the live trend variant to
  an LDC-enabled variant by setting BFA_LIVE_QUANT_SETUP_VARIANT (e.g. to
  quant_setup_ldc) in the live env. Per docs/current-live-strategy.md, after
  a live-env change the operator must verify the server actually picked up
  the new value (ops live-status) and continue monitoring adjusted-decision
  forensics via price_basis.ldc_diagnostics.
```

## Out of Scope (YAGNI / honest boundaries)

- No online learning / incremental reference-set updates (offline monthly
  retrain suffices).
- No per-symbol reference sets (first version uses a mixed-universe set;
  per-symbol is a future optimization).
- No micro-grid / range leg (trend only).
- No sizing / edge adjustment (confidence only).
- No new event type / DB table (diagnostics go into existing `price_basis`).
- No LDC-specific kill-switch (fail-closed is already the strictest
  protection — worst case = LDC does nothing).
