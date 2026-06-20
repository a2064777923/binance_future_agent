import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_exchange_response, persist_order_intent
from bfa.ops.exposure_clearance import build_exposure_clearance_report


class FakeSignedClient:
    def __init__(self, *, positions=None, open_orders=None, open_algo_orders=None):
        self.positions = [] if positions is None else positions
        self.orders = [] if open_orders is None else open_orders
        self.algo_orders = [] if open_algo_orders is None else open_algo_orders

    def account(self):
        return {"availableBalance": "30", "totalWalletBalance": "30"}

    def position_risk(self):
        return list(self.positions)

    def open_orders(self):
        return list(self.orders)

    def open_algo_orders(self):
        return list(self.algo_orders)


class ExposureClearanceTests(unittest.TestCase):
    def test_classifies_agent_manual_and_unknown_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            event_id = _persist_submitted_intent(db_path, symbol="SOLUSDT", side="BUY", quantity=0.16)
            report = build_exposure_clearance_report(
                _config(root),
                db_path=str(db_path),
                signed_client=FakeSignedClient(
                    positions=[
                        _position("SOLUSDT", "0.16", "LONG"),
                        _position("ETHUSDT", "0.01", "LONG"),
                        _position("XRPUSDT", "-4", "SHORT"),
                    ],
                    open_algo_orders=[
                        {"symbol": "SOLUSDT", "positionSide": "LONG", "algoId": 1},
                        {"symbol": "SOLUSDT", "positionSide": "LONG", "algoId": 2},
                        {"symbol": "ETHUSDT", "positionSide": "LONG", "algoId": 3},
                    ],
                ),
                manual_exposure_symbols=["ETHUSDT"],
            )

        payload = report.to_dict()
        by_symbol = {item["symbol"]: item for item in payload["positions"]}
        self.assertEqual(payload["status"], "resolve_exposure")
        self.assertFalse(payload["clearance_allowed"])
        self.assertEqual(by_symbol["SOLUSDT"]["classification"], "agent_managed")
        self.assertEqual(by_symbol["SOLUSDT"]["matching_intent_event_ids"], [event_id])
        self.assertTrue(by_symbol["SOLUSDT"]["protected"])
        self.assertEqual(by_symbol["ETHUSDT"]["classification"], "manual")
        self.assertEqual(by_symbol["XRPUSDT"]["classification"], "unknown")
        self.assertIn("manual_exchange_exposure_present", payload["reasons"])
        self.assertIn("unknown_exchange_exposure_present", payload["reasons"])
        self.assertFalse(payload["read_only"]["places_orders"])
        self.assertFalse(payload["read_only"]["mutates_exchange_state"])

    def test_stale_attributed_when_symbol_matches_but_quantity_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            _persist_submitted_intent(db_path, symbol="SOLUSDT", side="BUY", quantity=0.16)
            report = build_exposure_clearance_report(
                _config(root),
                db_path=str(db_path),
                signed_client=FakeSignedClient(positions=[_position("SOLUSDT", "0.20", "LONG")]),
            )

        payload = report.to_dict()
        self.assertEqual(payload["positions"][0]["classification"], "stale_attributed")
        self.assertIn("stale_attributed_exchange_exposure_present", payload["reasons"])

    def test_open_orders_and_orphan_algo_orders_block_clearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            report = build_exposure_clearance_report(
                _config(root),
                signed_client=FakeSignedClient(
                    open_orders=[{"symbol": "BNBUSDT", "orderId": 1, "side": "BUY"}],
                    open_algo_orders=[{"symbol": "BNBUSDT", "algoId": 2, "positionSide": "LONG"}],
                ),
            )

        payload = report.to_dict()
        self.assertEqual(payload["status"], "resolve_exposure")
        self.assertIn("normal_open_orders_present", payload["reasons"])
        self.assertIn("orphan_algo_orders_present", payload["reasons"])
        self.assertTrue(payload["open_orders"][0]["blocks_live_resume"])
        self.assertTrue(payload["open_algo_orders"][0]["orphan"])


def _config(root: Path):
    return load_config(
        {
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
    )


def _position(symbol: str, amount: str, side: str):
    return {
        "symbol": symbol,
        "positionAmt": amount,
        "positionSide": side,
        "entryPrice": "100",
        "markPrice": "101",
        "leverage": "5",
    }


def _persist_submitted_intent(db_path: Path, *, symbol: str, side: str, quantity: float) -> int:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        store = EventStore(connection)
        intent = OrderIntent(
            symbol=symbol,
            side=side,
            quantity=quantity,
            notional_usdt=12.0,
            entry_price=100.0,
            stop_price=98.0,
            target_price=104.0,
            leverage=5,
            mode="live",
            decided_at="2026-06-20T00:00:00Z",
            metadata={"ai_side": "long"},
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
                "entry_order": {"orderId": 1},
                "stop_loss_order": {"algoId": 1},
                "take_profit_order": {"algoId": 2},
            },
        )
        return event_id
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
