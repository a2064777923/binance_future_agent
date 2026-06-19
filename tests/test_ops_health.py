import json
import tempfile
import unittest
from pathlib import Path

from bfa.config import load_config
from bfa.market.models import MarketDataResponse
from bfa.ops.health import run_health_checks


class FakeMarketClient:
    def __init__(self):
        self.calls = []

    def exchange_info(self):
        self.calls.append("exchange_info")
        return MarketDataResponse(
            endpoint="/fapi/v1/exchangeInfo",
            params={},
            payload={"symbols": []},
            headers={},
        )


class FakeAiClient:
    def __init__(self):
        self.calls = []

    def create_decision(self, context, *, instructions, schema):
        self.calls.append({"context": context, "instructions": instructions, "schema": schema})
        return object()


class OpsHealthTests(unittest.TestCase):
    def env(self, root: Path, **overrides):
        values = {
            "BFA_MODE": "dry_run",
            "BFA_RUNTIME_DIR": str(root / "runtime"),
            "BFA_LOG_DIR": str(root / "logs"),
            "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
            "BFA_DB_PATH": str(root / "data" / "agent.sqlite"),
            "BFA_KILL_SWITCH_FILE": str(root / "runtime" / "KILL_SWITCH"),
        }
        values.update(overrides)
        return values

    def test_passing_dry_run_health_check_creates_local_dirs_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(self.env(Path(tmp)))

            report = run_health_checks(config, create_dirs=True)

        statuses = {check.name: check.status for check in report.checks}
        self.assertTrue(report.ok)
        self.assertEqual(statuses["config"], "passed")
        self.assertEqual(statuses["runtime_dir"], "passed")
        self.assertEqual(statuses["database"], "passed")
        self.assertEqual(statuses["risk_state"], "passed")
        self.assertEqual(statuses["binance_public"], "skipped")
        self.assertEqual(statuses["openai"], "skipped")

    def test_missing_directory_fails_without_create_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(self.env(Path(tmp)))

            report = run_health_checks(config)

        self.assertFalse(report.ok)
        failed = [check.name for check in report.checks if check.status == "failed"]
        self.assertIn("runtime_dir", failed)
        self.assertIn("database", failed)
        self.assertIn("risk_state", failed)

    def test_invalid_live_config_fails_without_printing_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(self.env(Path(tmp), BFA_MODE="live", OPENAI_API_KEY="synthetic-openai-key"))

            report = run_health_checks(config, create_dirs=True)

        payload = json.dumps(report.to_dict(), sort_keys=True)
        self.assertFalse(report.ok)
        self.assertIn("BINANCE_API_KEY is required for live mode", payload)
        self.assertNotIn("synthetic-openai-key", payload)

    def test_network_checks_use_injected_fake_clients(self):
        market = FakeMarketClient()
        ai = FakeAiClient()
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(
                self.env(
                    Path(tmp),
                    BFA_OPENAI_ENABLED="true",
                    OPENAI_API_KEY="synthetic-openai-key",
                )
            )

            report = run_health_checks(
                config,
                create_dirs=True,
                check_binance=True,
                check_openai=True,
                market_client=market,
                ai_client=ai,
            )

        statuses = {check.name: check.status for check in report.checks}
        self.assertTrue(report.ok)
        self.assertEqual(statuses["binance_public"], "passed")
        self.assertEqual(statuses["openai"], "passed")
        self.assertEqual(market.calls, ["exchange_info"])
        self.assertEqual(len(ai.calls), 1)


if __name__ == "__main__":
    unittest.main()
