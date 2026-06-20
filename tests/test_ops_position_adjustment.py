import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.store import EventStore
from bfa.execution.filters import SymbolExecutionFilters
from bfa.ops.live_status import LiveStatusReport, OpenAiBackoffStatus, ProtectiveEvidence
from bfa.ops.position_adjustment import (
    build_position_adjustment_execute_report,
    build_position_adjustment_plan_report,
    position_adjustment_plan_from_review,
)
from bfa.ops.position_hold_check import position_hold_check_from_live_status
from bfa.ops.position_review import position_review_from_hold_check


EXCHANGE_INFO = Path(__file__).parent / "fixtures" / "binance_market" / "exchange_info.json"


def report(*, positions=None, open_orders=None, open_algo_orders=None):
    return LiveStatusReport(
        db_path=":memory:",
        runtime_dir="/tmp",
        counts={},
        latest={},
        openai_backoff=OpenAiBackoffStatus(active=False),
        protective_evidence=ProtectiveEvidence(
            complete=True,
            status="entry_with_stop_loss_and_take_profit",
        ),
        lva05_complete=True,
        exchange_evidence={
            "account": {"available_balance": "30"},
            "positions": [] if positions is None else positions,
            "open_orders": [] if open_orders is None else open_orders,
            "open_algo_orders": [] if open_algo_orders is None else open_algo_orders,
        },
    )


class FakeSignedClient:
    def __init__(self, *, mark_price="107", close_sets_position_zero=False):
        self.mark_price = mark_price
        self.closed = False
        self.close_sets_position_zero = close_sets_position_zero
        self.orders = []
        self.cancelled_algo_symbols = []

    def account(self):
        return {"availableBalance": "30", "totalWalletBalance": "30"}

    def position_risk(self):
        amount = "0" if self.closed else "0.2"
        return [
            {
                "symbol": "BTCUSDT",
                "positionAmt": amount,
                "positionSide": "LONG",
                "entryPrice": "100",
                "markPrice": self.mark_price,
                "unRealizedProfit": str((float(self.mark_price) - 100) * float(amount)),
            }
        ]

    def open_orders(self):
        return []

    def open_algo_orders(self):
        return [
            {"symbol": "BTCUSDT", "positionSide": "LONG"},
            {"symbol": "BTCUSDT", "positionSide": "LONG"},
        ]

    def new_order(self, **kwargs):
        self.orders.append(kwargs)
        if kwargs.get("quantity") == 0.2 and self.close_sets_position_zero:
            self.closed = True
        return {"orderId": len(self.orders), "symbol": kwargs["symbol"], "side": kwargs["side"]}

    def cancel_all_open_algo_orders(self, symbol):
        self.cancelled_algo_symbols.append(symbol)
        return {"code": 200, "msg": "success", "symbol": symbol}


class PositionAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)

    def tearDown(self):
        self.connection.close()

    def insert_submitted_intent(
        self,
        *,
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.2,
        entry_price=100,
        stop_price=96,
        target_price=108,
        hold_time_minutes=120,
    ):
        self.store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:00:00Z",
            source="execution.live",
            symbol=symbol,
            ref_id=f"order_intent:{symbol}:2026-06-20T03:00:00Z",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "leverage": 5,
                    "metadata": {"hold_time_minutes": hold_time_minutes},
                },
            },
            event_type="order_intent",
        )

    def review(self, *, mark_price, checked_at="2026-06-20T03:30:00Z", hold_time_minutes=120):
        self.insert_submitted_intent(hold_time_minutes=hold_time_minutes)
        hold_check = position_hold_check_from_live_status(
            report(
                positions=[
                    {
                        "symbol": "BTCUSDT",
                        "positionAmt": "0.2",
                        "positionSide": "LONG",
                        "entryPrice": "100",
                        "markPrice": str(mark_price),
                        "unRealizedProfit": str((mark_price - 100) * 0.2),
                    }
                ],
                open_algo_orders=[
                    {"symbol": "BTCUSDT", "positionSide": "LONG"},
                    {"symbol": "BTCUSDT", "positionSide": "LONG"},
                ],
            ),
            connection=self.connection,
            checked_at=checked_at,
        )
        return position_review_from_hold_check(hold_check)

    def test_near_target_position_plans_partial_take_profit(self):
        adjustment = position_adjustment_plan_from_review(
            self.review(mark_price=107),
            position_mode="hedge",
            partial_take_profit_fraction=0.5,
        )

        self.assertEqual(adjustment.status, "adjustment_plan_ready")
        self.assertTrue(adjustment.adjustment_allowed)
        order_plan = adjustment.plans[0].order_plan
        self.assertEqual(order_plan.action, "partial_take_profit")
        self.assertEqual(order_plan.side, "SELL")
        self.assertEqual(order_plan.quantity, 0.1)
        self.assertEqual(order_plan.position_side, "LONG")
        self.assertFalse(order_plan.reduce_only)

    def test_partial_take_profit_quantity_respects_step_size(self):
        adjustment = position_adjustment_plan_from_review(
            self.review(mark_price=107),
            position_mode="hedge",
            partial_take_profit_fraction=0.333,
            filters_by_symbol={
                "BTCUSDT": SymbolExecutionFilters(
                    symbol="BTCUSDT",
                    step_size=Decimal("0.01"),
                    min_qty=Decimal("0.01"),
                    min_notional=Decimal("5"),
                )
            },
        )

        order_plan = adjustment.plans[0].order_plan
        self.assertEqual(adjustment.status, "adjustment_plan_ready")
        self.assertAlmostEqual(order_plan.quantity, 0.06)
        self.assertIn("quantity_filter_checked", order_plan.reason_codes)

    def test_partial_take_profit_blocks_when_min_notional_would_fail(self):
        adjustment = position_adjustment_plan_from_review(
            self.review(mark_price=107),
            position_mode="hedge",
            partial_take_profit_fraction=0.1,
            filters_by_symbol={
                "BTCUSDT": SymbolExecutionFilters(
                    symbol="BTCUSDT",
                    step_size=Decimal("0.01"),
                    min_qty=Decimal("0.01"),
                    min_notional=Decimal("50"),
                )
            },
        )

        self.assertFalse(adjustment.adjustment_allowed)
        self.assertIn("notional_below_min", adjustment.plans[0].reasons)

    def test_expired_position_plans_full_close(self):
        adjustment = position_adjustment_plan_from_review(
            self.review(mark_price=101, checked_at="2026-06-20T04:10:00Z", hold_time_minutes=30),
            position_mode="one_way",
        )

        self.assertEqual(adjustment.status, "adjustment_plan_ready")
        order_plan = adjustment.plans[0].order_plan
        self.assertEqual(order_plan.action, "full_close")
        self.assertEqual(order_plan.quantity, 0.2)
        self.assertEqual(order_plan.side, "SELL")
        self.assertIsNone(order_plan.position_side)
        self.assertTrue(order_plan.reduce_only)

    def test_watch_position_does_not_allow_adjustment(self):
        adjustment = position_adjustment_plan_from_review(
            self.review(mark_price=101, checked_at="2026-06-20T04:00:00Z", hold_time_minutes=70),
            position_mode="hedge",
        )

        self.assertFalse(adjustment.adjustment_allowed)
        self.assertEqual(adjustment.plans[0].reasons, ["watch_only_recheck_later"])

    def test_diagnostics_show_close_ready_and_manual_hold_without_blocking(self):
        self.insert_submitted_intent(hold_time_minutes=30)
        hold_check = position_hold_check_from_live_status(
            report(
                positions=[
                    {
                        "symbol": "BTCUSDT",
                        "positionAmt": "0.2",
                        "positionSide": "LONG",
                        "entryPrice": "100",
                        "markPrice": "101",
                        "unRealizedProfit": "0.2",
                    },
                    {
                        "symbol": "BTWUSDT",
                        "positionAmt": "-556",
                        "positionSide": "SHORT",
                        "entryPrice": "0.02",
                        "markPrice": "0.019",
                        "unRealizedProfit": "0.556",
                    },
                ],
                open_algo_orders=[
                    {"symbol": "BTCUSDT", "positionSide": "LONG"},
                    {"symbol": "BTCUSDT", "positionSide": "LONG"},
                ],
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:10:00Z",
        )
        review = position_review_from_hold_check(hold_check, manual_symbols={"BTWUSDT"})

        adjustment = position_adjustment_plan_from_review(
            review,
            position_mode="hedge",
            filters_by_symbol={
                "BTCUSDT": SymbolExecutionFilters(
                    symbol="BTCUSDT",
                    step_size=Decimal("0.01"),
                    min_qty=Decimal("0.01"),
                    min_notional=Decimal("5"),
                )
            },
            require_filters=True,
        )

        self.assertEqual(adjustment.status, "adjustment_plan_ready")
        self.assertTrue(adjustment.adjustment_allowed)
        self.assertEqual(len(adjustment.plans), 1)
        diagnostics = {item.symbol: item for item in adjustment.diagnostics}
        self.assertEqual(diagnostics["BTCUSDT"].lifecycle_decision, "close_ready")
        self.assertEqual(diagnostics["BTCUSDT"].candidate_action, "full_close")
        self.assertEqual(diagnostics["BTCUSDT"].exchange_filter_state, "checked")
        self.assertEqual(diagnostics["BTCUSDT"].failed_preconditions, [])
        self.assertEqual(diagnostics["BTCUSDT"].order_plan.quantity, 0.2)
        self.assertEqual(diagnostics["BTWUSDT"].lifecycle_decision, "manual_hold")
        self.assertTrue(diagnostics["BTWUSDT"].manual_symbol)
        self.assertIsNone(diagnostics["BTWUSDT"].order_plan)
        self.assertIn("manual_position_ignored", diagnostics["BTWUSDT"].failed_preconditions)

    def test_diagnostics_explain_blocked_close_review_when_filters_are_missing(self):
        adjustment = position_adjustment_plan_from_review(
            self.review(mark_price=101, checked_at="2026-06-20T04:10:00Z", hold_time_minutes=30),
            position_mode="hedge",
            filters_by_symbol={},
            require_filters=True,
        )

        self.assertEqual(adjustment.status, "adjustment_plan_blocked")
        self.assertFalse(adjustment.adjustment_allowed)
        diagnostic = adjustment.diagnostics[0]
        self.assertEqual(diagnostic.lifecycle_decision, "blocked")
        self.assertEqual(diagnostic.exchange_filter_state, "missing")
        self.assertIn("symbol_filters_missing", diagnostic.failed_preconditions)
        self.assertIsNone(diagnostic.order_plan)

    def test_diagnostics_preserve_urgent_unprotected_priority_over_expired_hold(self):
        self.insert_submitted_intent(symbol="BTCUSDT", hold_time_minutes=120)
        self.insert_submitted_intent(
            symbol="ETHUSDT",
            quantity=0.1,
            entry_price=100,
            stop_price=96,
            target_price=108,
            hold_time_minutes=30,
        )
        hold_check = position_hold_check_from_live_status(
            report(
                positions=[
                    {
                        "symbol": "BTCUSDT",
                        "positionAmt": "0.2",
                        "positionSide": "LONG",
                        "entryPrice": "100",
                        "markPrice": "100.5",
                        "unRealizedProfit": "0.1",
                    },
                    {
                        "symbol": "ETHUSDT",
                        "positionAmt": "0.1",
                        "positionSide": "LONG",
                        "entryPrice": "100",
                        "markPrice": "101",
                        "unRealizedProfit": "0.1",
                    },
                ],
                open_algo_orders=[
                    {"symbol": "ETHUSDT", "positionSide": "LONG"},
                    {"symbol": "ETHUSDT", "positionSide": "LONG"},
                ],
            ),
            connection=self.connection,
            checked_at="2026-06-20T04:10:00Z",
        )
        review = position_review_from_hold_check(hold_check)

        adjustment = position_adjustment_plan_from_review(
            review,
            position_mode="hedge",
            filters_by_symbol={
                "BTCUSDT": SymbolExecutionFilters(symbol="BTCUSDT", step_size=Decimal("0.01")),
                "ETHUSDT": SymbolExecutionFilters(symbol="ETHUSDT", step_size=Decimal("0.01")),
            },
            require_filters=True,
        )

        diagnostics = {item.symbol: item for item in adjustment.diagnostics}
        self.assertEqual(diagnostics["BTCUSDT"].urgency, "urgent")
        self.assertEqual(diagnostics["BTCUSDT"].protection_state, "unprotected")
        self.assertIn("active_position_without_confirmed_algo_protection", diagnostics["BTCUSDT"].reasons)
        self.assertEqual(diagnostics["ETHUSDT"].urgency, "high")
        self.assertEqual(diagnostics["ETHUSDT"].protection_state, "protected")
        self.assertIn("hold_time_expired", diagnostics["ETHUSDT"].reasons)


class PositionAdjustmentExecuteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.sqlite"
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.store = EventStore(self.connection)
        self.store.insert_artifact(
            "order_intents",
            occurred_at="2026-06-20T03:43:09Z",
            source="execution.live",
            symbol="BTCUSDT",
            ref_id="order_intent:BTCUSDT:2026-06-20T03:43:09Z",
            payload={
                "status": "submitted",
                "intent": {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.2,
                    "entry_price": 100,
                    "stop_price": 96,
                    "target_price": 108,
                    "leverage": 5,
                    "metadata": {"hold_time_minutes": 100000},
                },
            },
            event_type="order_intent",
        )

    def tearDown(self):
        self.connection.close()
        self.tmp.cleanup()

    def config(self):
        return load_config(
            env={
                "BFA_MODE": "live",
                "BFA_POSITION_MODE": "hedge",
                "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
            }
        )

    def exchange_info(self):
        import json

        return json.loads(EXCHANGE_INFO.read_text(encoding="utf-8"))

    def test_requires_confirmation_token_before_partial_reduce(self):
        fake = FakeSignedClient(mark_price="107")

        report = build_position_adjustment_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake,
            exchange_info=self.exchange_info(),
        )

        self.assertEqual(report.status, "confirmation_required")
        self.assertTrue(report.expected_confirmation_token.startswith("POSITION-ADJUST-BTCUSDT-"))
        self.assertEqual(fake.orders, [])

    def test_plan_report_blocks_actionable_adjustment_when_filters_missing(self):
        report = build_position_adjustment_plan_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=FakeSignedClient(mark_price="107"),
            exchange_info={"symbols": []},
        )

        self.assertEqual(report.status, "adjustment_plan_blocked")
        self.assertFalse(report.adjustment_allowed)
        self.assertIn("symbol_filters_missing", report.reasons)

    def test_executes_partial_reduce_with_matching_token(self):
        fake = FakeSignedClient(mark_price="107")
        preview = build_position_adjustment_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake,
            exchange_info=self.exchange_info(),
        )

        report = build_position_adjustment_execute_report(
            self.config(),
            db_path=str(self.db_path),
            signed_client=fake,
            confirm_token=preview.expected_confirmation_token,
            exchange_info=self.exchange_info(),
        )

        self.assertEqual(report.status, "position_adjustment_submitted")
        self.assertTrue(report.adjustment_executed)
        self.assertEqual(fake.orders[0]["symbol"], "BTCUSDT")
        self.assertEqual(fake.orders[0]["side"], "SELL")
        self.assertEqual(fake.orders[0]["quantity"], 0.1)
        self.assertEqual(fake.orders[0]["position_side"], "LONG")
        self.assertEqual(fake.cancelled_algo_symbols, [])
        self.assertGreaterEqual(report.executions[0].persisted["order_intent"], 1)

    def test_blocks_when_live_service_is_active(self):
        report = build_position_adjustment_execute_report(
            self.config(),
            db_path=str(self.db_path),
            signed_client=FakeSignedClient(mark_price="107"),
            service_active=True,
        )

        self.assertEqual(report.status, "execution_blocked")
        self.assertIn("live_service_active", report.reasons)

    def test_confirmed_execution_requires_symbol_filters(self):
        fake = FakeSignedClient(mark_price="107")
        preview = build_position_adjustment_execute_report(
            self.config(),
            db_path=str(self.db_path),
            now="2026-06-20T04:00:00Z",
            signed_client=fake,
            exchange_info=self.exchange_info(),
        )

        report = build_position_adjustment_execute_report(
            self.config(),
            db_path=str(self.db_path),
            signed_client=fake,
            confirm_token=preview.expected_confirmation_token,
            exchange_info={"symbols": []},
        )

        self.assertEqual(report.status, "execution_blocked")
        self.assertIn("symbol_filters_missing", report.reasons)


if __name__ == "__main__":
    unittest.main()
