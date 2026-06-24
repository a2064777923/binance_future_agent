import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.ops.post_trade_path import build_post_trade_path_report


class FakeKlineClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def klines(self, symbol, *, interval, start_time=None, end_time=None, limit=30):
        self.calls.append(
            {
                "symbol": symbol,
                "interval": interval,
                "start_time": start_time,
                "end_time": end_time,
                "limit": limit,
            }
        )
        return type("Response", (), {"payload": list(self.rows)})()


class PostTradePathTests(unittest.TestCase):
    def test_classifies_stop_then_target_as_direction_right_with_bad_entry_or_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "agent.sqlite"
            intent_event_id = _seed_closed_outcome(db_path)
            client = FakeKlineClient(
                [
                    _kline(1782000000000, open_=100.0, high=100.4, low=98.8, close=99.2, quote_volume=1_000_000),
                    _kline(1782000060000, open_=99.2, high=101.8, low=99.1, close=101.2, quote_volume=1_200_000),
                    _kline(1782000120000, open_=101.2, high=103.4, low=100.9, close=103.0, quote_volume=1_400_000),
                ]
            )

            report = build_post_trade_path_report(
                load_config({"BFA_DB_PATH": str(db_path)}),
                client=client,
                db_path=str(db_path),
                latest_limit=1,
                lookahead_minutes=10,
            )

        payload = report.to_dict()
        outcome = payload["outcomes"][0]
        self.assertEqual(payload["status"], "path_ready")
        self.assertEqual(outcome["intent_event_id"], intent_event_id)
        self.assertEqual(outcome["path"]["first_hit"], "stop")
        self.assertTrue(outcome["path"]["would_hit_target_after_stop"])
        self.assertIn("direction_right_stop_or_entry_bad", outcome["classification"]["labels"])


def _seed_closed_outcome(db_path: Path) -> int:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    store = EventStore(connection)
    decided_at = "2026-06-21T00:00:00Z"
    intent_event_id = store.insert_artifact(
        "order_intents",
        occurred_at=decided_at,
        source="test",
        symbol="BTCUSDT",
        ref_id=f"order_intent:BTCUSDT:{decided_at}",
        event_type="order_intent",
        payload={
            "status": "submitted",
            "intent": {
                "decided_at": decided_at,
                "symbol": "BTCUSDT",
                "side": "BUY",
                "entry_price": 100.0,
                "stop_price": 99.0,
                "target_price": 103.0,
                "notional_usdt": 20.0,
            },
        },
    )
    store.insert_artifact(
        "trade_setups",
        occurred_at=decided_at,
        source="test",
        symbol="BTCUSDT",
        ref_id=f"trade_setup:BTCUSDT:{decided_at}",
        event_type="trade_setup",
        payload={
            "setup": {
                "side": "long",
                "entry_price": 100.0,
                "stop_price": 99.0,
                "target_price": 103.0,
                "notional_usdt": 20.0,
                "reasons": ["quant_long_setup"],
            }
        },
    )
    store.insert_artifact(
        "outcomes",
        occurred_at="2026-06-21T00:03:00Z",
        source="test",
        symbol="BTCUSDT",
        ref_id=f"outcome:{intent_event_id}:closed",
        event_type="trade_outcome",
        payload={
            "schema": "bfa_trade_outcome_v1",
            "symbol": "BTCUSDT",
            "status": "closed",
            "first_trade_time": decided_at,
            "last_trade_time": "2026-06-21T00:03:00Z",
            "net_realized_pnl_usdt": -0.25,
            "intent": {"event_id": intent_event_id, "side": "BUY", "occurred_at": decided_at},
        },
    )
    connection.close()
    return intent_event_id


def _kline(open_time, *, open_, high, low, close, quote_volume):
    close_time = open_time + 59_999
    return [
        open_time,
        str(open_),
        str(high),
        str(low),
        str(close),
        "1000",
        close_time,
        str(quote_volume),
        100,
        "500",
        str(quote_volume / 2),
        "0",
    ]


if __name__ == "__main__":
    unittest.main()
