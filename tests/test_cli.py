import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bfa.ai.client import OpenAIResponse
from bfa.cli import main
from bfa.market.models import MarketDataResponse, NormalizedMarketSnapshot
from bfa.narrative.models import NormalizedNarrativeRecord


class CliTests(unittest.TestCase):
    def invoke(
        self,
        *args,
        env=None,
        client_factory=None,
        collector_factory=None,
        narrative_runner_factory=None,
        ai_client_factory=None,
        signed_client_factory=None,
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                list(args),
                env={} if env is None else env,
                client_factory=client_factory,
                collector_factory=collector_factory,
                narrative_runner_factory=narrative_runner_factory,
                ai_client_factory=ai_client_factory,
                signed_client_factory=signed_client_factory,
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

    def test_narrative_collect_uses_injected_fake_runner_and_writes_jsonl(self):
        class FakeRunner:
            def collect_to_jsonl(self, output, *, append=False):
                record = NormalizedNarrativeRecord(
                    source="binance_square",
                    source_id="square-1",
                    author="poster",
                    symbol_mentions=["BTCUSDT"],
                    text="BTCUSDT hot narrative",
                    url=None,
                    published_at="2026-06-19T09:00:00Z",
                    collected_at="2026-06-19T09:01:00Z",
                    engagement={},
                    raw={},
                    quality_flags=[],
                )
                Path(output).write_text(json.dumps(record.to_dict()) + "\n", encoding="utf-8")
                return [record], 1

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "narrative.jsonl"
            code, stdout, stderr = self.invoke(
                "narrative",
                "collect",
                "--env-file",
                ".env.example",
                "--output",
                str(output_path),
                narrative_runner_factory=lambda _config: FakeRunner(),
            )

            lines = output_path.read_text(encoding="utf-8").splitlines()

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["record_count"], 1)
        self.assertEqual(payload["written"], 1)
        self.assertEqual(payload["sources"], ["binance_square"])
        self.assertEqual(payload["symbols"], ["BTCUSDT"])
        self.assertEqual(len(lines), 1)
        self.assertNotIn("SQUARE_COOKIE_FILE", stdout)

    def test_event_store_init_creates_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "agent.sqlite"
            code, stdout, stderr = self.invoke(
                "event-store",
                "init",
                "--env-file",
                ".env.example",
                "--db",
                str(db_path),
            )

            payload = json.loads(stdout)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["initialized"])
        self.assertEqual(payload["db"], str(db_path))

    def test_event_store_report_prints_empty_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "agent.sqlite"
            code, stdout, stderr = self.invoke(
                "event-store",
                "report",
                "--env-file",
                ".env.example",
                "--db",
                str(db_path),
            )

            payload = json.loads(stdout)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["report"]["trade_count"], 0)
        self.assertEqual(payload["report"]["reason_codes"], {})

    def test_strategy_candidates_prints_ranked_candidates(self):
        replay_path = Path("tests") / "fixtures" / "strategy" / "replay_packet.json"
        code, stdout, stderr = self.invoke(
            "strategy",
            "candidates",
            "--env-file",
            ".env.example",
            "--replay",
            str(replay_path),
            "--generated-at",
            "2026-06-19T09:30:00Z",
        )

        payload = json.loads(stdout)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["candidates"][0]["symbol"], "BTCUSDT")
        self.assertGreaterEqual(len(payload["rejected"]), 1)
        self.assertEqual(payload["persisted"], 0)

    def test_strategy_candidates_can_persist_to_db(self):
        replay_path = Path("tests") / "fixtures" / "strategy" / "replay_packet.json"
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "agent.sqlite"
            code, stdout, stderr = self.invoke(
                "strategy",
                "candidates",
                "--env-file",
                ".env.example",
                "--replay",
                str(replay_path),
                "--generated-at",
                "2026-06-19T09:30:00Z",
                "--db",
                str(db_path),
            )

        payload = json.loads(stdout)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["persisted"], 1)

    def test_ai_decide_uses_injected_fake_client_and_persists(self):
        class FakeAiClient:
            def create_decision(self, context, *, instructions, schema):
                return OpenAIResponse(
                    response_id="resp_1",
                    request_payload={"model": "fake", "context": context, "schema": schema},
                    raw_response={
                        "id": "resp_1",
                        "output_text": json.dumps(
                            {
                                "decision": "trade",
                                "side": "long",
                                "confidence": 0.7,
                                "entry_price": 100.0,
                                "stop_price": 96.0,
                                "target_price": 108.0,
                                "notional_usdt": 20.0,
                                "hold_time_minutes": 30,
                                "reasons": ["narrative and market confirmation"],
                            }
                        ),
                    },
                    output_text=json.dumps(
                        {
                            "decision": "trade",
                            "side": "long",
                            "confidence": 0.7,
                            "entry_price": 100.0,
                            "stop_price": 96.0,
                            "target_price": 108.0,
                            "notional_usdt": 20.0,
                            "hold_time_minutes": 30,
                            "reasons": ["narrative and market confirmation"],
                        }
                    ),
                    response_headers={},
                )

        secret = "synthetic-openai-key-abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate_path = tmp_path / "candidate.json"
            journal_path = tmp_path / "ai.jsonl"
            db_path = tmp_path / "agent.sqlite"
            candidate_path.write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "score": 42,
                        "reason_codes": ["narrative_heat", "price_momentum"],
                        "source_event_ids": [1],
                        "market_event_ids": [2],
                        "features": {"quote_volume": 5_000_000},
                    }
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "ai",
                "decide",
                "--candidate",
                str(candidate_path),
                "--decided-at",
                "2026-06-19T10:00:00Z",
                "--journal",
                str(journal_path),
                "--db",
                str(db_path),
                env={
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": secret,
                    "OPENAI_MODEL": "gpt-5.4",
                },
                ai_client_factory=lambda _config: FakeAiClient(),
            )

            journal_text = journal_path.read_text(encoding="utf-8")

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["decision"]["side"], "long")
        self.assertTrue(payload["journaled"])
        self.assertEqual(payload["persisted"], 1)
        self.assertNotIn(secret, stdout + stderr + journal_text)

    def test_execution_run_dry_run_persists_intent_without_signed_client_calls(self):
        class FakeSignedClient:
            def __init__(self):
                self.calls = []

            def new_order(self, **kwargs):
                self.calls.append(("new_order", kwargs))
                return {"orderId": 1}

        fake_client = FakeSignedClient()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            decision_path = tmp_path / "decision.json"
            db_path = tmp_path / "agent.sqlite"
            decision_path.write_text(
                json.dumps(
                    {
                        "accepted": True,
                        "decision": {
                            "decision": "trade",
                            "side": "long",
                            "confidence": 0.7,
                            "entry_price": 100.0,
                            "stop_price": 96.0,
                            "target_price": 108.0,
                            "notional_usdt": 20.0,
                            "hold_time_minutes": 30,
                            "reasons": ["narrative and market confirmation"],
                        },
                        "validation_errors": [],
                    }
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "execution",
                "run",
                "--decision",
                str(decision_path),
                "--symbol",
                "BTCUSDT",
                "--decided-at",
                "2026-06-20T10:00:00Z",
                "--exchange-info",
                str(Path("tests") / "fixtures" / "binance_market" / "exchange_info.json"),
                "--db",
                str(db_path),
                signed_client_factory=lambda _config: fake_client,
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "dry_run")
        self.assertFalse(payload["submitted"])
        self.assertEqual(payload["persisted"]["order_intent"], 1)
        self.assertEqual(fake_client.calls, [])

    def test_execution_run_live_missing_credentials_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            decision_path = Path(tmp) / "decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "accepted": True,
                        "decision": {
                            "decision": "trade",
                            "side": "long",
                            "confidence": 0.7,
                            "entry_price": 100.0,
                            "stop_price": 96.0,
                            "target_price": 108.0,
                            "notional_usdt": 20.0,
                            "hold_time_minutes": 30,
                            "reasons": ["narrative and market confirmation"],
                        },
                        "validation_errors": [],
                    }
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "execution",
                "run",
                "--decision",
                str(decision_path),
                "--symbol",
                "BTCUSDT",
                "--decided-at",
                "2026-06-20T10:00:00Z",
                env={"BFA_MODE": "live"},
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "rejected")
        self.assertIn("missing_binance_credentials", payload["risk"]["reason_codes"])


if __name__ == "__main__":
    unittest.main()
