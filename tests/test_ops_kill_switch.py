import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.ops.kill_switch import build_kill_switch_clearance_report


class FakeClient:
    def __init__(self, *, positions, algo_orders):
        self._positions = positions
        self._algo_orders = algo_orders

    def position_risk(self, symbol=None):
        return self._positions

    def open_algo_orders(self, symbol=None):
        return self._algo_orders


class KillSwitchClearanceTests(unittest.TestCase):
    def config(self, path: Path):
        return load_config(
            {
                "BFA_MODE": "live",
                "BFA_KILL_SWITCH_FILE": str(path),
                "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
            }
        )

    def test_execute_archives_kill_switch_when_all_positions_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "KILL_SWITCH"
            path.write_text("protective order failure\n", encoding="utf-8")
            client = FakeClient(
                positions=[{"symbol": "BTCUSDT", "positionAmt": "0.2", "positionSide": "LONG"}],
                algo_orders=[
                    {
                        "symbol": "BTCUSDT",
                        "positionSide": "LONG",
                        "side": "SELL",
                        "orderType": "STOP_MARKET",
                        "closePosition": True,
                    },
                    {
                        "symbol": "BTCUSDT",
                        "positionSide": "LONG",
                        "side": "SELL",
                        "orderType": "TAKE_PROFIT_MARKET",
                        "closePosition": True,
                    },
                ],
            )

            report = build_kill_switch_clearance_report(
                self.config(path),
                signed_client=client,
                execute=True,
                now_epoch=1782240000,
            )

            self.assertTrue(report.eligible)
            self.assertTrue(report.executed)
            self.assertFalse(path.exists())
            self.assertIsNotNone(report.archived_path)
            self.assertTrue(Path(report.archived_path).exists())

    def test_blocks_clearance_when_position_missing_take_profit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "KILL_SWITCH"
            path.write_text("protective order failure\n", encoding="utf-8")
            client = FakeClient(
                positions=[{"symbol": "BTCUSDT", "positionAmt": "-0.2", "positionSide": "SHORT"}],
                algo_orders=[
                    {
                        "symbol": "BTCUSDT",
                        "positionSide": "SHORT",
                        "side": "BUY",
                        "orderType": "STOP_MARKET",
                        "closePosition": True,
                    }
                ],
            )

            report = build_kill_switch_clearance_report(self.config(path), signed_client=client, execute=True)

            self.assertFalse(report.eligible)
            self.assertFalse(report.executed)
            self.assertTrue(path.exists())
            self.assertIn("unprotected_open_positions", report.reason_codes)


if __name__ == "__main__":
    unittest.main()
