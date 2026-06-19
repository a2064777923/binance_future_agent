import unittest
from pathlib import Path
import tempfile

from bfa.config import load_config
import bfa.ops.live_status as live_status_module
from bfa.ops.live_status import build_live_status_report


class FakeSignedClient:
    def __init__(self):
        self.calls = []

    def account(self):
        self.calls.append("account")
        return {"canTrade": True, "totalWalletBalance": "100", "availableBalance": "98"}

    def position_risk(self):
        self.calls.append("position_risk")
        return [{"symbol": "SOLUSDT", "positionAmt": "0.1"}]

    def open_orders(self):
        self.calls.append("open_orders")
        return [{"symbol": "SOLUSDT", "clientOrderId": "bfa-solusdt", "status": "NEW"}]


class LiveStatusBinanceTests(unittest.TestCase):
    def test_live_status_can_include_read_only_binance_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(
                {
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "BFA_MODE": "live",
                    "BINANCE_API_KEY": "synthetic-binance-key",
                    "BINANCE_API_SECRET": "synthetic-binance-secret",
                }
            )
            original = live_status_module.BinanceFuturesSignedClient
            try:
                live_status_module.BinanceFuturesSignedClient = lambda **_kwargs: FakeSignedClient()  # type: ignore[assignment]
                report = build_live_status_report(config, check_binance=True)
            finally:
                live_status_module.BinanceFuturesSignedClient = original

        payload = report.to_dict()
        self.assertEqual(payload["exchange_evidence"]["account"]["can_trade"], True)
        self.assertEqual(len(payload["exchange_evidence"]["positions"]), 1)
        self.assertEqual(len(payload["exchange_evidence"]["open_orders"]), 1)


if __name__ == "__main__":
    unittest.main()
