import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bfa.cli import main
from bfa.market.models import MarketDataResponse, NormalizedMarketSnapshot


class CliTests(unittest.TestCase):
    def invoke(self, *args, env=None, client_factory=None, collector_factory=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                list(args),
                env={} if env is None else env,
                client_factory=client_factory,
                collector_factory=collector_factory,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_config_check_dry_run_example_exits_zero(self):
        code, stdout, stderr = self.invoke("config-check", "--env-file", ".env.example")
        payload = json.loads(stdout)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["errors"], [])

    def test_invalid_live_config_exits_nonzero_with_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "env"
            env_path.write_text("BFA_MODE=live\n", encoding="utf-8")

            code, stdout, _stderr = self.invoke("config-check", "--env-file", str(env_path))

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertFalse(payload["valid"])
        self.assertIn("BINANCE_API_KEY is required for live mode", payload["errors"])
        self.assertIn("BINANCE_API_SECRET is required for live mode", payload["errors"])

    def test_config_check_redacts_synthetic_sensitive_values(self):
        synthetic_key = "synthetic-binance-key-abcdef"
        synthetic_secret = "synthetic-binance-secret-abcdef"
        synthetic_openai = "synthetic-openai-key-abcdef"

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "env"
            env_path.write_text(
                "\n".join(
                    [
                        "BFA_MODE=live",
                        "BFA_OPENAI_ENABLED=true",
                        f"BINANCE_API_KEY={synthetic_key}",
                        f"BINANCE_API_SECRET={synthetic_secret}",
                        f"OPENAI_API_KEY={synthetic_openai}",
                    ]
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke("config-check", "--env-file", str(env_path))

        combined = stdout + stderr
        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertTrue(payload["valid"])
        self.assertNotIn(synthetic_key, combined)
        self.assertNotIn(synthetic_secret, combined)
        self.assertNotIn(synthetic_openai, combined)
        self.assertIn("redacted", payload)

    def test_config_check_does_not_print_unrelated_environment_values(self):
        code, stdout, stderr = self.invoke(
            "config-check",
            env={"BFA_MODE": "dry_run", "UNRELATED_PUBLIC_PATH": "do-not-print-me"},
        )

        self.assertEqual(code, 0)
        self.assertNotIn("UNRELATED_PUBLIC_PATH", stdout + stderr)
        self.assertNotIn("do-not-print-me", stdout + stderr)

    def test_market_data_exchange_info_uses_injected_fake_client(self):
        class FakeClient:
            def exchange_info(self):
                return MarketDataResponse(
                    endpoint="/fapi/v1/exchangeInfo",
                    params={},
                    payload={"serverTime": 1700000000000, "symbols": []},
                    headers={"X-MBX-USED-WEIGHT-1M": "1"},
                )

        code, stdout, stderr = self.invoke(
            "market-data",
            "exchange-info",
            "--env-file",
            ".env.example",
            client_factory=lambda _config: FakeClient(),
        )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["endpoint"], "/fapi/v1/exchangeInfo")
        self.assertEqual(payload["request_weight"], "1")
        self.assertEqual(payload["payload"]["symbols"], [])
        self.assertNotIn("BINANCE_API_KEY", stdout)

    def test_market_data_snapshot_uses_injected_fake_collector_and_writes_jsonl(self):
        class FakeCollector:
            def __init__(self):
                self.symbols = ["BTCUSDT"]

            def collect_rest_snapshots(self):
                return [
                    NormalizedMarketSnapshot(
                        source="binance_usdm",
                        event_type="ticker_24h",
                        symbol="BTCUSDT",
                        event_time=1700000000000,
                        received_at="now",
                        payload={"last_price": "70100.00"},
                    )
                ]

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "market.jsonl"
            code, stdout, stderr = self.invoke(
                "market-data",
                "snapshot",
                "--env-file",
                ".env.example",
                "--output",
                str(output_path),
                collector_factory=lambda _config, _client: FakeCollector(),
            )

            lines = output_path.read_text(encoding="utf-8").splitlines()

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["written"], 1)
        self.assertEqual(payload["symbols"], ["BTCUSDT"])
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["event_type"], "ticker_24h")


if __name__ == "__main__":
    unittest.main()
