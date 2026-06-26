import json
import unittest


class ActualSetupLdcCalibrationTests(unittest.TestCase):
    def test_sample_from_trade_setup_row_reads_nested_payload(self):
        from scripts.server_actual_setup_ldc_calibration import sample_from_trade_setup_row

        payload = {
            "candidate": {
                "symbol": "BTCUSDT",
                "features": {
                    "strategy_leg": "trend",
                    "regime_label": "TREND",
                    "route_decision": "ALLOW",
                    "ema_spread_percent": 0.2,
                    "rsi": 55,
                    "atr_percent": 1.1,
                    "taker_buy_sell_ratio": 1.08,
                    "kline_momentum_percent": 0.4,
                },
            },
            "setup": {
                "symbol": "BTCUSDT",
                "decision": "trade",
                "side": "long",
                "entry_price": 100.0,
                "stop_price": 98.0,
                "target_price": 104.0,
                "confidence": 0.61,
                "edge_score": 22.0,
                "risk_reward_ratio": 2.0,
                "price_basis": {
                    "entry_basis": {"limit_entry_max_wait_seconds": 30},
                    "regime_router": {"regime_label": "TREND", "route_decision": "ALLOW"},
                },
            },
        }
        sample = sample_from_trade_setup_row(
            {
                "id": 7,
                "event_id": 11,
                "occurred_at": "2026-06-26T00:00:00Z",
                "symbol": "BTCUSDT",
                "payload": json.dumps(payload),
            }
        )

        self.assertIsNotNone(sample)
        self.assertEqual(sample.symbol, "BTCUSDT")
        self.assertEqual(sample.side, "long")
        self.assertEqual(sample.strategy_leg, "trend")
        self.assertEqual(sample.regime_label, "TREND")
        self.assertEqual(sample.wait_seconds, 30)

    def test_label_path_marks_stop_first_but_later_target(self):
        from scripts.server_actual_setup_ldc_calibration import (
            SetupSample,
            Tick,
            label_setup_path,
            parse_iso,
        )

        sample = SetupSample(
            row_id=1,
            event_id=2,
            occurred_at=parse_iso("2026-06-26T00:00:00Z"),
            symbol="BTCUSDT",
            side="long",
            strategy_leg="trend",
            regime_label="TREND",
            route_decision="ALLOW",
            decision="trade",
            entry_price=100.0,
            stop_price=99.0,
            target_price=103.0,
            wait_seconds=10,
            confidence=0.6,
            edge_score=20.0,
            risk_reward_ratio=3.0,
            features={
                "ema_spread_percent": 0.2,
                "rsi": 52,
                "atr_percent": 1.0,
                "taker_buy_sell_ratio": 1.1,
                "kline_momentum_percent": 0.5,
            },
            setup={},
            candidate={},
        )
        ticks = [
            Tick(event_ms=1_782_432_000_000, price=100.2, quantity=1.0),
            Tick(event_ms=1_782_432_001_000, price=99.9, quantity=1.0),
            Tick(event_ms=1_782_432_002_000, price=98.8, quantity=1.0),
            Tick(event_ms=1_782_432_020_000, price=103.2, quantity=1.0),
        ]
        row = label_setup_path(
            sample,
            ticks,
            horizon_seconds=30,
            dead_zone_percent=0.1,
            min_coverage_fraction=0.0,
        )

        self.assertEqual(row["status"], "stop_first")
        self.assertFalse(row["setup_won"])
        self.assertTrue(row["stop_first_but_later_target"])
        self.assertTrue(row["direction_correct_after_stop"])

    def test_label_path_marks_no_fill_when_limit_not_touched(self):
        from scripts.server_actual_setup_ldc_calibration import (
            SetupSample,
            Tick,
            label_setup_path,
            parse_iso,
        )

        sample = SetupSample(
            row_id=1,
            event_id=2,
            occurred_at=parse_iso("2026-06-26T00:00:00Z"),
            symbol="BTCUSDT",
            side="short",
            strategy_leg="trend",
            regime_label="TREND",
            route_decision="ALLOW",
            decision="trade",
            entry_price=105.0,
            stop_price=106.0,
            target_price=101.0,
            wait_seconds=5,
            confidence=None,
            edge_score=None,
            risk_reward_ratio=None,
            features={
                "ema_spread_percent": -0.2,
                "rsi": 48,
                "atr_percent": 1.0,
                "taker_buy_sell_ratio": 0.9,
                "kline_momentum_percent": -0.5,
            },
            setup={},
            candidate={},
        )
        ticks = [
            Tick(event_ms=1_782_432_000_000, price=100.0, quantity=1.0),
            Tick(event_ms=1_782_432_004_000, price=101.0, quantity=1.0),
            Tick(event_ms=1_782_432_010_000, price=106.0, quantity=1.0),
        ]
        row = label_setup_path(
            sample,
            ticks,
            horizon_seconds=20,
            dead_zone_percent=0.1,
            min_coverage_fraction=0.0,
        )

        self.assertEqual(row["status"], "no_fill")
        self.assertEqual(row["label"], 0)

    def test_calibrate_ldc_returns_ok_with_real_setup_side_labels(self):
        from scripts.server_actual_setup_ldc_calibration import calibrate_ldc, FEATURE_NAMES

        rows = []
        for i in range(20):
            side = "long" if i % 2 == 0 else "short"
            sign = 1 if side == "long" else -1
            rows.append({
                "occurred_at": f"2026-06-26T00:{i:02d}:00Z",
                "symbol": "BTCUSDT",
                "side": side,
                "status": "target_first",
                "label": sign,
                "low_coverage": False,
                "ldc_missing_features": "",
                "ema_spread": sign * (0.2 + i * 0.001),
                "rsi": 55 if sign > 0 else 45,
                "atr_percent": 1.0,
                "taker_ratio": 1.1 if sign > 0 else 0.9,
                "mom_6": sign * 0.4,
            })

        report = calibrate_ldc(rows, feature_names=FEATURE_NAMES, k=3, val_fraction=0.3)

        self.assertEqual(report["status"], "ok")
        self.assertGreater(report["usable_samples"], 10)
        self.assertIn("recommended_blend", report)


if __name__ == "__main__":
    unittest.main()
