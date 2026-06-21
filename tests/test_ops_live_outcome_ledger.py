import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.ops.live_outcome_ledger import build_live_outcome_ledger_report


class FakeTradeHistoryClient:
    def __init__(self, trades_by_symbol):
        self.trades_by_symbol = trades_by_symbol
        self.calls = []

    def user_trades(self, symbol, *, start_time=None, end_time=None, limit=500):
        self.calls.append(
            {
                "symbol": symbol,
                "start_time": start_time,
                "end_time": end_time,
                "limit": limit,
            }
        )
        return list(self.trades_by_symbol.get(symbol, []))


class LiveOutcomeLedgerTests(unittest.TestCase):
    def config(self, root: Path, **overrides):
        env = {
            "BFA_MODE": "live",
            "BFA_DB_PATH": str(root / "agent.sqlite"),
            "BFA_RUNTIME_DIR": str(root / "runtime"),
            "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
            "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
        }
        env.update(overrides)
        return load_config(env)

    def test_aggregates_live_outcomes_and_recommends_guard_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            _insert_live_trade(
                db_path,
                symbol="SOLUSDT",
                side="BUY",
                decided_at="2026-06-20T10:00:00Z",
                closed_at="2026-06-20T10:22:00Z",
                pnl=-0.4,
                setup_reasons=["quant_long_setup", "taker_buy_bias"],
                factor_name="taker_flow",
                factor_reason="taker_flow_faded",
                factor_score=-12,
                exit_reason="stop_loss",
            )
            _insert_live_trade(
                db_path,
                symbol="SOLUSDT",
                side="BUY",
                decided_at="2026-06-20T11:00:00Z",
                closed_at="2026-06-20T11:45:00Z",
                pnl=-0.2,
                setup_reasons=["quant_long_setup", "taker_buy_bias"],
                factor_name="taker_flow",
                factor_reason="taker_flow_faded",
                factor_score=-9,
                exit_reason="stop_loss",
            )
            _insert_live_trade(
                db_path,
                symbol="BNBUSDT",
                side="SELL",
                decided_at="2026-06-20T12:00:00Z",
                closed_at="2026-06-20T13:30:00Z",
                pnl=0.3,
                setup_reasons=["quant_short_setup", "funding_supports_short"],
                factor_name="funding",
                factor_reason="funding_supports_short",
                factor_score=8,
                exit_reason="take_profit",
            )

            report = build_live_outcome_ledger_report(
                self.config(root),
                db_path=str(db_path),
                min_group_outcomes=2,
            )

        payload = report.to_dict()
        self.assertEqual(payload["schema"], "bfa_live_outcome_ledger_v1")
        self.assertEqual(report.status, "ledger_ready")
        self.assertEqual(payload["summary"]["outcome_count"], 3)
        self.assertEqual(payload["summary"]["win_count"], 1)
        self.assertEqual(payload["summary"]["loss_count"], 2)
        self.assertAlmostEqual(payload["summary"]["total_net_pnl_usdt"], -0.3)
        self.assertEqual(payload["summary"]["exit_reason_counts"]["stop_loss"], 2)
        self.assertEqual(payload["groups"]["symbols"][0]["name"], "SOLUSDT")
        self.assertEqual(payload["groups"]["symbols"][0]["outcome_count"], 2)
        self.assertEqual(payload["groups"]["sides"][0]["name"], "long")
        self.assertTrue(
            any(
                item["action"] == "quarantine_or_reduce_symbol"
                and item["name"] == "SOLUSDT"
                and not item["applies_changes"]
                and not item["raises_risk"]
                and item["sample_sufficient"]
                and item["recent_outcome_count"] == 2
                and item["decay_weight"] > 0
                for item in payload["guard_feedback"]
            )
        )
        self.assertEqual(payload["latest_outcomes"][0]["symbol"], "BNBUSDT")
        self.assertIn("order_intent_event_id", payload["latest_outcomes"][0]["trace_ids"])
        self.assertFalse(payload["mutation_proof"]["places_orders"])
        self.assertFalse(payload["mutation_proof"]["writes_env_files"])
        self.assertFalse(payload["mutation_proof"]["persists_closed_fills_and_outcomes"])

    def test_persist_closed_requires_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()

            report = build_live_outcome_ledger_report(
                self.config(root),
                db_path=str(root / "agent.sqlite"),
                persist_closed=True,
            )

        payload = report.to_dict()
        self.assertEqual(report.status, "ledger_blocked")
        self.assertEqual(payload["reasons"], ["persist_closed_requires_reconcile"])
        self.assertTrue(payload["mutation_proof"]["persists_closed_fills_and_outcomes"])
        self.assertFalse(payload["mutation_proof"]["places_orders"])

    def test_reconcile_requires_signed_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()

            report = build_live_outcome_ledger_report(
                self.config(root),
                db_path=str(root / "agent.sqlite"),
                reconcile=True,
            )

        payload = report.to_dict()
        self.assertEqual(report.status, "ledger_blocked")
        self.assertEqual(payload["reasons"], ["signed_client_required_for_reconcile"])
        self.assertFalse(payload["mutation_proof"]["places_orders"])
        self.assertFalse(payload["mutation_proof"]["cancels_orders"])

    def test_reconcile_persists_closed_outcome_before_reporting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db_path = root / "agent.sqlite"
            _insert_submitted_intent(
                db_path,
                symbol="ZECUSDT",
                side="BUY",
                decided_at="2026-06-20T02:49:17Z",
                quantity=0.032,
                entry_price=467.68,
            )
            fake_client = FakeTradeHistoryClient(
                {
                    "ZECUSDT": [
                        _trade(
                            trade_id=10,
                            order_id=100,
                            symbol="ZECUSDT",
                            side="BUY",
                            qty="0.032",
                            price="467.68",
                            realized_pnl="0",
                            commission="0.00748288",
                            time=1781923762837,
                        ),
                        _trade(
                            trade_id=11,
                            order_id=101,
                            symbol="ZECUSDT",
                            side="SELL",
                            qty="0.032",
                            price="471.49",
                            realized_pnl="0.12192",
                            commission="0.00754384",
                            time=1781924000000,
                        ),
                    ]
                }
            )

            report = build_live_outcome_ledger_report(
                self.config(root),
                db_path=str(db_path),
                symbol="ZECUSDT",
                reconcile=True,
                persist_closed=True,
                signed_client=fake_client,
            )
            connection = sqlite3.connect(db_path)
            try:
                fill_count = connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
                outcome_count = connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
            finally:
                connection.close()

        payload = report.to_dict()
        self.assertEqual(report.status, "ledger_ready")
        self.assertEqual(payload["reconciliation"]["closed"], 1)
        self.assertEqual(payload["reconciliation"]["persisted_outcomes_inserted"], 1)
        self.assertEqual(payload["summary"]["outcome_count"], 1)
        self.assertAlmostEqual(payload["summary"]["total_net_pnl_usdt"], 0.10689328)
        self.assertEqual(fill_count, 2)
        self.assertEqual(outcome_count, 1)
        self.assertTrue(payload["mutation_proof"]["persists_closed_fills_and_outcomes"])


def _insert_live_trade(
    db_path: Path,
    *,
    symbol: str,
    side: str,
    decided_at: str,
    closed_at: str,
    pnl: float,
    setup_reasons: list[str],
    factor_name: str,
    factor_reason: str,
    factor_score: float,
    exit_reason: str,
) -> int:
    intent_id = _insert_submitted_intent(
        db_path,
        symbol=symbol,
        side=side,
        decided_at=decided_at,
        quantity=1.0,
        entry_price=100.0,
    )
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        store.insert_artifact(
            "trade_setups",
            occurred_at=decided_at,
            source="strategy.quant_setup",
            symbol=symbol,
            ref_id=f"trade_setup:{symbol}:{decided_at}",
            payload={
                "setup": {
                    "symbol": symbol,
                    "decision": "trade",
                    "side": "long" if side == "BUY" else "short",
                    "price_basis": {"profile": "quant_setup_selective"},
                    "reasons": setup_reasons,
                    "warnings": [],
                    "factor_scores": [
                        {
                            "name": factor_name,
                            "weighted_score": factor_score,
                            "reasons": [factor_reason],
                        }
                    ],
                }
            },
            event_type="trade_setup",
        )
        store.insert_artifact(
            "ai_decisions",
            occurred_at=decided_at,
            source="deepseek.chat_completions",
            symbol=symbol,
            ref_id=f"ai_decision:{symbol}:{decided_at}",
            payload={
                "validation": {
                    "accepted": True,
                    "decision": {
                        "decision": "trade",
                        "side": "long" if side == "BUY" else "short",
                        "confidence": 0.71,
                    },
                    "validation_errors": [],
                }
            },
            event_type="ai_decision",
        )
        store.insert_artifact(
            "outcomes",
            occurred_at=closed_at,
            source="binance_usdm",
            symbol=symbol,
            ref_id=f"outcome:{intent_id}:closed",
            payload={
                "intent": {
                    "event_id": intent_id,
                    "symbol": symbol,
                    "side": side,
                    "occurred_at": decided_at,
                },
                "status": "closed",
                "trade_count": 2,
                "gross_realized_pnl_usdt": pnl,
                "commission_usdt": 0.0,
                "net_realized_pnl_usdt": pnl,
                "first_trade_time": decided_at,
                "last_trade_time": closed_at,
                "exit_reason": exit_reason,
            },
            event_type="outcome",
        )
    finally:
        connection.close()
    return intent_id


def _insert_submitted_intent(
    db_path: Path,
    *,
    symbol: str,
    side: str,
    decided_at: str,
    quantity: float,
    entry_price: float,
) -> int:
    connection = sqlite3.connect(db_path)
    try:
        store = EventStore(connection)
        return store.insert_artifact(
            "order_intents",
            occurred_at=decided_at,
            source="execution.live",
            symbol=symbol,
            ref_id=f"order_intent:{symbol}:{decided_at}",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "entry_price": entry_price,
                    "leverage": 10,
                    "decided_at": decided_at,
                },
            },
            event_type="order_intent",
        )
    finally:
        connection.close()


def _trade(
    *,
    trade_id: int,
    order_id: int,
    symbol: str,
    side: str,
    qty: str,
    price: str,
    realized_pnl: str,
    commission: str,
    time: int,
) -> dict:
    return {
        "id": trade_id,
        "orderId": order_id,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "quoteQty": str(float(qty) * float(price)),
        "realizedPnl": realized_pnl,
        "commission": commission,
        "commissionAsset": "USDT",
        "time": time,
    }


if __name__ == "__main__":
    unittest.main()
