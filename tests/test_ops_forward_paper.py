import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.event_store.store import EventStore
from bfa.market.models import MarketDataResponse
from bfa.ops.forward_paper import run_forward_paper


FIVE_MINUTES_MS = 300_000


def kline(index, *, open_price, high, low, close, quote_volume=3_000_000, taker_ratio=1.35):
    taker_buy_quote = quote_volume * (taker_ratio / (1 + taker_ratio))
    open_time = 1_700_000_000_000 + index * FIVE_MINUTES_MS
    return [
        open_time,
        str(open_price),
        str(high),
        str(low),
        str(close),
        "1000",
        open_time + FIVE_MINUTES_MS - 1,
        str(quote_volume),
        10,
        "500",
        str(taker_buy_quote),
        "0",
    ]


def trend_rows(count=24):
    rows = []
    price = 100.0
    for index in range(count):
        close = price * 1.018
        rows.append(
            kline(
                index,
                open_price=price,
                high=close * 1.018,
                low=price * 0.999,
                close=close,
            )
        )
        price = close
    return rows


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def klines(self, symbol, *, interval, limit=30, start_time=None, end_time=None):
        self.calls.append((symbol, interval, limit, start_time, end_time))
        return MarketDataResponse(endpoint="/fapi/v1/klines", params={}, payload=self.rows[-limit:])


class ForwardPaperTests(unittest.TestCase):
    def test_forward_paper_run_records_signal_when_setup_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            report = run_forward_paper(
                client=FakeClient(trend_rows(24)),
                db_path=str(db),
                symbols=["btcusdt"],
                interval="5m",
                variant="quant_setup",
                limit=18,
                now="2026-06-20T00:00:00Z",
            )
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            try:
                signal_count = connection.execute("SELECT COUNT(*) AS count FROM paper_signals").fetchone()["count"]
                intent_count = connection.execute("SELECT COUNT(*) AS count FROM order_intents").fetchone()["count"]
            finally:
                connection.close()

        self.assertEqual(report.status, "paper_run_complete")
        self.assertEqual(report.persisted["paper_signals"], 1)
        self.assertEqual(signal_count, 1)
        self.assertEqual(intent_count, 0)
        self.assertEqual(report.paper_signals[0]["symbol"], "BTCUSDT")
        self.assertEqual(report.paper_signals[0]["recorded_at"], "2026-06-20T00:00:00Z")

    def test_forward_paper_run_settles_existing_open_signal(self):
        rows = trend_rows(24)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            store = EventStore(connection)
            signal_id = store.insert_artifact(
                "paper_signals",
                occurred_at="2023-11-14T22:13:20Z",
                source="test",
                symbol="BTCUSDT",
                ref_id="paper_signal:test",
                event_type="paper_signal",
                payload={
                    "schema": "bfa_paper_signal_v1",
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "variant": "quant_setup",
                    "opened_at": "2023-11-14T22:13:20Z",
                    "expiry_time": "2023-11-14T22:28:19Z",
                    "side": "long",
                    "entry_price": 100.0,
                    "stop_price": 98.0,
                    "target_price": 102.0,
                    "notional_usdt": 12.0,
                    "hold_bars": 3,
                    "status": "open",
                    "setup": {},
                },
            )
            connection.close()

            report = run_forward_paper(
                client=FakeClient(rows),
                db_path=str(db),
                symbols=["BTCUSDT"],
                interval="5m",
                variant="quant_setup",
                limit=24,
            )
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            try:
                outcome = connection.execute("SELECT payload_json FROM paper_outcomes").fetchone()
            finally:
                connection.close()

        payload = json.loads(outcome["payload_json"])
        self.assertEqual(report.settled_outcomes, 1)
        self.assertEqual(report.persisted["paper_outcomes"], 1)
        self.assertEqual(payload["signal_event_id"], signal_id)
        self.assertIn(payload["exit_reason"], {"take_profit", "time_exit", "stop_loss"})
        self.assertGreater(payload["net_pnl_usdt"], 0)


if __name__ == "__main__":
    unittest.main()
