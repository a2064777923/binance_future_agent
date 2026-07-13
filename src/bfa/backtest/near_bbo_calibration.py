"""Walk-forward calibration for public near-BBO shadow labels.

The model is deliberately small: two regularized logistic surfaces for fill
and profitable-fill probability plus a ridge surface for conditional net bps.
Training refuses undersized or one-sided data instead of emitting confident
probabilities from a handful of fills.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


NUMERIC_FEATURES = (
    "aligned_microprice",
    "aligned_flow_change",
    "aligned_fast_flow",
    "favorable_reversal_bps",
    "volatility_bps",
    "momentum_bps",
    "near_bbo_regime_confidence",
    "near_bbo_range_position",
    "signal_persistence_ratio",
    "scout_adverse_bps",
    "quote_ttl_seconds",
    "queue_pressure_ratio",
    "log_queue_ahead_notional_usdt",
    "spread_bps",
    "target_bps",
    "stop_bps",
    "expected_round_trip_cost_bps",
    "log_trade_count",
    "shadow_max_hold_seconds",
    "shadow_queue_fill_mode_touch",
    "shadow_queue_fill_mode_trade_through",
    "shadow_queue_ahead_fraction",
    "shadow_evidence_exit_enabled",
    "shadow_confirmation_seconds",
    "shadow_confirmation_min_net_progress_bps",
    "shadow_adverse_selection_exit_bps",
    "shadow_profit_lock_activate_net_bps",
    "shadow_profit_lock_min_net_bps",
    "shadow_profit_lock_giveback_fraction",
)
CATEGORICAL_FEATURES = (
    "side_long",
    "lane_range_reversion",
    "lane_trend_pullback",
    "regime_range",
    "regime_trend",
)
MODEL_FEATURES = (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES)
MODEL_FEATURE_INDEX = {name: index for index, name in enumerate(MODEL_FEATURES)}
CONFIG_DOMAIN_FEATURES = (
    "quote_ttl_seconds",
    "expected_round_trip_cost_bps",
    "shadow_max_hold_seconds",
    "shadow_queue_fill_mode_touch",
    "shadow_queue_fill_mode_trade_through",
    "shadow_queue_ahead_fraction",
    "shadow_evidence_exit_enabled",
    "shadow_confirmation_seconds",
    "shadow_confirmation_min_net_progress_bps",
    "shadow_adverse_selection_exit_bps",
    "shadow_profit_lock_activate_net_bps",
    "shadow_profit_lock_min_net_bps",
    "shadow_profit_lock_giveback_fraction",
)


@dataclass(frozen=True)
class NearBboCalibrationConfig:
    min_labels: int = 500
    min_fills: int = 100
    min_profitable_fills: int = 20
    min_losing_fills: int = 20
    validation_fraction: float = 0.25
    l2: float = 0.02
    iterations: int = 800
    learning_rate: float = 0.05

    def __post_init__(self) -> None:
        if min(self.min_labels, self.min_fills, self.min_profitable_fills, self.min_losing_fills) <= 0:
            raise ValueError("calibration sample minimums must be positive")
        if not 0.10 <= self.validation_fraction <= 0.50:
            raise ValueError("validation_fraction must be between 0.10 and 0.50")
        if self.l2 <= 0 or self.iterations <= 0 or self.learning_rate <= 0:
            raise ValueError("calibration optimizer controls are invalid")


@dataclass(frozen=True)
class NearBboCalibrationPrediction:
    fill_probability: float
    win_probability: float
    expected_net_bps: float


class NearBboCalibrator:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        if str(payload.get("schema") or "") != "bfa_near_bbo_calibration_v1":
            raise ValueError("unsupported near-BBO calibration schema")
        try:
            self.feature_names = tuple(str(value) for value in payload["feature_names"])
            self.means = tuple(float(value) for value in payload["means"])
            self.scales = tuple(float(value) for value in payload["scales"])
            self.fill_intercept = float(payload["fill_model"]["intercept"])
            self.fill_coefficients = tuple(float(value) for value in payload["fill_model"]["coefficients"])
            self.win_intercept = float(payload["win_model"]["intercept"])
            self.win_coefficients = tuple(float(value) for value in payload["win_model"]["coefficients"])
            self.net_intercept = float(payload["net_model"]["intercept"])
            self.net_coefficients = tuple(float(value) for value in payload["net_model"]["coefficients"])
            raw_domain = payload["input_domain"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("malformed near-BBO calibration model") from exc
        if self.feature_names != MODEL_FEATURES:
            raise ValueError("calibration feature schema mismatch")
        expected = len(self.feature_names)
        vectors = (
            self.means,
            self.scales,
            self.fill_coefficients,
            self.win_coefficients,
            self.net_coefficients,
        )
        if any(len(values) != expected for values in vectors):
            raise ValueError("calibration vector length mismatch")
        if any(not all(math.isfinite(value) for value in values) for values in vectors):
            raise ValueError("calibration vectors must be finite")
        if any(value <= 0 for value in self.scales):
            raise ValueError("calibration scales must be positive")
        if not all(
            math.isfinite(value)
            for value in (self.fill_intercept, self.win_intercept, self.net_intercept)
        ):
            raise ValueError("calibration intercepts must be finite")
        if not isinstance(raw_domain, Mapping):
            raise ValueError("calibration input domain is malformed")
        self.input_domain: dict[str, tuple[float, float]] = {}
        try:
            for name in CONFIG_DOMAIN_FEATURES:
                bounds = raw_domain[name]
                minimum = float(bounds["minimum"])
                maximum = float(bounds["maximum"])
                if not math.isfinite(minimum) or not math.isfinite(maximum) or minimum > maximum:
                    raise ValueError
                self.input_domain[name] = (minimum, maximum)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("calibration input domain is malformed") from exc

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "NearBboCalibrator":
        if payload is None:
            raise ValueError("calibration model is required")
        return cls(payload)

    def predict(
        self,
        features: Mapping[str, Any],
        *,
        side: str,
        lane: str,
        regime: str,
    ) -> NearBboCalibrationPrediction:
        self.validate_input_domain(features)
        raw = _feature_vector(features, side=side, lane=lane, regime=regime, feature_names=self.feature_names)

        scaled = tuple(
            (value - mean) / scale
            for value, mean, scale in zip(raw, self.means, self.scales)
        )
        return NearBboCalibrationPrediction(
            fill_probability=_sigmoid_scalar(self.fill_intercept + _dot(scaled, self.fill_coefficients)),
            win_probability=_sigmoid_scalar(self.win_intercept + _dot(scaled, self.win_coefficients)),
            expected_net_bps=self.net_intercept + _dot(scaled, self.net_coefficients),
        )

    def validate_input_domain(self, features: Mapping[str, Any]) -> None:
        for name, (minimum, maximum) in self.input_domain.items():
            if name not in features:
                raise ValueError(f"calibration input missing domain feature: {name}")
            try:
                value = float(features[name])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"calibration input domain feature is invalid: {name}") from exc
            if not math.isfinite(value):
                raise ValueError(f"calibration input domain feature is invalid: {name}")
            tolerance = max(1e-9, abs(minimum) * 1e-9, abs(maximum) * 1e-9)
            if value < minimum - tolerance or value > maximum + tolerance:
                raise ValueError(f"calibration input outside training domain: {name}")


def fit_near_bbo_calibration(
    labels: Iterable[Mapping[str, Any]],
    config: NearBboCalibrationConfig | None = None,
) -> dict[str, Any]:
    cfg = config or NearBboCalibrationConfig()
    observed_rows = _dedupe_and_sort_labels(labels)
    rows = [row for row in observed_rows if _is_article_v2_label(row)]
    observed_filled = [row for row in observed_rows if bool(row.get("filled"))]
    filled = [row for row in rows if bool(row.get("filled"))]
    profitable = [row for row in filled if bool(row.get("profitable"))]
    losing = [row for row in filled if row.get("profitable") is False]
    reasons: list[str] = []
    if len(rows) < cfg.min_labels:
        reasons.append("labels_below_minimum")
    if len(rows) < 2:
        reasons.append("labels_below_walk_forward_minimum")
    if len(filled) < cfg.min_fills:
        reasons.append("fills_below_minimum")
    if len(profitable) < cfg.min_profitable_fills:
        reasons.append("profitable_fills_below_minimum")
    if len(losing) < cfg.min_losing_fills:
        reasons.append("losing_fills_below_minimum")
    counts = {
        "observed_labels": len(observed_rows),
        "observed_fills": len(observed_filled),
        "observed_profitable_fills": sum(row.get("profitable") is True for row in observed_filled),
        "excluded_incompatible_labels": len(observed_rows) - len(rows),
        "labels": len(rows),
        "fills": len(filled),
        "profitable_fills": len(profitable),
        "losing_fills": len(losing),
        "symbols": len({str(row.get("symbol") or "") for row in rows}),
    }
    if reasons:
        return {
            "schema": "bfa_near_bbo_calibration_report_v1",
            "status": "insufficient_data",
            "reasons": reasons,
            "counts": counts,
            "model": None,
        }

    split_index = max(1, min(len(rows) - 1, int(len(rows) * (1.0 - cfg.validation_fraction))))
    train_candidates = rows[:split_index]
    validation = rows[split_index:]
    validation_start_ms = int(validation[0]["signal_time_ms"])
    train = [
        row
        for row in train_candidates
        if int(row.get("resolved_time_ms") or row["signal_time_ms"]) < validation_start_ms
    ]
    purged_train_count = len(train_candidates) - len(train)
    train_filled = [row for row in train if bool(row.get("filled"))]
    train_profitable = sum(row.get("profitable") is True for row in train_filled)
    train_losing = sum(row.get("profitable") is False for row in train_filled)
    retained_fraction = 1.0 - cfg.validation_fraction
    required_train_fills = max(1, math.ceil(cfg.min_fills * retained_fraction))
    required_train_profitable = max(1, math.ceil(cfg.min_profitable_fills * retained_fraction))
    required_train_losing = max(1, math.ceil(cfg.min_losing_fills * retained_fraction))
    training_reasons: list[str] = []
    if len(train_filled) < required_train_fills:
        training_reasons.append("training_fills_below_minimum")
    if train_profitable < required_train_profitable:
        training_reasons.append("training_profitable_fills_below_minimum")
    if train_losing < required_train_losing:
        training_reasons.append("training_losing_fills_below_minimum")
    if train_profitable + train_losing != len(train_filled):
        training_reasons.append("training_fill_outcomes_missing")
    if (
        not train
        or not train_filled
        or train_profitable == 0
        or train_losing == 0
        or all(bool(row.get("filled")) for row in train)
        or not any(bool(row.get("filled")) for row in train)
    ):
        training_reasons.append("training_split_is_one_sided")
    split = {
        "train_count": len(train),
        "train_candidate_count": len(train_candidates),
        "purged_train_count": purged_train_count,
        "validation_count": len(validation),
        "train_end_ms": int(train[-1]["signal_time_ms"]) if train else None,
        "validation_start_ms": validation_start_ms,
    }
    if training_reasons:
        return {
            "schema": "bfa_near_bbo_calibration_report_v1",
            "status": "insufficient_data",
            "reasons": training_reasons,
            "counts": counts,
            "split": split,
            "model": None,
        }

    np = _require_numpy()
    x_train_raw = _matrix(train, MODEL_FEATURES, np=np)
    means = x_train_raw.mean(axis=0)
    scales = x_train_raw.std(axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    x_train = (x_train_raw - means) / scales
    y_fill = np.asarray([1.0 if row.get("filled") else 0.0 for row in train], dtype=float)
    fill_intercept, fill_coefficients = _fit_logistic(x_train, y_fill, cfg, np=np)

    x_train_filled = _matrix(train_filled, MODEL_FEATURES, np=np)
    x_train_filled = (x_train_filled - means) / scales
    y_win = np.asarray([1.0 if row.get("profitable") else 0.0 for row in train_filled], dtype=float)
    win_intercept, win_coefficients = _fit_logistic(x_train_filled, y_win, cfg, np=np)
    y_net_bps = np.asarray([_net_bps(row) for row in train_filled], dtype=float)
    net_intercept, net_coefficients = _fit_ridge(x_train_filled, y_net_bps, cfg.l2, np=np)

    model = {
        "schema": "bfa_near_bbo_calibration_v1",
        "feature_names": list(MODEL_FEATURES),
        "means": _float_list(means),
        "scales": _float_list(scales),
        "fill_model": {
            "intercept": float(fill_intercept),
            "coefficients": _float_list(fill_coefficients),
        },
        "win_model": {
            "intercept": float(win_intercept),
            "coefficients": _float_list(win_coefficients),
        },
        "net_model": {
            "intercept": float(net_intercept),
            "coefficients": _float_list(net_coefficients),
        },
        "input_domain": {
            name: {
                "minimum": float(x_train_raw[:, MODEL_FEATURE_INDEX[name]].min()),
                "maximum": float(x_train_raw[:, MODEL_FEATURE_INDEX[name]].max()),
            }
            for name in CONFIG_DOMAIN_FEATURES
        },
        "training_counts": counts,
    }
    calibrator = NearBboCalibrator(model)
    validation_predictions = [
        calibrator.predict(
            _mapping(row.get("features")),
            side=str(row.get("side") or ""),
            lane=str(row.get("lane") or ""),
            regime=str(row.get("regime") or ""),
        )
        for row in validation
    ]
    validation_filled = [
        (row, prediction)
        for row, prediction in zip(validation, validation_predictions)
        if bool(row.get("filled"))
    ]
    fill_actual = np.asarray([1.0 if row.get("filled") else 0.0 for row in validation], dtype=float)
    fill_predicted = np.asarray([item.fill_probability for item in validation_predictions], dtype=float)
    metrics: dict[str, Any] = {
        "validation_labels": len(validation),
        "validation_fills": len(validation_filled),
        "fill_rate_actual": float(fill_actual.mean()) if len(fill_actual) else None,
        "fill_probability_mean": float(fill_predicted.mean()) if len(fill_predicted) else None,
        "fill_brier": float(np.mean((fill_predicted - fill_actual) ** 2)) if len(fill_actual) else None,
    }
    if validation_filled:
        win_actual = np.asarray([1.0 if row.get("profitable") else 0.0 for row, _ in validation_filled], dtype=float)
        win_predicted = np.asarray([prediction.win_probability for _, prediction in validation_filled], dtype=float)
        net_actual = np.asarray([_net_bps(row) for row, _ in validation_filled], dtype=float)
        net_predicted = np.asarray([prediction.expected_net_bps for _, prediction in validation_filled], dtype=float)
        metrics.update(
            {
                "win_rate_actual": float(win_actual.mean()),
                "win_probability_mean": float(win_predicted.mean()),
                "win_brier": float(np.mean((win_predicted - win_actual) ** 2)),
                "net_bps_actual_mean": float(net_actual.mean()),
                "net_bps_predicted_mean": float(net_predicted.mean()),
                "net_bps_mae": float(np.mean(np.abs(net_predicted - net_actual))),
            }
        )
    return {
        "schema": "bfa_near_bbo_calibration_report_v1",
        "status": "trained",
        "reasons": [],
        "counts": counts,
        "split": split,
        "validation": metrics,
        "model": model,
    }


def load_near_bbo_labels(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Load native labels and reconstruct older shadow JSONL when possible."""

    loaded: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() == ".jsonl":
            loaded.extend(_load_jsonl_labels(path))
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping):
            loaded.extend(dict(item) for item in payload.get("labels", []) if isinstance(item, Mapping))
    return _dedupe_and_sort_labels(loaded)


def load_trained_near_bbo_calibrator(path: str | Path) -> NearBboCalibrator:
    """Load only a completed training report; insufficient reports fail closed."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("near-BBO calibration artifact must be a JSON object")
    if str(payload.get("schema") or "") != "bfa_near_bbo_calibration_report_v1":
        raise ValueError("unsupported near-BBO calibration report schema")
    if str(payload.get("status") or "") != "trained":
        raise ValueError("near-BBO calibration report is not trained")
    model = payload.get("model")
    if not isinstance(model, Mapping):
        raise ValueError("trained near-BBO calibration report has no model")
    return NearBboCalibrator(model)


def _load_jsonl_labels(path: Path) -> list[dict[str, Any]]:
    native: list[dict[str, Any]] = []
    admitted: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    latest_event_ms = 0
    default_notional = 120.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, Mapping):
            continue
        event_time = event.get("event_time_ms")
        if event_time is not None:
            latest_event_ms = max(latest_event_ms, int(event_time))
        summary = event.get("summary")
        if isinstance(summary, Mapping) and summary.get("notional_usdt") is not None:
            default_notional = float(summary["notional_usdt"])
        if event.get("type") == "label" and isinstance(event.get("label"), Mapping):
            native.append(dict(event["label"]))
            continue
        for proposal in event.get("admitted", []) if isinstance(event.get("admitted"), list) else []:
            if not isinstance(proposal, Mapping):
                continue
            signal_time = int(proposal.get("generated_at_ms") or 0)
            key = f"{str(proposal.get('symbol') or '').upper()}|{signal_time}"
            admitted[key] = dict(proposal)
        outcome_values = []
        if event.get("type") == "outcome" and isinstance(event.get("outcome"), Mapping):
            outcome_values.append(event["outcome"])
        if isinstance(event.get("closed"), list):
            outcome_values.extend(event["closed"])
        for outcome in outcome_values:
            if not isinstance(outcome, Mapping):
                continue
            signal_time = int(outcome.get("signal_time_ms") or 0)
            key = f"{str(outcome.get('symbol') or '').upper()}|{signal_time}"
            outcomes[key] = dict(outcome)
            latest_event_ms = max(latest_event_ms, int(outcome.get("exit_time_ms") or 0))
    reconstructed: list[dict[str, Any]] = []
    for key, proposal in admitted.items():
        signal_time = int(proposal.get("generated_at_ms") or 0)
        expires_at = int(proposal.get("expires_at_ms") or signal_time)
        outcome = outcomes.get(key)
        if outcome is None and expires_at > latest_event_ms:
            continue
        filled = outcome is not None
        notional = float(outcome.get("notional_usdt") if outcome else default_notional)
        net = float(outcome.get("net_pnl_usdt")) if outcome and outcome.get("net_pnl_usdt") is not None else None
        proposal_id = str(proposal.get("proposal_id") or key)
        reconstructed.append(
            {
                "proposal_id": proposal_id,
                "symbol": str(proposal.get("symbol") or "").upper(),
                "side": str(proposal.get("side") or ""),
                "lane": str(proposal.get("lane") or "legacy_direction"),
                "regime": str(proposal.get("regime") or "UNCLASSIFIED"),
                "signal_time_ms": signal_time,
                "resolved_time_ms": int(outcome.get("exit_time_ms") if outcome else expires_at),
                "expires_at_ms": expires_at,
                "notional_usdt": notional,
                "filled": filled,
                "fill_time_ms": int(outcome.get("fill_time_ms")) if outcome and outcome.get("fill_time_ms") is not None else None,
                "exit_time_ms": int(outcome.get("exit_time_ms")) if outcome and outcome.get("exit_time_ms") is not None else None,
                "exit_reason": str(outcome.get("exit_reason") if outcome else "quote_expired"),
                "profitable": net > 0 if net is not None else None,
                "net_pnl_usdt": net,
                "mfe_bps": float(outcome.get("mfe_bps")) if outcome and outcome.get("mfe_bps") is not None else None,
                "mae_bps": float(outcome.get("mae_bps")) if outcome and outcome.get("mae_bps") is not None else None,
                "predicted_fill_probability": float(proposal.get("fill_probability") or 0.0),
                "predicted_win_probability": float(proposal.get("win_probability") or 0.0),
                "predicted_conditional_net_ev_bps": float(proposal.get("conditional_net_ev_bps") or 0.0),
                "features": dict(proposal.get("features") or {}),
            }
        )
    # Native labels are appended last so they replace a reconstructed record
    # with the same proposal_id during the outer deduplication pass.
    return [*reconstructed, *native]


def _dedupe_and_sort_labels(labels: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for raw in labels:
        row = dict(raw)
        proposal_id = str(row.get("proposal_id") or "")
        if not proposal_id or row.get("signal_time_ms") is None:
            continue
        by_id[proposal_id] = row
    return sorted(by_id.values(), key=lambda row: (int(row["signal_time_ms"]), str(row["proposal_id"])))


def _is_article_v2_label(row: Mapping[str, Any]) -> bool:
    lane = str(row.get("lane") or "").lower()
    regime = str(row.get("regime") or "").upper()
    if (lane, regime) not in {("range_reversion", "RANGE"), ("trend_pullback", "TREND")}:
        return False
    if str(row.get("side") or "").lower() not in {"long", "short"}:
        return False
    if _float_or_zero(row.get("notional_usdt")) <= 0:
        return False
    if bool(row.get("filled")) and (
        not isinstance(row.get("profitable"), bool)
        or row.get("net_pnl_usdt") is None
    ):
        return False
    features = _mapping(row.get("features"))
    for name in NUMERIC_FEATURES:
        if name not in features:
            return False
        try:
            value = float(features[name])
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
    return True


def _matrix(rows: list[Mapping[str, Any]], feature_names: tuple[str, ...], *, np: Any) -> Any:
    return np.asarray(
        [
            _feature_vector(
                _mapping(row.get("features")),
                side=str(row.get("side") or ""),
                lane=str(row.get("lane") or ""),
                regime=str(row.get("regime") or ""),
                feature_names=feature_names,
            )
            for row in rows
        ],
        dtype=float,
    )


def _feature_vector(
    features: Mapping[str, Any],
    *,
    side: str,
    lane: str,
    regime: str,
    feature_names: tuple[str, ...],
) -> tuple[float, ...]:
    categorical = {
        "side_long": 1.0 if side.lower() == "long" else 0.0,
        "lane_range_reversion": 1.0 if lane.lower() == "range_reversion" else 0.0,
        "lane_trend_pullback": 1.0 if lane.lower() == "trend_pullback" else 0.0,
        "regime_range": 1.0 if regime.upper() == "RANGE" else 0.0,
        "regime_trend": 1.0 if regime.upper() == "TREND" else 0.0,
    }
    values = []
    for name in feature_names:
        if name in categorical:
            value = categorical[name]
        else:
            value = _float_or_zero(features.get(name))
        values.append(value if math.isfinite(value) else 0.0)
    return tuple(values)


def _fit_logistic(x: Any, y: Any, config: NearBboCalibrationConfig, *, np: Any) -> tuple[float, Any]:
    intercept = _logit(float(np.clip(y.mean(), 1e-4, 1.0 - 1e-4)))
    coefficients = np.zeros(x.shape[1], dtype=float)
    for _ in range(config.iterations):
        logits = np.clip(intercept + x @ coefficients, -30.0, 30.0)
        predicted = 1.0 / (1.0 + np.exp(-logits))
        error = predicted - y
        intercept -= config.learning_rate * float(error.mean())
        gradient = (x.T @ error) / len(y) + config.l2 * coefficients
        coefficients -= config.learning_rate * gradient
    return intercept, coefficients


def _fit_ridge(x: Any, y: Any, l2: float, *, np: Any) -> tuple[float, Any]:
    design = np.column_stack((np.ones(len(x)), x))
    penalty = np.eye(design.shape[1]) * l2
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return float(coefficients[0]), coefficients[1:]


def _net_bps(row: Mapping[str, Any]) -> float:
    notional = _float_or_zero(row.get("notional_usdt"))
    net = _float_or_zero(row.get("net_pnl_usdt"))
    return net / notional * 10_000.0 if notional > 0 else 0.0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float_list(values: Any) -> list[float]:
    return [float(value) for value in values.tolist()]


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(first * second for first, second in zip(left, right))


def _require_numpy() -> Any:
    try:
        import numpy as np
    except ModuleNotFoundError as exc:
        raise RuntimeError("near-BBO calibration training requires numpy") from exc
    return np


def _logit(value: float) -> float:
    return math.log(value / (1.0 - value))


def _sigmoid_scalar(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


__all__ = [
    "CONFIG_DOMAIN_FEATURES",
    "MODEL_FEATURES",
    "NUMERIC_FEATURES",
    "NearBboCalibrationConfig",
    "NearBboCalibrationPrediction",
    "NearBboCalibrator",
    "fit_near_bbo_calibration",
    "load_near_bbo_labels",
    "load_trained_near_bbo_calibrator",
]
