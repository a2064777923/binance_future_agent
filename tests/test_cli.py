import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.ai.client import OpenAIResponse
from bfa.cli import main
from bfa.event_store.store import EventStore
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
        self.assertGreaterEqual(payload["persisted"]["order_intent"], 1)
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

    def test_agent_run_once_executes_dry_run_chain_with_injected_fakes(self):
        class FakeMarketClient:
            def exchange_info(self):
                return MarketDataResponse(
                    endpoint="/fapi/v1/exchangeInfo",
                    params={},
                    payload=json.loads(
                        (Path("tests") / "fixtures" / "binance_market" / "exchange_info.json").read_text(
                            encoding="utf-8"
                        )
                    ),
                )

        class FakeCollector:
            def collect_rest_snapshots(self):
                return [
                    NormalizedMarketSnapshot(
                        source="binance_usdm",
                        event_type="ticker_24h",
                        symbol="BTCUSDT",
                        event_time=1700000000000,
                        received_at="2026-06-20T10:00:00Z",
                        payload={"price_change_percent": "5.2", "quote_volume": "12000000"},
                    ),
                    NormalizedMarketSnapshot(
                        source="binance_usdm",
                        event_type="kline",
                        symbol="BTCUSDT",
                        event_time=1700000000001,
                        received_at="2026-06-20T10:00:00Z",
                        payload={"high": "101", "low": "99", "close": "100"},
                    ),
                    NormalizedMarketSnapshot(
                        source="binance_usdm",
                        event_type="funding_rate",
                        symbol="BTCUSDT",
                        event_time=1700000000002,
                        received_at="2026-06-20T10:00:00Z",
                        payload={"funding_rate": "0.0001"},
                    ),
                    NormalizedMarketSnapshot(
                        source="binance_usdm",
                        event_type="open_interest_hist",
                        symbol="BTCUSDT",
                        event_time=1700000000003,
                        received_at="2026-06-20T10:00:00Z",
                        payload={"sum_open_interest_value": "5000000"},
                    ),
                    NormalizedMarketSnapshot(
                        source="binance_usdm",
                        event_type="taker_buy_sell_volume",
                        symbol="BTCUSDT",
                        event_time=1700000000004,
                        received_at="2026-06-20T10:00:00Z",
                        payload={"buy_sell_ratio": "1.2"},
                    ),
                ]

        class FakeNarrativeRunner:
            def collect(self):
                return [
                    NormalizedNarrativeRecord(
                        source="binance_square",
                        source_id="square-1",
                        author="poster",
                        symbol_mentions=["BTCUSDT"],
                        text="BTCUSDT breakout narrative",
                        url=None,
                        published_at="2026-06-20T09:58:00Z",
                        collected_at="2026-06-20T10:00:00Z",
                        engagement={"likes": 50, "comments": 5},
                        raw={},
                        quality_flags=[],
                    )
                ]

        class FakeAiClient:
            def create_decision(self, context, *, instructions, schema):
                payload = {
                    "decision": "trade",
                    "side": "long",
                    "confidence": 0.74,
                    "entry_price": 100.0,
                    "stop_price": 96.0,
                    "target_price": 108.0,
                    "notional_usdt": 20.0,
                    "hold_time_minutes": 30,
                    "reasons": ["narrative heat plus market confirmation"],
                }
                return OpenAIResponse(
                    response_id="resp_agent_1",
                    request_payload={"context": context, "schema": schema},
                    raw_response={"id": "resp_agent_1", "output_text": json.dumps(payload)},
                    output_text=json.dumps(payload),
                    response_headers={},
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, stdout, stderr = self.invoke(
                "agent",
                "run-once",
                "--db",
                str(root / "agent.sqlite"),
                "--journal",
                str(root / "ai.jsonl"),
                env={
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                },
                client_factory=lambda _config: FakeMarketClient(),
                collector_factory=lambda _config, _client: FakeCollector(),
                narrative_runner_factory=lambda _config: FakeNarrativeRunner(),
                ai_client_factory=lambda _config: FakeAiClient(),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["selected_symbol"], "BTCUSDT")
        self.assertTrue(payload["ai_accepted"])
        self.assertGreaterEqual(payload["persisted"]["order_intent"], 1)

    def test_ops_health_check_prints_secret_safe_json(self):
        secret = "synthetic-openai-key-abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, stdout, stderr = self.invoke(
                "ops",
                "health-check",
                "--create-dirs",
                env={
                    "BFA_MODE": "dry_run",
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "BFA_LOG_DIR": str(root / "logs"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                    "BFA_DB_PATH": str(root / "data" / "agent.sqlite"),
                    "BFA_KILL_SWITCH_FILE": str(root / "runtime" / "KILL_SWITCH"),
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": secret,
                },
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["ok"])
        self.assertNotIn(secret, stdout)
        self.assertNotEqual(payload["redacted_config"]["OPENAI_API_KEY"], secret)

    def test_ops_health_check_invalid_live_config_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, stdout, stderr = self.invoke(
                "ops",
                "health-check",
                "--create-dirs",
                env={
                    "BFA_MODE": "live",
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "BFA_LOG_DIR": str(root / "logs"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                    "BFA_DB_PATH": str(root / "data" / "agent.sqlite"),
                    "BFA_KILL_SWITCH_FILE": str(root / "runtime" / "KILL_SWITCH"),
                },
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertFalse(payload["ok"])
        self.assertIn("BINANCE_API_KEY is required for live mode", payload["checks"][0]["detail"])

    def test_ops_live_status_prints_event_store_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            store.insert_artifact(
                "candidates",
                occurred_at="2026-06-20T10:00:00Z",
                source="test",
                symbol="SOLUSDT",
                ref_id="candidate-1",
                payload={"symbol": "SOLUSDT"},
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "live-status",
                "--db",
                str(db_path),
                env={
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BFA_DB_PATH": str(db_path),
                },
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["counts"]["candidates"], 1)
        self.assertEqual(payload["latest"]["candidate"]["symbol"], "SOLUSDT")
        self.assertFalse(payload["lva05_complete"])


if __name__ == "__main__":
    unittest.main()
