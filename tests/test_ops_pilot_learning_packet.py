import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_exchange_response, persist_order_intent
from bfa.ops.pilot_learning_packet import build_pilot_learning_packet_report


class FakeSignedClient:
    def account(self):
        return {"availableBalance": "64.2", "totalWalletBalance": "44.6"}

    def position_risk(self):
        return [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.001",
                "positionSide": "LONG",
                "entryPrice": "65000",
                "markPrice": "65100",
                "notional": "65.1",
                "initialMargin": "6.51",
                "leverage": "10",
                "unRealizedProfit": "0.1",
            },
            {
                "symbol": "BTWUSDT",
                "positionAmt": "-556",
                "positionSide": "SHORT",
                "entryPrice": "0.18819",
                "markPrice": "0.137",
                "notional": "-76.172",
                "initialMargin": "7.6172",
                "leverage": "10",
                "unRealizedProfit": "28.46",
            },
        ]

    def open_orders(self):
        return []

    def open_algo_orders(self):
        return [
            {"symbol": "BTCUSDT", "positionSide": "LONG"},
            {"symbol": "BTCUSDT", "positionSide": "LONG"},
            {"symbol": "BTWUSDT", "positionSide": "SHORT"},
        ]


class PilotLearningPacketTests(unittest.TestCase):
    def config(self, root: Path, **overrides):
        env = {
            "BFA_MODE": "live",
            "BFA_DB_PATH": str(root / "agent.sqlite"),
            "BFA_RUNTIME_DIR": str(root / "runtime"),
            "BFA_ACCOUNT_CAPITAL_USDT": "45",
            "BFA_MAX_LEVERAGE": "10",
            "BFA_MAX_POSITION_NOTIONAL_USDT": "120",
            "BFA_MAX_RISK_PER_TRADE_USDT": "0.7",
            "BFA_MAX_DAILY_LOSS_USDT": "2",
            "BFA_MAX_OPEN_POSITIONS": "12",
            "BFA_DYNAMIC_POSITION_SIZING_ENABLED": "true",
            "BFA_MAX_MARGIN_PER_POSITION_USDT": "12",
            "BFA_MAX_MARGIN_FRACTION": "0.33",
            "BFA_MAX_EFFECTIVE_NOTIONAL_USDT": "120",
            "BFA_MAX_PORTFOLIO_MARGIN_USDT": "45",
            "BFA_MAX_PORTFOLIO_MARGIN_FRACTION": "0.95",
            "BFA_MAX_PORTFOLIO_NOTIONAL_USDT": "900",
            "BFA_MAX_SAME_DIRECTION_NOTIONAL_USDT": "720",
            "BFA_MULTI_POSITION_ENABLED": "true",
            "BFA_POSITION_MODE": "hedge",
            "BFA_MANUAL_POSITION_SYMBOLS": "BTWUSDT",
            "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
            "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
        }
        env.update(overrides)
        return load_config(env)

    def test_packet_composes_manual_lifecycle_caps_exit_outcomes_and_traces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            active_intent_id = _insert_btc_live_flow(db_path)
            outcome_intent_id = _insert_closed_sol_outcome(db_path)

            report = build_pilot_learning_packet_report(
                self.config(root),
                db_path=str(db_path),
                signed_client=FakeSignedClient(),
                now="2026-06-21T07:10:00Z",
                latest_traces=5,
            )

        payload = report.to_dict()
        self.assertEqual(payload["schema"], "bfa_pilot_learning_packet_v1")
        self.assertIn(payload["status"], {"packet_ready", "review_required"})
        self.assertEqual(payload["manual_symbols"], ["BTWUSDT"])
        self.assertFalse(payload["mutation_proof"]["places_orders"])
        self.assertFalse(payload["mutation_proof"]["cancels_orders"])
        self.assertFalse(payload["mutation_proof"]["writes_env_files"])
        self.assertFalse(payload["mutation_proof"]["persists_closed_fills_and_outcomes"])

        self.assertEqual(payload["cap_usage"]["current_profile"]["max_open_positions"], 12)
        self.assertEqual(payload["cap_usage"]["entry_capacity"]["manual_exposures"][0]["symbol"], "BTWUSDT")
        self.assertEqual(payload["cap_usage"]["entry_capacity"]["active_exposures"][0]["symbol"], "BTCUSDT")
        self.assertEqual(payload["cap_usage"]["utilization"]["manual_position_count"], 1)
        self.assertEqual(payload["cap_usage"]["utilization"]["bot_position_count"], 1)

        decisions = {item["symbol"]: item for item in payload["lifecycle"]["decisions"]}
        self.assertEqual(decisions["BTWUSDT"]["recommendation"], "manual_hold")
        self.assertIn("manual_position_ignored", decisions["BTWUSDT"]["reasons"])
        self.assertEqual(decisions["BTCUSDT"]["matching_intent_event_id"], active_intent_id)

        self.assertEqual(payload["exit_plan"]["status"], "exit_plan_blocked")
        self.assertEqual(payload["live_outcomes"]["summary"]["outcome_count"], 1)
        self.assertEqual(payload["live_outcomes"]["latest_trace_ids"][0]["order_intent_event_id"], outcome_intent_id)

        trace_order_ids = {
            item.get("order_intent_event_id")
            for item in payload["trace_index"]
            if item.get("order_intent_event_id") is not None
        }
        self.assertIn(active_intent_id, trace_order_ids)
        self.assertIn(outcome_intent_id, trace_order_ids)
        self.assertIn("position_review", {item["source"] for item in payload["trace_index"]})
        self.assertIn("live_outcome", {item["source"] for item in payload["trace_index"]})
        self.assertIn("trade_trace", {item["source"] for item in payload["trace_index"]})

    def test_packet_can_run_without_signed_binance_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            _insert_closed_sol_outcome(db_path)

            report = build_pilot_learning_packet_report(
                self.config(root),
                db_path=str(db_path),
                check_binance=False,
                latest_traces=2,
            )

        payload = report.to_dict()
        self.assertEqual(payload["schema"], "bfa_pilot_learning_packet_v1")
        self.assertIn("exchange_evidence_missing", payload["source_reports"]["position_review"]["reasons"])
        self.assertFalse(payload["mutation_proof"]["places_orders"])
        self.assertEqual(payload["live_outcomes"]["summary"]["outcome_count"], 1)


def _insert_btc_live_flow(db_path: Path) -> int:
    decided_at = "2026-06-21T06:30:00Z"
    intent = OrderIntent(
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.001,
        notional_usdt=65.0,
        entry_price=65000,
        stop_price=64600,
        target_price=65800,
        leverage=10,
        mode="live",
        decided_at=decided_at,
        metadata={"ai_side": "long", "hold_time_minutes": 120},
    )
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        event_id = persist_order_intent(
            store,
            intent=intent,
            status="submitted",
            risk=RiskDecision(True, ["risk_accepted"]),
        )
        store.insert_artifact(
            "candidates",
            occurred_at=decided_at,
            source="strategy.hot",
            symbol="BTCUSDT",
            ref_id=f"candidate:BTCUSDT:{decided_at}",
            payload={"score": 91.0, "reason_codes": ["hot_symbol"], "features": {"quote_volume": 100000000}},
            event_type="candidate",
        )
        store.insert_artifact(
            "trade_setups",
            occurred_at=decided_at,
            source="strategy.quant_setup",
            symbol="BTCUSDT",
            ref_id=f"trade_setup:BTCUSDT:{decided_at}",
            payload={
                "setup": {
                    "decision": "trade",
                    "side": "long",
                    "entry_price": 65000,
                    "stop_price": 64600,
                    "target_price": 65800,
                    "notional_usdt": 65,
                    "regime": "momentum_expansion",
                    "factor_scores": [{"name": "momentum", "weighted_score": 12, "reasons": ["24h_momentum"]}],
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
            symbol="BTCUSDT",
            ref_id=f"ai_decision:BTCUSDT:{decided_at}",
            payload={
                "validation": {
                    "accepted": True,
                    "decision": {"decision": "trade", "side": "long", "confidence": 0.72},
                    "validation_errors": [],
                }
            },
            event_type="ai_decision",
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
        return event_id
    finally:
        connection.close()


def _insert_closed_sol_outcome(db_path: Path) -> int:
    decided_at = "2026-06-21T05:00:00Z"
    intent = OrderIntent(
        symbol="SOLUSDT",
        side="BUY",
        quantity=1.0,
        notional_usdt=140.0,
        entry_price=140,
        stop_price=138,
        target_price=144,
        leverage=10,
        mode="live",
        decided_at=decided_at,
        metadata={"ai_side": "long", "hold_time_minutes": 60},
    )
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        event_id = persist_order_intent(
            store,
            intent=intent,
            status="submitted",
            risk=RiskDecision(True, ["risk_accepted"]),
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
                    "price_basis": {"profile": "quant_setup_selective"},
                    "reasons": ["quant_long_setup", "taker_buy_bias"],
                    "factor_scores": [
                        {"name": "taker_flow", "weighted_score": -8, "reasons": ["taker_flow_faded"]}
                    ],
                    "warnings": [],
                }
            },
            event_type="trade_setup",
        )
        store.insert_artifact(
            "outcomes",
            occurred_at="2026-06-21T05:45:00Z",
            source="binance_usdm",
            symbol="SOLUSDT",
            ref_id=f"outcome:{event_id}:closed",
            payload={
                "intent": {"event_id": event_id, "symbol": "SOLUSDT", "side": "BUY", "occurred_at": decided_at},
                "status": "closed",
                "trade_count": 2,
                "gross_realized_pnl_usdt": -0.21,
                "commission_usdt": 0.01,
                "net_realized_pnl_usdt": -0.22,
                "first_trade_time": decided_at,
                "last_trade_time": "2026-06-21T05:45:00Z",
                "exit_reason": "stop_loss",
            },
            event_type="outcome",
        )
        return event_id
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
