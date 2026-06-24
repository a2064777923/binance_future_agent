import json
import tempfile
import unittest
from pathlib import Path

from bfa.ai.decision import validate_decision_payload
from bfa.ai.schema import RiskLimits, context_from_candidate
from bfa.config import RuntimeMode, load_config
from bfa.execution.filters import SymbolExecutionFilters
from bfa.execution.models import RiskState
from bfa.execution.risk import evaluate_risk, intent_from_ai_decision


EXCHANGE_INFO = Path(__file__).parent / "fixtures" / "binance_market" / "exchange_info.json"


class ExecutionRiskTests(unittest.TestCase):
    def limits(self):
        return RiskLimits(
            account_capital_usdt=100,
            max_leverage=3,
            max_position_notional_usdt=20,
            max_risk_per_trade_usdt=1,
            max_daily_loss_usdt=3,
            max_open_positions=2,
        )

    def validation(self, **overrides):
        payload = {
            "decision": "trade",
            "side": "long",
            "confidence": 0.75,
            "entry_price": 100.0,
            "stop_price": 96.0,
            "target_price": 108.0,
            "notional_usdt": 20.0,
            "hold_time_minutes": 30,
            "reasons": ["narrative and market confirmation"],
        }
        payload.update(overrides)
        context = context_from_candidate(
            {"symbol": "BTCUSDT", "score": 42},
            risk_limits=self.limits(),
            decided_at="2026-06-20T10:00:00Z",
        )
        return validate_decision_payload(payload, context)

    def config(self, **overrides):
        env = {
            "BFA_MODE": "dry_run",
            "BFA_ACCOUNT_CAPITAL_USDT": "100",
            "BFA_MAX_LEVERAGE": "3",
            "BFA_MAX_POSITION_NOTIONAL_USDT": "20",
            "BFA_MAX_RISK_PER_TRADE_USDT": "1",
            "BFA_MAX_DAILY_LOSS_USDT": "3",
            "BFA_MAX_OPEN_POSITIONS": "2",
            "BFA_KILL_SWITCH_FILE": "",
        }
        env.update(overrides)
        return load_config(env)

    def test_valid_dry_run_intent_passes_risk(self):
        validation = self.validation()
        filters = SymbolExecutionFilters.from_exchange_info(
            json.loads(EXCHANGE_INFO.read_text(encoding="utf-8")),
            "BTCUSDT",
        )

        intent, intent_risk = intent_from_ai_decision(
            symbol="BTCUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
            filters=filters,
        )
        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(),
            now="2026-06-20T10:00:00Z",
        )

        self.assertTrue(intent_risk.accepted)
        self.assertTrue(risk.accepted)
        self.assertEqual(intent.side, "BUY")
        self.assertAlmostEqual(intent.quantity, 0.2)
        self.assertAlmostEqual(intent.estimated_initial_margin_usdt, 20 / 3)

    def test_ai_pass_creates_no_intent(self):
        validation = self.validation(
            decision="pass",
            side="flat",
            entry_price=None,
            stop_price=None,
            target_price=None,
            notional_usdt=None,
            hold_time_minutes=None,
        )

        intent, risk = intent_from_ai_decision(
            symbol="BTCUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        self.assertIsNone(intent)
        self.assertFalse(risk.accepted)
        self.assertIn("ai_decision_pass", risk.reason_codes)

    def test_daily_loss_position_and_cooldown_reject(self):
        validation = self.validation()
        intent, _risk = intent_from_ai_decision(
            symbol="BTCUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(
                active_positions=2,
                daily_realized_pnl_usdt=-3.1,
                cooldown_until="2026-06-20T10:05:00Z",
            ),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("daily_loss_cap_reached", risk.reason_codes)
        self.assertIn("max_open_positions_reached", risk.reason_codes)
        self.assertIn("cooldown_active", risk.reason_codes)

    def test_single_position_default_rejects_when_any_position_is_active(self):
        validation = self.validation()
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(active_positions=1, active_exposures=[{"symbol": "BTCUSDT", "direction": "LONG"}]),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("multi_position_disabled", risk.reason_codes)

    def test_multi_position_enabled_allows_different_symbol_until_cap(self):
        validation = self.validation()
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(active_positions=1, active_exposures=[{"symbol": "BTCUSDT", "direction": "LONG"}]),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(BFA_MULTI_POSITION_ENABLED="true"),
            now="2026-06-20T10:00:00Z",
        )

        self.assertTrue(risk.accepted)
        self.assertEqual(risk.reason_codes, ["risk_accepted"])

    def test_micro_grid_intent_can_use_extra_open_position_slots(self):
        validation = self.validation(
            reasons=[
                "strategy_leg:micro_grid",
                "regime_label:RANGE",
                "entry_order_type:limit",
            ]
        )
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(
                active_positions=2,
                active_exposures=[
                    {"symbol": "BTCUSDT", "direction": "LONG"},
                    {"symbol": "SOLUSDT", "direction": "SHORT"},
                ],
            ),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(
                BFA_MULTI_POSITION_ENABLED="true",
                BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS="2",
            ),
            now="2026-06-20T10:00:00Z",
        )

        self.assertTrue(risk.accepted)
        self.assertEqual(risk.reason_codes, ["risk_accepted"])

    def test_trend_intent_cannot_use_micro_grid_extra_open_position_slots(self):
        validation = self.validation(reasons=["strategy_leg:trend", "regime_label:TREND"])
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(
                active_positions=2,
                active_exposures=[
                    {"symbol": "BTCUSDT", "direction": "LONG"},
                    {"symbol": "SOLUSDT", "direction": "SHORT"},
                ],
            ),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(
                BFA_MULTI_POSITION_ENABLED="true",
                BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS="2",
            ),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("max_open_positions_reached", risk.reason_codes)

    def test_micro_grid_extra_open_position_slots_still_have_a_cap(self):
        validation = self.validation(
            reasons=[
                "strategy_leg:micro_grid",
                "regime_label:RANGE",
                "entry_order_type:limit",
            ]
        )
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(
                active_positions=4,
                active_exposures=[
                    {"symbol": "BTCUSDT", "direction": "LONG"},
                    {"symbol": "SOLUSDT", "direction": "SHORT"},
                    {"symbol": "BNBUSDT", "direction": "LONG"},
                    {"symbol": "DOGEUSDT", "direction": "SHORT"},
                ],
            ),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(
                BFA_MULTI_POSITION_ENABLED="true",
                BFA_MICRO_GRID_EXTRA_OPEN_POSITIONS="2",
            ),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("max_open_positions_reached", risk.reason_codes)

    def test_micro_grid_can_use_extra_same_direction_notional_cap(self):
        validation = self.validation(
            notional_usdt=20.0,
            reasons=[
                "strategy_leg:micro_grid",
                "regime_label:RANGE",
                "entry_order_type:limit",
            ],
        )
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(
                active_positions=1,
                active_exposures=[{"symbol": "BTCUSDT", "direction": "LONG", "notional_usdt": 35.0}],
            ),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(
                BFA_MULTI_POSITION_ENABLED="true",
                BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT="40",
                BFA_MICRO_GRID_EXTRA_SAME_DIRECTION_NOTIONAL_USDT="20",
            ),
            now="2026-06-20T10:00:00Z",
        )

        self.assertTrue(risk.accepted)
        self.assertEqual(risk.reason_codes, ["risk_accepted"])

    def test_trend_cannot_use_micro_grid_extra_same_direction_notional_cap(self):
        validation = self.validation(notional_usdt=20.0, reasons=["strategy_leg:trend", "regime_label:TREND"])
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(
                active_positions=1,
                active_exposures=[{"symbol": "BTCUSDT", "direction": "LONG", "notional_usdt": 35.0}],
            ),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(
                BFA_MULTI_POSITION_ENABLED="true",
                BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT="40",
                BFA_MICRO_GRID_EXTRA_SAME_DIRECTION_NOTIONAL_USDT="20",
            ),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("same_direction_notional_cap_reached", risk.reason_codes)

    def test_multi_position_enabled_rejects_duplicate_symbol_direction(self):
        validation = self.validation()
        intent, _risk = intent_from_ai_decision(
            symbol="BTCUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(active_positions=1, active_exposures=[{"symbol": "BTCUSDT", "direction": "LONG"}]),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(BFA_MULTI_POSITION_ENABLED="true"),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("duplicate_symbol_direction_exposure", risk.reason_codes)

    def test_multi_position_blocks_same_symbol_opposite_direction_by_default(self):
        validation = self.validation(side="short", stop_price=104.0, target_price=92.0)
        intent, _risk = intent_from_ai_decision(
            symbol="BTCUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(active_positions=1, active_exposures=[{"symbol": "BTCUSDT", "direction": "LONG"}]),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(BFA_MULTI_POSITION_ENABLED="true"),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("same_symbol_opposite_exposure_blocked", risk.reason_codes)

    def test_multi_position_can_allow_same_symbol_opposite_direction_explicitly(self):
        validation = self.validation(side="short", stop_price=104.0, target_price=92.0)
        intent, _risk = intent_from_ai_decision(
            symbol="BTCUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(active_positions=1, active_exposures=[{"symbol": "BTCUSDT", "direction": "LONG"}]),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(
                BFA_MULTI_POSITION_ENABLED="true",
                BFA_ALLOW_SAME_SYMBOL_OPPOSITE_POSITIONS="true",
            ),
            now="2026-06-20T10:00:00Z",
        )

        self.assertTrue(risk.accepted)

    def test_multi_position_rejects_portfolio_margin_cap(self):
        validation = self.validation()
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(
                active_positions=1,
                active_exposures=[
                    {
                        "symbol": "BTCUSDT",
                        "direction": "LONG",
                        "notional_usdt": 20,
                        "initial_margin_usdt": 5,
                    }
                ],
            ),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(
                BFA_MULTI_POSITION_ENABLED="true",
                BFA_MAX_PORTFOLIO_MARGIN_USDT="8",
                BFA_MAX_PORTFOLIO_MARGIN_FRACTION="1",
            ),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("portfolio_margin_cap_reached", risk.reason_codes)

    def test_multi_position_rejects_same_direction_notional_cap(self):
        validation = self.validation()
        intent, _risk = intent_from_ai_decision(
            symbol="ETHUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.DRY_RUN,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(
                active_positions=1,
                active_exposures=[
                    {
                        "symbol": "BTCUSDT",
                        "direction": "LONG",
                        "notional_usdt": 25,
                        "leverage": 5,
                    }
                ],
            ),
            mode=RuntimeMode.DRY_RUN,
            config=self.config(
                BFA_MULTI_POSITION_ENABLED="true",
                BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT="40",
            ),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("same_direction_notional_cap_reached", risk.reason_codes)

    def test_live_kill_switch_rejects(self):
        validation = self.validation()
        intent, _risk = intent_from_ai_decision(
            symbol="BTCUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.LIVE,
            decided_at="2026-06-20T10:00:00Z",
        )

        with tempfile.TemporaryDirectory() as tmp:
            kill_switch = Path(tmp) / "KILL_SWITCH"
            kill_switch.write_text("stop", encoding="utf-8")
            risk = evaluate_risk(
                intent=intent,
                validation=validation,
                risk_limits=self.limits(),
                risk_state=RiskState(),
                mode=RuntimeMode.LIVE,
                config=self.config(
                    BFA_MODE="live",
                    BFA_KILL_SWITCH_FILE=str(kill_switch),
                    BINANCE_API_KEY="synthetic-binance-key-abcdef",
                    BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
                ),
                now="2026-06-20T10:00:00Z",
            )

        self.assertFalse(risk.accepted)
        self.assertIn("kill_switch_active", risk.reason_codes)

    def test_live_missing_credentials_rejects(self):
        validation = self.validation()
        intent, _risk = intent_from_ai_decision(
            symbol="BTCUSDT",
            validation=validation,
            risk_limits=self.limits(),
            mode=RuntimeMode.LIVE,
            decided_at="2026-06-20T10:00:00Z",
        )

        risk = evaluate_risk(
            intent=intent,
            validation=validation,
            risk_limits=self.limits(),
            risk_state=RiskState(),
            mode=RuntimeMode.LIVE,
            config=self.config(BFA_MODE="live"),
            now="2026-06-20T10:00:00Z",
        )

        self.assertFalse(risk.accepted)
        self.assertIn("missing_binance_credentials", risk.reason_codes)


if __name__ == "__main__":
    unittest.main()
