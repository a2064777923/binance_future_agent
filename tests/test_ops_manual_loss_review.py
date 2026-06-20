import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.ops.manual_loss import build_manual_loss_incident, record_manual_loss_incident
from bfa.ops.manual_loss_review import build_manual_loss_review_report
from bfa.strategy.paper_guard import ForwardPaperGuardConfig
from tests.test_strategy_paper_guard import outcome_payload, signal_payload


class ManualLossReviewTests(unittest.TestCase):
    def test_reports_no_manual_loss_incidents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = build_manual_loss_review_report(
                _config(root),
                db_path=str(root / "agent.sqlite"),
                include_paper_guard=False,
            )

        self.assertEqual(report.status, "no_manual_loss_incidents")
        self.assertEqual(report.incident_count, 0)
        self.assertEqual(report.summary["not_caught_by_current_guards"], 0)

    def test_high_leverage_missing_stop_manual_loss_would_be_blocked_by_risk_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "agent.sqlite"
            record_manual_loss_incident(
                _config(root, BFA_MAX_LEVERAGE="10"),
                db_path=str(db),
                incident=build_manual_loss_incident(
                    symbol="SOLUSDT",
                    side="long",
                    leverage=20,
                    entry_price=100,
                    liquidation_price=99,
                    stop_loss_status="none",
                    trigger_reason="manual chase",
                    lessons=["no stop", "oversized"],
                    occurred_at="2026-06-21T01:00:00Z",
                ),
            )

            report = build_manual_loss_review_report(
                _config(root, BFA_MAX_LEVERAGE="10"),
                db_path=str(db),
                include_paper_guard=False,
            )

        payload = report.to_dict()
        item = payload["items"][0]
        self.assertEqual(report.status, "review_ready")
        self.assertEqual(item["guard_outcome"], "would_block_by_risk_guard")
        self.assertIn("liquidation_distance_within_2_percent", item["warnings"])
        self.assertTrue(any(check["rule"] == "max_leverage" and check["status"] == "blocked" for check in item["risk_checks"]))
        self.assertTrue(
            any(check["rule"] == "protective_stop_required" and check["status"] == "blocked" for check in item["risk_checks"])
        )
        self.assertFalse(payload["read_only_exchange"]["mutates_exchange_state"])

    def test_paper_guard_blocked_symbol_is_reported_for_manual_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "agent.sqlite"
            record_manual_loss_incident(
                _config(root, BFA_MAX_LEVERAGE="10"),
                db_path=str(db),
                incident=build_manual_loss_incident(
                    symbol="BTWUSDT",
                    side="short",
                    leverage=5,
                    entry_price=0.2,
                    exit_price=0.21,
                    stop_loss_status="configured",
                    trigger_reason="manual short",
                    occurred_at="2026-06-21T01:00:00Z",
                ),
            )
            _seed_losing_paper_symbol(db, "BTWUSDT", side="short")

            report = build_manual_loss_review_report(
                _config(root, BFA_MAX_LEVERAGE="10"),
                db_path=str(db),
                guard_config=ForwardPaperGuardConfig(
                    min_total_outcomes=3,
                    min_symbol_outcomes=3,
                    symbol_min_loss_usdt=0.5,
                    symbol_max_win_rate=0.1,
                    min_side_outcomes=99,
                    min_factor_outcomes=99,
                ),
            )

        item = report.to_dict()["items"][0]
        self.assertEqual(item["guard_outcome"], "would_block_by_paper_guard")
        self.assertTrue(
            any(check["rule"] == "forward_paper_symbol_block" and check["status"] == "blocked" for check in item["paper_guard_checks"])
        )

    def test_configured_stop_within_limits_can_be_not_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "agent.sqlite"
            record_manual_loss_incident(
                _config(root, BFA_MAX_LEVERAGE="10"),
                db_path=str(db),
                incident=build_manual_loss_incident(
                    symbol="XRPUSDT",
                    side="long",
                    leverage=5,
                    entry_price=2,
                    exit_price=1.98,
                    stop_loss_status="configured",
                    occurred_at="2026-06-21T01:00:00Z",
                ),
            )

            report = build_manual_loss_review_report(
                _config(root, BFA_MAX_LEVERAGE="10"),
                db_path=str(db),
                include_paper_guard=False,
            )

        self.assertEqual(report.items[0].guard_outcome, "not_caught_by_current_guards")


def _seed_losing_paper_symbol(db: Path, symbol: str, *, side: str):
    connection = connect(db)
    try:
        store = EventStore(connection)
        for index, pnl in enumerate([-0.3, -0.25, -0.2]):
            signal_id = store.insert_artifact(
                "paper_signals",
                occurred_at=f"2026-06-20T00:0{index}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_signal:{index}",
                event_type="paper_signal",
                payload=signal_payload(symbol, side=side),
            )
            store.insert_artifact(
                "paper_outcomes",
                occurred_at=f"2026-06-20T01:0{index}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_outcome:{signal_id}",
                event_type="paper_outcome",
                payload=outcome_payload(signal_id, symbol, pnl, side=side),
            )
    finally:
        connection.close()


def _config(root: Path, **overrides):
    env = {
        "BFA_MODE": "live",
        "BFA_DB_PATH": str(root / "agent.sqlite"),
        "BFA_RUNTIME_DIR": str(root / "runtime"),
        "BFA_MAX_LEVERAGE": "10",
    }
    env.update(overrides)
    return load_config(env)


if __name__ == "__main__":
    unittest.main()
