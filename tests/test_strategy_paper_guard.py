import tempfile
import unittest
from pathlib import Path

from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.strategy.paper_guard import ForwardPaperGuardConfig, build_forward_paper_guard, merge_guard_profile


def signal_payload(symbol, *, side="long", reasons=None):
    return {
        "schema": "bfa_paper_signal_v1",
        "symbol": symbol,
        "interval": "5m",
        "variant": "quant_setup_selective",
        "opened_at": "2026-06-20T00:00:00Z",
        "expiry_time": "2026-06-20T00:20:00Z",
        "side": side,
        "entry_price": 100.0,
        "stop_price": 98.0,
        "target_price": 104.0,
        "notional_usdt": 12.0,
        "hold_bars": 4,
        "status": "open",
        "setup": {
            "side": side,
            "reasons": ["quant_long_setup"],
            "factor_scores": [
                {
                    "name": "taker_flow",
                    "weighted_score": -7.0,
                    "reasons": reasons or ["taker_flow_acceleration"],
                }
            ],
        },
    }


def outcome_payload(signal_event_id, symbol, pnl, *, side="long"):
    return {
        "schema": "bfa_paper_outcome_v1",
        "signal_event_id": signal_event_id,
        "symbol": symbol,
        "interval": "5m",
        "variant": "quant_setup_selective",
        "opened_at": "2026-06-20T00:00:00Z",
        "closed_at": "2026-06-20T00:20:00Z",
        "side": side,
        "entry_price": 100.0,
        "exit_price": 98.0 if pnl < 0 else 104.0,
        "quantity": 0.12,
        "notional_usdt": 12.0,
        "gross_pnl_usdt": pnl,
        "fees_usdt": 0.0,
        "slippage_usdt": 0.0,
        "net_pnl_usdt": pnl,
        "exit_reason": "stop_loss" if pnl < 0 else "take_profit",
    }


class ForwardPaperGuardTests(unittest.TestCase):
    def make_db(self, rows):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "guard.sqlite"
        connection = connect(db)
        store = EventStore(connection)
        for index, (symbol, pnl, side) in enumerate(rows):
            signal_id = store.insert_artifact(
                "paper_signals",
                occurred_at=f"2026-06-20T00:{index:02d}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_signal:{index}",
                event_type="paper_signal",
                payload=signal_payload(symbol, side=side),
            )
            store.insert_artifact(
                "paper_outcomes",
                occurred_at=f"2026-06-20T01:{index:02d}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_outcome:{signal_id}",
                event_type="paper_outcome",
                payload=outcome_payload(signal_id, symbol, pnl, side=side),
            )
        return connection

    def test_guard_noops_when_total_outcomes_are_insufficient(self):
        connection = self.make_db([("BTWUSDT", -0.3, "long")])
        try:
            guard = build_forward_paper_guard(connection, ForwardPaperGuardConfig(min_total_outcomes=3))
        finally:
            connection.close()

        self.assertEqual(guard.status, "insufficient_evidence")
        self.assertFalse(guard.active)
        self.assertEqual(guard.symbol_blocks, {})

    def test_guard_blocks_repeated_losing_symbol_and_factor_reason(self):
        rows = [
            ("BTWUSDT", -0.3, "long"),
            ("BTWUSDT", -0.25, "long"),
            ("BTWUSDT", -0.2, "long"),
            ("SOLUSDT", 0.2, "long"),
        ]
        connection = self.make_db(rows)
        try:
            guard = build_forward_paper_guard(
                connection,
                ForwardPaperGuardConfig(
                    min_total_outcomes=4,
                    min_symbol_outcomes=3,
                    symbol_min_loss_usdt=0.5,
                    symbol_max_win_rate=0.1,
                    min_factor_outcomes=3,
                    factor_min_loss_usdt=0.5,
                    factor_max_win_rate=0.3,
                ),
            )
        finally:
            connection.close()

        self.assertTrue(guard.active)
        self.assertTrue(guard.blocks_symbol("btwusdt"))
        self.assertIn("BTWUSDT", guard.symbol_blocks)
        self.assertIn("taker_flow_acceleration", guard.factor_blocks)
        merged = merge_guard_profile({"name": "selective"}, guard)
        self.assertIn("taker_flow_acceleration", merged["blocked_factor_reasons"])


if __name__ == "__main__":
    unittest.main()
