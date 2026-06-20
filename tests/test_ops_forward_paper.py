import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.event_store.store import EventStore
from bfa.market.models import MarketDataResponse
from bfa.ops.forward_paper import run_forward_paper
from bfa.strategy.paper_guard import ForwardPaperGuardConfig


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
                observation_count = connection.execute("SELECT COUNT(*) AS count FROM paper_observations").fetchone()["count"]
                intent_count = connection.execute("SELECT COUNT(*) AS count FROM order_intents").fetchone()["count"]
            finally:
                connection.close()

        self.assertEqual(report.status, "paper_run_complete")
        self.assertEqual(report.persisted["paper_signals"], 1)
        self.assertEqual(report.persisted["paper_observations"], 1)
        self.assertEqual(signal_count, 1)
        self.assertEqual(observation_count, 1)
        self.assertEqual(intent_count, 0)
        self.assertEqual(report.observation_summary, {"generated_signal": 1})
        self.assertEqual(report.paper_observations[0]["status"], "generated_signal")
        self.assertGreater(len(report.paper_observations[0]["factor_scores"]), 0)
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

    def test_forward_paper_guard_skips_blocked_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            store = EventStore(connection)
            for index in range(3):
                signal_id = store.insert_artifact(
                    "paper_signals",
                    occurred_at=f"2026-06-20T00:0{index}:00Z",
                    source="test",
                    symbol="BTCUSDT",
                    ref_id=f"paper_signal:btc:{index}",
                    event_type="paper_signal",
                    payload={
                        "schema": "bfa_paper_signal_v1",
                        "symbol": "BTCUSDT",
                        "interval": "5m",
                        "variant": "quant_setup",
                        "opened_at": f"2026-06-20T00:0{index}:00Z",
                        "expiry_time": "2026-06-20T00:20:00Z",
                        "side": "long",
                        "entry_price": 100.0,
                        "stop_price": 98.0,
                        "target_price": 104.0,
                        "notional_usdt": 12.0,
                        "hold_bars": 4,
                        "status": "open",
                        "setup": {"factor_scores": []},
                    },
                )
                store.insert_artifact(
                    "paper_outcomes",
                    occurred_at=f"2026-06-20T01:0{index}:00Z",
                    source="test",
                    symbol="BTCUSDT",
                    ref_id=f"paper_outcome:btc:{index}",
                    event_type="paper_outcome",
                    payload={
                        "schema": "bfa_paper_outcome_v1",
                        "signal_event_id": signal_id,
                        "symbol": "BTCUSDT",
                        "interval": "5m",
                        "variant": "quant_setup",
                        "opened_at": f"2026-06-20T00:0{index}:00Z",
                        "closed_at": f"2026-06-20T01:0{index}:00Z",
                        "side": "long",
                        "entry_price": 100.0,
                        "exit_price": 98.0,
                        "quantity": 0.12,
                        "notional_usdt": 12.0,
                        "gross_pnl_usdt": -0.3,
                        "fees_usdt": 0.0,
                        "slippage_usdt": 0.0,
                        "net_pnl_usdt": -0.3,
                        "exit_reason": "stop_loss",
                    },
                )
            connection.close()

            report = run_forward_paper(
                client=FakeClient(trend_rows(24)),
                db_path=str(db),
                symbols=["BTCUSDT"],
                interval="5m",
                variant="quant_setup",
                limit=18,
                paper_guard_config=ForwardPaperGuardConfig(
                    variant="quant_setup",
                    min_total_outcomes=3,
                    min_symbol_outcomes=3,
                    symbol_min_loss_usdt=0.5,
                    symbol_max_win_rate=0.1,
                ),
            )

        self.assertEqual(report.generated_signals, 0)
        self.assertEqual(report.skipped_signals, 1)
        self.assertEqual(report.persisted["paper_observations"], 1)
        self.assertEqual(report.observation_summary, {"blocked_by_guard": 1})
        self.assertEqual(report.paper_observations[0]["status"], "blocked_by_guard")
        self.assertEqual(report.paper_observations[0]["reason_codes"], ["forward_paper_symbol_block:BTCUSDT"])
        self.assertEqual(report.guarded_symbols, ["BTCUSDT"])
        self.assertEqual(report.paper_guard["status"], "active")

    def test_forward_paper_run_records_setup_pass_observation(self):
        flat_rows = [
            kline(
                index,
                open_price=100.0,
                high=100.2,
                low=99.8,
                close=100.0,
                taker_ratio=1.0,
            )
            for index in range(18)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            report = run_forward_paper(
                client=FakeClient(flat_rows),
                db_path=str(db),
                symbols=["BTCUSDT"],
                interval="5m",
                variant="quant_setup_selective",
                limit=18,
                now="2026-06-20T00:00:00Z",
            )
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            try:
                observation_count = connection.execute("SELECT COUNT(*) AS count FROM paper_observations").fetchone()["count"]
            finally:
                connection.close()

        self.assertEqual(report.generated_signals, 0)
        self.assertEqual(report.skipped_signals, 1)
        self.assertEqual(observation_count, 1)
        self.assertEqual(report.observation_summary, {"setup_pass": 1})
        observation = report.paper_observations[0]
        self.assertEqual(observation["status"], "setup_pass")
        self.assertIn("quant_setup_pass", observation["reason_codes"])
        self.assertGreater(len(observation["factor_scores"]), 0)

    def test_forward_paper_run_reports_event_store_narrative_source_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            store = EventStore(connection)
            store.insert_artifact(
                "narratives",
                occurred_at="2026-06-20T00:00:00Z",
                source="binance_square",
                symbol="BTCUSDT",
                ref_id="square:btc",
                event_type="narrative",
                payload={
                    "schema": "bfa_normalized_narrative_v1",
                    "source": "binance_square",
                    "symbol_mentions": ["BTCUSDT"],
                },
            )
            connection.close()

            report = run_forward_paper(
                client=FakeClient(trend_rows(24)),
                db_path=str(db),
                symbols=["BTCUSDT"],
                interval="5m",
                variant="quant_setup",
                limit=18,
                now="2026-06-20T00:05:00Z",
            )

        narrative_health = report.source_health["event_store_narratives"]
        self.assertEqual(narrative_health["status"], "available")
        self.assertEqual(narrative_health["matched_records"], 1)
        self.assertEqual(narrative_health["sources"], {"binance_square": 1})
        self.assertEqual(narrative_health["covered_symbols"], ["BTCUSDT"])


if __name__ == "__main__":
    unittest.main()
