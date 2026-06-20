import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.ops.manual_loss import build_manual_loss_incident, record_manual_loss_incident


class ManualLossTests(unittest.TestCase):
    def test_records_manual_loss_incident_as_risk_state_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db = root / "agent.sqlite"
            incident = build_manual_loss_incident(
                symbol="solusdt",
                side="long",
                leverage=20,
                entry_price=100,
                liquidation_price=95,
                stop_loss_status="none",
                trigger_reason="chased breakout",
                lessons=["no stop", "size too high"],
                occurred_at="2026-06-21T01:00:00Z",
            )
            report = record_manual_loss_incident(_config(root), db_path=str(db), incident=incident)

            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            try:
                row = connection.execute(
                    "SELECT event_type, symbol, payload_json FROM events WHERE id = ?",
                    (report.event_id,),
                ).fetchone()
            finally:
                connection.close()

        payload = json.loads(row["payload_json"])
        self.assertTrue(report.recorded)
        self.assertEqual(row["event_type"], "manual_loss_incident")
        self.assertEqual(row["symbol"], "SOLUSDT")
        self.assertEqual(payload["schema"], "bfa_manual_loss_incident_v1")
        self.assertEqual(payload["liquidation_price"], 95.0)
        self.assertFalse(report.to_dict()["read_only_exchange"]["places_orders"])

    def test_requires_exit_or_liquidation_price(self):
        with self.assertRaises(ValueError):
            build_manual_loss_incident(
                symbol="SOLUSDT",
                side="long",
                leverage=10,
                entry_price=100,
                occurred_at="2026-06-21T01:00:00Z",
            )


def _config(root: Path):
    return load_config(
        {
            "BFA_MODE": "live",
            "BFA_DB_PATH": str(root / "agent.sqlite"),
            "BFA_RUNTIME_DIR": str(root / "runtime"),
        }
    )


if __name__ == "__main__":
    unittest.main()
