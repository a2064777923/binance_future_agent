import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_exchange_response, persist_order_intent
from bfa.ops.live_cycle_explainability import build_live_cycle_explainability_report


class LiveCycleExplainabilityTests(unittest.TestCase):
    def config(self, root: Path, **overrides):
        env = {
            "BFA_MODE": "live",
            "BFA_DB_PATH": str(root / "agent.sqlite"),
            "BFA_RUNTIME_DIR": str(root / "runtime"),
            "BFA_ACCOUNT_CAPITAL_USDT": "45",
            "BFA_MAX_LEVERAGE": "10",
            "BFA_MAX_POSITION_NOTIONAL_USDT": "300",
            "BFA_MAX_RISK_PER_TRADE_USDT": "0.7",
            "BFA_MAX_DAILY_LOSS_USDT": "2",
            "BFA_MAX_OPEN_POSITIONS": "30",
            "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
            "BFA_MAX_MARGIN_PER_POSITION_USDT": "30",
            "BFA_MAX_MARGIN_FRACTION": "0.75",
            "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "300",
            "BFA_MAX_PORTFOLIO_MARGIN_USDT": "90",
            "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "2.00",
            "BFA_MAX_PORTFOLIO_NOTIONAL_USDT": "2400",
            "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT": "1800",
            "BFA_MULTI_POSITION_ENABLED": "true",
            "BFA_POSITION_MODE": "hedge",
            "BFA_MANUAL_POSITION_SYMBOLS": "BTWUSDT",
            "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
            "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
        }
        env.update(overrides)
        return load_config(env)

    def test_report_explains_submitted_no_order_risk_blocked_missing_and_manual_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            _insert_submitted_sol_cycle(db_path)
            _insert_ai_pass_cycle(db_path)
            _insert_risk_blocked_cycle(db_path)
            _insert_missing_artifact_cycle(db_path)
            _insert_manual_lifecycle_cycle(db_path)

            report = build_live_cycle_explainability_report(
                self.config(root),
                db_path=str(db_path),
                latest_cycles=10,
            )

        payload = report.to_dict()
        self.assertEqual(payload["schema"], "bfa_live_cycle_explainability_v1")
        self.assertEqual(payload["status"], "explainability_ready")
        self.assertEqual(payload["manual_symbols"], ["BTWUSDT"])
        self.assertEqual(payload["summary"]["submitted_cycle_count"], 1)
        self.assertGreaterEqual(payload["summary"]["no_order_cycle_count"], 2)
        self.assertEqual(payload["summary"]["risk_blocked_cycle_count"], 2)
        self.assertEqual(payload["ledger"]["status"], "ledger_ready")
        self.assertEqual(payload["ledger"]["summary"]["outcome_count"], 1)
        self.assertFalse(payload["mutation_proof"]["places_orders"])
        self.assertFalse(payload["mutation_proof"]["cancels_orders"])
        self.assertFalse(payload["mutation_proof"]["writes_env_files"])
        self.assertFalse(payload["mutation_proof"]["changes_systemd_state"])
        self.assertFalse(payload["mutation_proof"]["raises_risk"])
        self.assertFalse(payload["mutation_proof"]["applies_guard_changes"])
        self.assertFalse(payload["mutation_proof"]["persists_closed_fills_and_outcomes"])

        cycles = {item["symbol"]: item for item in payload["cycles"] if item["symbol"]}
        sol = cycles["SOLUSDT"]
        self.assertTrue(sol["order"]["submitted"])
        self.assertEqual(sol["candidate"]["score"], 88.0)
        self.assertEqual(sol["trade_setup"]["decision"], "trade")
        self.assertEqual(sol["trade_setup"]["factor_summary"]["schema"], "bfa_factor_summary_v1")
        self.assertEqual(sol["ai_decision"]["decision"], "trade")
        self.assertTrue(sol["risk"]["accepted"])
        self.assertTrue(sol["exchange_responses"][0]["has_stop_loss_order"])
        self.assertIn("stop_risk_cap", sol["sizing_explanation"]["limiting_factors"])
        self.assertIn("margin_fraction_cap", sol["sizing_explanation"]["limiting_factors"])
        self.assertIn("effective_notional_cap", sol["sizing_explanation"]["limiting_factors"])
        self.assertIn("below_min_executable_notional", sol["sizing_explanation"]["limiting_factors"])

        ada = cycles["ADAUSDT"]
        self.assertIsNone(ada["order"]["intent"])
        self.assertEqual(ada["ai_decision"]["decision"], "pass")
        self.assertIn("no_order_intent", ada["evidence_quality"]["notes"])

        wld = cycles["WLDUSDT"]
        self.assertFalse(wld["risk"]["accepted"])
        self.assertIn("risk_exceeds_cap", wld["sizing_explanation"]["limiting_factors"])
        self.assertIn("portfolio_notional_cap_reached", wld["sizing_explanation"]["limiting_factors"])

        bnb = cycles["BNBUSDT"]
        self.assertIn("missing_candidate", bnb["evidence_quality"]["notes"])
        self.assertIn("missing_trade_setup", bnb["evidence_quality"]["notes"])

        lifecycle_cycles = [
            item for item in payload["cycles"] if item["position_lifecycle"] is not None
        ]
        manual_lifecycle = lifecycle_cycles[0]["position_lifecycle"]
        self.assertEqual(manual_lifecycle["manual_diagnostics"][0]["symbol"], "BTWUSDT")
        self.assertFalse(manual_lifecycle["manual_diagnostics"][0]["bot_managed"])
        self.assertIn("manual_position_ignored", manual_lifecycle["manual_diagnostics"][0]["reasons"])

    def test_reconcile_guard_is_visible_in_explainability_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()

            report = build_live_cycle_explainability_report(
                self.config(root),
                db_path=str(root / "agent.sqlite"),
                reconcile=True,
                persist_closed=True,
            )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "explainability_blocked")
        self.assertIn("signed_client_required_for_reconcile", payload["reasons"])
        self.assertTrue(payload["mutation_proof"]["persists_closed_fills_and_outcomes"])
        self.assertFalse(payload["mutation_proof"]["places_orders"])
        self.assertFalse(payload["mutation_proof"]["exchange_mutation"])


def _insert_submitted_sol_cycle(db_path: Path) -> int:
    decided_at = "2026-06-21T06:30:00Z"
    intent = OrderIntent(
        symbol="SOLUSDT",
        side="BUY",
        quantity=1.0,
        notional_usdt=140.0,
        entry_price=140.0,
        stop_price=138.0,
        target_price=144.0,
        leverage=10,
        mode="live",
        decided_at=decided_at,
        metadata={"ai_side": "long", "hold_time_minutes": 60},
    )
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        store.insert_artifact(
            "candidates",
            occurred_at=decided_at,
            source="strategy.hot",
            symbol="SOLUSDT",
            ref_id=f"candidate:SOLUSDT:{decided_at}",
            payload={
                "score": 88.0,
                "reason_codes": ["hot_symbol", "volume_expansion"],
                "features": {
                    "reference_price": 140.0,
                    "min_executable_notional": 500.0,
                    "quote_volume": 300000000,
                },
            },
            event_type="candidate",
        )
        store.insert_artifact(
            "trade_setups",
            occurred_at=decided_at,
            source="strategy.quant_setup",
            symbol="SOLUSDT",
            ref_id=f"trade_setup:SOLUSDT:{decided_at}",
            payload={
                "setup": {
                    "decision": "trade",
                    "side": "long",
                    "entry_price": 140.0,
                    "stop_price": 138.0,
                    "target_price": 144.0,
                    "notional_usdt": 140.0,
                    "edge_score": 76,
                    "factor_summary": {
                        "schema": "bfa_factor_summary_v1",
                        "selected_side": "long",
                        "edge_score": 76,
                    },
                    "factor_scores": [
                        {
                            "name": "taker_flow",
                            "weighted_score": 15,
                            "reasons": ["taker_buy_bias"],
                        }
                    ],
                    "reasons": ["quant_long_setup"],
                    "warnings": ["below_min_executable_notional"],
                }
            },
            event_type="trade_setup",
        )
        store.insert_artifact(
            "ai_decisions",
            occurred_at=decided_at,
            source="deepseek.chat_completions",
            symbol="SOLUSDT",
            ref_id=f"ai_decision:SOLUSDT:{decided_at}",
            payload={
                "validation": {
                    "accepted": True,
                    "decision": {
                        "decision": "trade",
                        "side": "long",
                        "confidence": 0.72,
                        "entry_price": 140.0,
                        "stop_price": 138.0,
                        "target_price": 144.0,
                        "notional_usdt": 140.0,
                        "reasons": ["ai_confirms_momentum"],
                    },
                    "validation_errors": [],
                }
            },
            event_type="ai_decision",
        )
        event_id = persist_order_intent(
            store,
            intent=intent,
            status="submitted",
            risk=RiskDecision(True, ["risk_accepted"]),
        )
        persist_exchange_response(
            store,
            intent=intent,
            response={
                "entry_order": {"orderId": 9001},
                "stop_loss_order": {"algoId": 9101},
                "take_profit_order": {"algoId": 9102},
            },
        )
        store.insert_artifact(
            "outcomes",
            occurred_at="2026-06-21T07:10:00Z",
            source="binance_usdm",
            symbol="SOLUSDT",
            ref_id=f"outcome:{event_id}:closed",
            payload={
                "intent": {
                    "event_id": event_id,
                    "symbol": "SOLUSDT",
                    "side": "BUY",
                    "occurred_at": decided_at,
                },
                "status": "closed",
                "trade_count": 2,
                "gross_realized_pnl_usdt": 0.22,
                "commission_usdt": 0.02,
                "net_realized_pnl_usdt": 0.2,
                "first_trade_time": decided_at,
                "last_trade_time": "2026-06-21T07:10:00Z",
                "exit_reason": "take_profit",
            },
            event_type="outcome",
        )
        return event_id
    finally:
        connection.close()


def _insert_ai_pass_cycle(db_path: Path) -> None:
    decided_at = "2026-06-21T06:35:00Z"
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        store.insert_artifact(
            "candidates",
            occurred_at=decided_at,
            source="strategy.hot",
            symbol="ADAUSDT",
            ref_id=f"candidate:ADAUSDT:{decided_at}",
            payload={"score": 70.0, "reason_codes": ["hot_symbol"], "features": {"reference_price": 0.7}},
            event_type="candidate",
        )
        store.insert_artifact(
            "trade_setups",
            occurred_at=decided_at,
            source="strategy.quant_setup",
            symbol="ADAUSDT",
            ref_id=f"trade_setup:ADAUSDT:{decided_at}",
            payload={
                "setup": {
                    "decision": "trade",
                    "side": "long",
                    "entry_price": 0.7,
                    "stop_price": 0.68,
                    "target_price": 0.74,
                    "factor_scores": [{"name": "momentum", "weighted_score": 8, "reasons": ["24h_momentum"]}],
                    "reasons": ["quant_long_setup"],
                    "warnings": [],
                }
            },
            event_type="trade_setup",
        )
        store.insert_artifact(
            "ai_decisions",
            occurred_at=decided_at,
            source="deepseek.chat_completions",
            symbol="ADAUSDT",
            ref_id=f"ai_decision:ADAUSDT:{decided_at}",
            payload={
                "validation": {
                    "accepted": True,
                    "decision": {"decision": "pass", "side": "long", "confidence": 0.6},
                    "validation_errors": [],
                }
            },
            event_type="ai_decision",
        )
    finally:
        connection.close()


def _insert_risk_blocked_cycle(db_path: Path) -> None:
    decided_at = "2026-06-21T06:40:00Z"
    intent = OrderIntent(
        symbol="WLDUSDT",
        side="BUY",
        quantity=10.0,
        notional_usdt=400.0,
        entry_price=40.0,
        stop_price=37.0,
        target_price=45.0,
        leverage=10,
        mode="live",
        decided_at=decided_at,
    )
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        store.insert_artifact(
            "candidates",
            occurred_at=decided_at,
            source="strategy.hot",
            symbol="WLDUSDT",
            ref_id=f"candidate:WLDUSDT:{decided_at}",
            payload={"score": 74.0, "reason_codes": ["hot_symbol"], "features": {"reference_price": 40.0}},
            event_type="candidate",
        )
        store.insert_artifact(
            "trade_setups",
            occurred_at=decided_at,
            source="strategy.quant_setup",
            symbol="WLDUSDT",
            ref_id=f"trade_setup:WLDUSDT:{decided_at}",
            payload={
                "setup": {
                    "decision": "trade",
                    "side": "long",
                    "entry_price": 40.0,
                    "stop_price": 37.0,
                    "target_price": 45.0,
                    "factor_scores": [{"name": "momentum", "weighted_score": 9, "reasons": ["24h_momentum"]}],
                    "reasons": ["quant_long_setup"],
                    "warnings": [],
                }
            },
            event_type="trade_setup",
        )
        store.insert_artifact(
            "ai_decisions",
            occurred_at=decided_at,
            source="deepseek.chat_completions",
            symbol="WLDUSDT",
            ref_id=f"ai_decision:WLDUSDT:{decided_at}",
            payload={
                "validation": {
                    "accepted": True,
                    "decision": {
                        "decision": "trade",
                        "side": "long",
                        "entry_price": 40.0,
                        "stop_price": 37.0,
                        "target_price": 45.0,
                        "notional_usdt": 400.0,
                    },
                    "validation_errors": [],
                }
            },
            event_type="ai_decision",
        )
        persist_order_intent(
            store,
            intent=intent,
            status="rejected",
            risk=RiskDecision(False, ["risk_exceeds_cap", "portfolio_notional_cap_reached"]),
        )
    finally:
        connection.close()


def _insert_missing_artifact_cycle(db_path: Path) -> None:
    decided_at = "2026-06-21T06:45:00Z"
    intent = OrderIntent(
        symbol="BNBUSDT",
        side="SELL",
        quantity=0.02,
        notional_usdt=12.0,
        entry_price=600.0,
        stop_price=612.0,
        target_price=570.0,
        leverage=10,
        mode="live",
        decided_at=decided_at,
    )
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        persist_order_intent(
            store,
            intent=intent,
            status="rejected",
            risk=RiskDecision(False, ["portfolio_margin_cap_reached"]),
        )
    finally:
        connection.close()


def _insert_manual_lifecycle_cycle(db_path: Path) -> None:
    decided_at = "2026-06-21T06:50:00Z"
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        store.insert_artifact(
            "risk_state",
            occurred_at=decided_at,
            source="agent.live_cycle",
            symbol=None,
            ref_id=f"position_lifecycle:{decided_at}",
            payload={
                "schema": "bfa_position_lifecycle_decision_v1",
                "mode": "live",
                "decided_at": decided_at,
                "status": "review_ok",
                "reasons": ["position_review_ok"],
                "manual_position_symbols": ["BTWUSDT"],
                "auto_management": {"enabled": False, "status": "disabled"},
                "diagnostics": [
                    {
                        "symbol": "BTWUSDT",
                        "lifecycle_decision": "manual_hold",
                        "manual_symbol": True,
                        "failed_preconditions": ["manual_position_ignored"],
                        "order_plan": None,
                    }
                ],
            },
            event_type="position_lifecycle_decision",
        )
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
