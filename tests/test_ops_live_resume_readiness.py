import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bfa.cli import main
from bfa.config import load_config
from bfa.event_store.migrations import connect
from bfa.event_store.store import EventStore
from bfa.ops.live_resume_readiness import (
    build_live_resume_readiness_report,
    build_matrix_readiness_report,
)


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


class LiveResumeReadinessTests(unittest.TestCase):
    def test_reports_ready_when_matrix_paper_server_exchange_and_profile_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db = _paper_db(root, [0.2, -0.04, 0.18])
            matrix = _matrix_report(root)

            report = build_live_resume_readiness_report(
                _config(root),
                db_path=str(db),
                matrix_report_path=str(matrix),
                min_outcomes=3,
                min_win_rate=0.5,
                min_profit_factor=1.1,
                check_systemd=False,
                server_state_overrides={
                    "paper.timer": "active",
                    "live.timer": "inactive",
                    "live.service": "inactive",
                },
                signed_client=FakeSignedClient(),
                require_operator_confirmation=False,
            )

        payload = report.to_dict()
        self.assertEqual(report.status, "live_resume_ready")
        self.assertTrue(report.live_resume_allowed)
        self.assertEqual(payload["reasons"]["matrix"], [])
        self.assertEqual(payload["reasons"]["strategy_evidence"], [])
        self.assertEqual(payload["reasons"]["server_state"], [])
        self.assertEqual(payload["reasons"]["exchange_state"], [])
        self.assertEqual(payload["reasons"]["risk_profile"], [])
        self.assertFalse(payload["read_only"]["places_orders"])
        self.assertFalse(payload["read_only"]["applies_risk_profiles"])

    def test_manual_exchange_exposure_is_separate_from_agent_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db = _paper_db(root, [0.2, -0.04, 0.18])
            matrix = _matrix_report(root)

            report = build_live_resume_readiness_report(
                _config(root),
                db_path=str(db),
                matrix_report_path=str(matrix),
                min_outcomes=3,
                min_win_rate=0.5,
                min_profit_factor=1.1,
                check_systemd=False,
                server_state_overrides={
                    "paper.timer": "active",
                    "live.timer": "inactive",
                    "live.service": "inactive",
                },
                signed_client=FakeSignedClient(
                    positions=[
                        {
                            "symbol": "ETHUSDT",
                            "positionAmt": "0.01",
                            "positionSide": "LONG",
                            "notional": "35",
                            "initialMargin": "3.5",
                            "leverage": "10",
                        }
                    ]
                ),
                manual_exposure_symbols=["ETHUSDT"],
                require_operator_confirmation=False,
            )

        payload = report.to_dict()
        self.assertEqual(report.status, "live_resume_blocked")
        self.assertFalse(report.live_resume_allowed)
        self.assertEqual(payload["exchange_review"]["manual_or_unattributed_symbols"], ["ETHUSDT"])
        self.assertEqual(payload["exchange_review"]["agent_managed_symbols"], [])
        self.assertFalse(payload["exchange_review"]["manual_exposure_is_agent_evidence"])
        self.assertIn(
            "manual_or_unattributed_exchange_exposure_present",
            payload["reasons"]["exchange_state"],
        )

    def test_matrix_suite_mixed_verdict_blocks_live_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            suite = root / "matrix-suite.json"
            suite.write_text(
                json.dumps(
                    {
                        "schema": "bfa_hot_backtest_matrix_suite_v1",
                        "matrices": [{"preset": "broad", "promotion": {"variants": {}}}],
                        "promotion": {
                            "overall": "mixed_candidate_collect_more_data",
                            "variants": {
                                "quant_setup_selective": {
                                    "matrix_count": 3,
                                    "candidate_matrix_count": 1,
                                    "mixed_matrix_count": 2,
                                    "total_net_pnl_usdt": 0.8,
                                    "worst_drawdown_usdt": 1.2,
                                    "verdict": "mixed_candidate_collect_more_data",
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = build_matrix_readiness_report(
                str(suite),
                variant="quant_setup_selective",
                scope="all-intervals",
                intervals=None,
                min_trade_count=5,
                min_positive_window_rate=0.5,
                max_worst_drawdown_usdt=None,
            )

        self.assertFalse(report.live_resume_allowed)
        self.assertIn("suite_variant_not_promoted", report.reasons)

    def test_cli_live_resume_readiness_exits_zero_only_when_all_gates_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db = _paper_db(root, [0.2, -0.04, 0.18])
            matrix = _matrix_report(root)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "ops",
                        "live-resume-readiness",
                        "--db",
                        str(db),
                        "--matrix-report",
                        str(matrix),
                        "--min-outcomes",
                        "3",
                        "--no-systemd-check",
                        "--paper-timer-state",
                        "active",
                        "--live-timer-state",
                        "inactive",
                        "--live-service-state",
                        "inactive",
                        "--no-operator-confirmation-required",
                    ],
                    env=_env(root),
                    signed_client_factory=lambda _config: FakeSignedClient(),
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(payload["schema"], "bfa_live_resume_readiness_v1")
        self.assertTrue(payload["live_resume_allowed"])


def _config(root: Path):
    return load_config(_env(root))


def _env(root: Path):
    return {
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
        "BFA_FORWARD_PAPER_GUARD_MIN_TOTAL_OUTCOMES": "30",
        "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
        "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
    }


def _paper_db(root: Path, pnls: list[float]) -> Path:
    db = root / "agent.sqlite"
    connection = connect(db)
    try:
        store = EventStore(connection)
        for index, pnl in enumerate(pnls):
            symbol = "SOLUSDT" if index % 2 == 0 else "HYPEUSDT"
            signal_id = store.insert_artifact(
                "paper_signals",
                occurred_at=f"2026-06-20T00:0{index}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_signal:{index}",
                event_type="paper_signal",
                payload={
                    "schema": "bfa_paper_signal_v1",
                    "symbol": symbol,
                    "interval": "5m",
                    "variant": "quant_setup_selective",
                    "opened_at": f"2026-06-20T00:0{index}:00Z",
                    "expiry_time": f"2026-06-20T00:2{index}:00Z",
                    "side": "long",
                    "entry_price": 100.0,
                    "stop_price": 98.0,
                    "target_price": 104.0,
                    "notional_usdt": 12.0,
                    "hold_bars": 4,
                    "status": "open",
                    "setup": {
                        "side": "long",
                        "reasons": ["quant_long_setup"],
                        "warnings": [],
                        "factor_scores": [],
                    },
                },
            )
            store.insert_artifact(
                "paper_outcomes",
                occurred_at=f"2026-06-20T01:0{index}:00Z",
                source="test",
                symbol=symbol,
                ref_id=f"paper_outcome:{signal_id}",
                event_type="paper_outcome",
                payload={
                    "schema": "bfa_paper_outcome_v1",
                    "signal_event_id": signal_id,
                    "symbol": symbol,
                    "interval": "5m",
                    "variant": "quant_setup_selective",
                    "opened_at": f"2026-06-20T00:0{index}:00Z",
                    "closed_at": f"2026-06-20T01:0{index}:00Z",
                    "side": "long",
                    "entry_price": 100.0,
                    "exit_price": 104.0 if pnl > 0 else 98.0,
                    "quantity": 0.12,
                    "notional_usdt": 12.0,
                    "gross_pnl_usdt": pnl,
                    "fees_usdt": 0.0,
                    "slippage_usdt": 0.0,
                    "net_pnl_usdt": pnl,
                    "exit_reason": "take_profit" if pnl > 0 else "stop_loss",
                },
            )
    finally:
        connection.close()
    return db


def _matrix_report(root: Path) -> Path:
    path = root / "matrix.json"
    path.write_text(
        json.dumps(
            {
                "schema": "bfa_hot_backtest_matrix_v1",
                "promotion": {
                    "overall": "candidate_for_forward_paper",
                    "cells": [
                        {
                            "interval": "5m",
                            "variant": "quant_setup_selective",
                            "verdict": "candidate_for_forward_paper",
                            "trade_count": 12,
                            "net_pnl_usdt": 1.25,
                            "positive_window_rate": 1.0,
                            "worst_drawdown_usdt": 0.2,
                            "max_daily_loss_usdt": 1.5,
                        }
                    ],
                    "variants": {
                        "quant_setup_selective": {
                            "interval_count": 1,
                            "candidate_interval_count": 1,
                            "total_net_pnl_usdt": 1.25,
                            "worst_drawdown_usdt": 0.2,
                            "verdict": "candidate_for_forward_paper",
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
