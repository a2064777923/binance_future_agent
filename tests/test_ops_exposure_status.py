import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_exchange_response, persist_order_intent
from bfa.ops.exposure_status import build_exposure_status_report
from bfa.ops.risk_profile import build_risk_profile_plan


class FakeSignedClient:
    def __init__(self, *, positions=None, open_orders=None, open_algo_orders=None):
        self.positions = [] if positions is None else positions
        self.orders = [] if open_orders is None else open_orders
        self.algo_orders = [] if open_algo_orders is None else open_algo_orders

    def account(self):
        return {"availableBalance": "27.9", "totalWalletBalance": "30.1"}

    def position_risk(self):
        return list(self.positions)

    def open_orders(self):
        return list(self.orders)

    def open_algo_orders(self):
        return list(self.algo_orders)


class ExposureStatusTests(unittest.TestCase):
    def config(self, root, **overrides):
        env = {
            "BFA_MODE": "live",
            "BFA_DB_PATH": str(root / "agent.sqlite"),
            "BFA_RUNTIME_DIR": str(root / "runtime"),
            "BFA_ACCOUNT_CAPITAL_USDT": "30",
            "BFA_MAX_LEVERAGE": "5",
            "BFA_MAX_POSITION_NOTIONAL_USDT": "12",
            "BFA_MAX_RISK_PER_TRADE_USDT": "0.3",
            "BFA_MAX_DAILY_LOSS_USDT": "1",
            "BFA_MAX_OPEN_POSITIONS": "1",
            "BFA_POSITION_MODE": "hedge",
            "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
            "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
        }
        env.update(overrides)
        return load_config(env)

    def test_reports_current_long_capacity_block_and_10x_multi_profile_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            _persist_submitted_hype_intent(db_path)
            client = FakeSignedClient(
                positions=[
                    {
                        "symbol": "HYPEUSDT",
                        "positionAmt": "0.16",
                        "positionSide": "LONG",
                        "entryPrice": "70.266",
                        "markPrice": "70.69",
                        "unRealizedProfit": "0.0678",
                    }
                ],
                open_algo_orders=[
                    {"symbol": "HYPEUSDT", "positionSide": "LONG"},
                    {"symbol": "HYPEUSDT", "positionSide": "LONG"},
                ],
            )

            report = build_exposure_status_report(
                self.config(root),
                db_path=str(db_path),
                signed_client=client,
                hypothetical_symbol="HYPEUSDT",
                hypothetical_side="long",
            )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "ready_for_profile_switch")
        self.assertEqual(payload["current_profile"]["max_leverage"], 5)
        self.assertFalse(payload["current_profile"]["dynamic_position_sizing_enabled"])
        self.assertAlmostEqual(payload["current_sizing"]["max_position_notional_usdt"], 12)
        self.assertTrue(payload["direction_support"]["long_entries_supported"])
        self.assertTrue(payload["direction_support"]["short_entries_supported"])
        self.assertEqual(payload["direction_support"]["long_position_side"], "LONG")
        self.assertFalse(payload["entry_capacity"]["can_open_new_position"])
        self.assertIn("multi_position_disabled", payload["entry_capacity"]["reasons"])
        self.assertIn("max_open_positions_reached", payload["entry_capacity"]["reasons"])
        self.assertIn("duplicate_symbol_direction_exposure", payload["entry_capacity"]["reasons"])
        self.assertEqual(payload["target_profile"]["target_leverage"], 10)
        self.assertTrue(payload["target_sizing"]["enabled"])
        self.assertAlmostEqual(payload["target_sizing"]["max_position_notional_usdt"], 40)
        self.assertTrue(payload["risk_change"]["risk_change_allowed"])
        self.assertIn("active_position_within_target_profile_caps", payload["risk_change"]["reasons"])
        self.assertIn("active_position_present", payload["risk_change"]["reasons"])
        self.assertIn("submitted_intents_missing_outcomes", payload["risk_change"]["reasons"])

    def test_reports_profile_switch_ready_when_exchange_clear_and_outcomes_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            event_id = _persist_submitted_hype_intent(db_path)
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            try:
                EventStore(connection).insert_artifact(
                    "outcomes",
                    occurred_at="2026-06-20T06:00:00Z",
                    source="binance_usdm",
                    symbol="HYPEUSDT",
                    ref_id=f"outcome:{event_id}:closed",
                    payload={"status": "closed"},
                    event_type="outcome",
                )
            finally:
                connection.close()

            report = build_exposure_status_report(
                self.config(root),
                db_path=str(db_path),
                signed_client=FakeSignedClient(),
                allow_two_positions=True,
                hypothetical_symbol="SOLUSDT",
                hypothetical_side="short",
            )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "ready_for_profile_switch")
        self.assertTrue(payload["entry_capacity"]["can_open_new_position"])
        self.assertEqual(payload["entry_capacity"]["reasons"], ["entry_capacity_available"])
        self.assertEqual(payload["entry_capacity"]["hypothetical"]["order_side"], "SELL")
        self.assertEqual(payload["entry_capacity"]["hypothetical"]["direction"], "SHORT")
        self.assertTrue(payload["risk_change"]["risk_change_allowed"])
        self.assertEqual(payload["target_profile"]["target_values"]["BFA_MAX_OPEN_POSITIONS"], "4")
        self.assertEqual(payload["target_profile"]["target_values"]["BFA_MULTI_POSITION_ENABLED"], "true")
        self.assertEqual(
            payload["target_profile"]["confirmation_token"],
            build_risk_profile_plan(
                self.config(root),
                profile="30u_10x_multi_dynamic",
                allow_two_positions=True,
            ).confirmation_token,
        )


def _persist_submitted_hype_intent(db_path: Path) -> int:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        store = EventStore(connection)
        intent = OrderIntent(
            symbol="HYPEUSDT",
            side="BUY",
            quantity=0.16,
            notional_usdt=11.24256,
            entry_price=70.266,
            stop_price=69.6,
            target_price=71.5,
            leverage=5,
            mode="live",
            decided_at="2026-06-20T05:26:07Z",
            metadata={"ai_side": "long", "hold_time_minutes": 120},
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
                "entry_order": {"orderId": 9598413023},
                "stop_loss_order": {"algoId": 1},
                "take_profit_order": {"algoId": 2},
            },
        )
        return event_id
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
