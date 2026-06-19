import sqlite3
import unittest

from bfa.event_store.report import generate_review_report
from bfa.event_store.replay import build_replay_packet
from bfa.event_store.store import EventStore


class EventStoreReplayReportTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)

    def test_replay_packet_is_stable(self):
        self.store.insert_artifact(
            "narratives",
            occurred_at="2026-06-19T09:00:00Z",
            source="manual",
            symbol="BTCUSDT",
            ref_id="n1",
            payload={"text": "BTCUSDT"},
            event_type="narrative",
        )
        self.store.insert_artifact(
            "market_snapshots",
            occurred_at="2026-06-19T09:01:00Z",
            source="binance_usdm",
            symbol="BTCUSDT",
            ref_id="m1",
            payload={"last_price": "70000"},
            event_type="market_snapshot",
        )

        packet = build_replay_packet(
            self.store,
            start="2026-06-19T00:00:00Z",
            end="2026-06-20T00:00:00Z",
            symbol="BTCUSDT",
        )

        self.assertEqual(packet["event_count"], 2)
        self.assertEqual(packet["symbols"], ["BTCUSDT"])
        self.assertEqual([record["ref_id"] for record in packet["records"]], ["n1", "m1"])

    def test_empty_review_report_returns_zero_metrics(self):
        report = generate_review_report(self.connection).to_dict()

        self.assertEqual(report["trade_count"], 0)
        self.assertEqual(report["win_rate"], 0.0)
        self.assertEqual(report["reason_codes"], {})

    def test_review_report_computes_outcome_and_fill_metrics(self):
        self.store.insert_artifact(
            "outcomes",
            occurred_at="2026-06-19T10:00:00Z",
            symbol="BTCUSDT",
            ref_id="trade-1",
            payload={
                "gross_pnl_usdt": 3.0,
                "fees_usdt": 0.2,
                "slippage_usdt": 0.1,
                "net_pnl_usdt": 2.7,
                "reason_codes": ["narrative_heat", "momentum"],
            },
        )
        self.store.insert_artifact(
            "outcomes",
            occurred_at="2026-06-19T11:00:00Z",
            symbol="ETHUSDT",
            ref_id="trade-2",
            payload={
                "gross_pnl_usdt": -1.0,
                "fees_usdt": 0.1,
                "slippage_usdt": 0.1,
                "net_pnl_usdt": -1.2,
                "reason_codes": ["momentum"],
            },
        )
        self.store.insert_artifact(
            "fills",
            occurred_at="2026-06-19T11:01:00Z",
            symbol="ETHUSDT",
            ref_id="fill-2",
            payload={"fees_usdt": 0.05, "slippage_usdt": 0.02},
        )

        report = generate_review_report(self.connection).to_dict()

        self.assertEqual(report["trade_count"], 2)
        self.assertEqual(report["wins"], 1)
        self.assertEqual(report["losses"], 1)
        self.assertEqual(report["win_rate"], 0.5)
        self.assertAlmostEqual(report["gross_pnl_usdt"], 2.0)
        self.assertAlmostEqual(report["fees_usdt"], 0.35)
        self.assertAlmostEqual(report["slippage_usdt"], 0.22)
        self.assertAlmostEqual(report["net_pnl_usdt"], 1.5)
        self.assertAlmostEqual(report["expectancy_usdt"], 0.75)
        self.assertAlmostEqual(report["max_drawdown_usdt"], 1.2)
        self.assertEqual(report["reason_codes"]["momentum"]["count"], 2)
        self.assertAlmostEqual(report["reason_codes"]["momentum"]["net_pnl_usdt"], 1.5)


if __name__ == "__main__":
    unittest.main()

