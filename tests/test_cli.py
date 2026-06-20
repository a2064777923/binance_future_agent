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
from bfa.execution.models import OrderIntent, RiskDecision
from bfa.execution.store import persist_exchange_response, persist_order_intent
from bfa.market.models import MarketDataResponse, NormalizedMarketSnapshot
from bfa.narrative.models import NormalizedNarrativeRecord


def test_kline(open_time, *, open_price="100", high="101", low="99", close="100.5"):
    return [
        open_time,
        open_price,
        high,
        low,
        close,
        "10",
        open_time + 299_999,
        "2000000",
        10,
        "5",
        "1200000",
        "0",
    ]


def decision_from_quant_setup(context, *, fallback_confidence=0.7):
    setup = context.get("quant_setup") or {}
    return {
        "decision": setup.get("decision", "trade"),
        "side": setup.get("side", "long"),
        "confidence": setup.get("confidence", fallback_confidence),
        "entry_price": setup.get("entry_price", 100.0),
        "stop_price": setup.get("stop_price", 96.0),
        "target_price": setup.get("target_price", 108.0),
        "notional_usdt": setup.get("notional_usdt", 20.0),
        "hold_time_minutes": setup.get("hold_time_minutes", 30),
        "reasons": setup.get("reasons", ["narrative and market confirmation"]),
    }


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
            env={"BFA_MARKET_SYMBOLS": "BTCUSDT,ETHUSDT"},
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
                env={"BFA_MARKET_SYMBOLS": "BTCUSDT,ETHUSDT"},
            )

        payload = json.loads(stdout)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["persisted"], 1)

    def test_ai_decide_uses_injected_fake_client_and_persists(self):
        class FakeAiClient:
            def create_decision(self, context, *, instructions, schema):
                payload = decision_from_quant_setup(context)
                return OpenAIResponse(
                    response_id="resp_1",
                    request_payload={"model": "fake", "context": context, "schema": schema},
                    raw_response={"id": "resp_1", "output_text": json.dumps(payload)},
                    output_text=json.dumps(payload),
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
                        "features": {
                            "mention_count": 2,
                            "source_count": 2,
                            "engagement_score": 100,
                            "price_change_percent": 5.0,
                            "quote_volume": 5_000_000,
                            "open_interest_value": 5_000_000,
                            "taker_buy_sell_ratio": 1.2,
                            "funding_rate": -0.0001,
                            "kline_range_mean_percent": 1.2,
                            "kline_momentum_percent": 1.5,
                            "kline_close_position_percent": 75,
                            "reference_price": 100.0,
                            "min_executable_notional": 5.0,
                        },
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
                payload = decision_from_quant_setup(context, fallback_confidence=0.74)
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

    def test_ops_live_status_uses_injected_signed_client_for_binance_evidence(self):
        class FakeSignedClient:
            def account(self):
                return {"availableBalance": "30", "totalWalletBalance": "30"}

            def position_risk(self):
                return []

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()

            code, stdout, stderr = self.invoke(
                "ops",
                "live-status",
                "--check-binance",
                "--db",
                str(db_path),
                env={
                    "BFA_MODE": "live",
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: FakeSignedClient(),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["exchange_evidence"]["account"]["available_balance"], "30")

    def test_ops_trade_trace_reconstructs_decision_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            decided_at = "2026-06-20T10:00:00Z"
            store.insert_artifact(
                "candidates",
                occurred_at=decided_at,
                source="strategy.hot_coin",
                symbol="BTCUSDT",
                ref_id=f"candidate:BTCUSDT:{decided_at}",
                payload={
                    "symbol": "BTCUSDT",
                    "score": 80,
                    "reason_codes": ["price_momentum"],
                    "features": {"reference_price": 100, "taker_buy_sell_ratio": 1.2},
                },
                event_type="candidate",
            )
            store.insert_artifact(
                "trade_setups",
                occurred_at=decided_at,
                source="strategy.quant_setup",
                symbol="BTCUSDT",
                ref_id=f"trade_setup:BTCUSDT:{decided_at}",
                payload={
                    "setup": {
                        "symbol": "BTCUSDT",
                        "decision": "trade",
                        "side": "long",
                        "entry_price": 100,
                        "stop_price": 98.8,
                        "target_price": 102.2,
                        "notional_usdt": 12,
                        "hold_time_minutes": 15,
                        "long_score": 55,
                        "short_score": 18,
                        "edge_score": 37,
                        "regime": "trend_expansion",
                        "risk_reward_ratio": 1.8,
                        "stop_distance_percent": 1.2,
                        "target_distance_percent": 2.16,
                        "price_basis": {
                            "model": "expected_market_entry_structure_stop_target_v1",
                            "support_price": 98.7,
                            "resistance_price": 102.5,
                            "stop_basis": {"anchor": "support_price"},
                            "target_basis": {"anchor": "nearest_structure_with_min_rr"},
                        },
                        "factor_scores": [{"name": "momentum", "weighted_score": 20}],
                        "reasons": ["quant_long_setup"],
                    }
                },
                event_type="trade_setup",
            )
            store.insert_artifact(
                "ai_decisions",
                occurred_at=decided_at,
                source="deepseek.chat_completions",
                symbol="BTCUSDT",
                ref_id=f"ai_decision:BTCUSDT:{decided_at}",
                payload={
                    "validation": {
                        "accepted": True,
                        "decision": {
                            "decision": "trade",
                            "side": "long",
                            "confidence": 0.7,
                            "reasons": ["echo quant setup"],
                        },
                        "validation_errors": [],
                    }
                },
                event_type="ai_decision",
            )
            store.insert_artifact(
                "order_intents",
                occurred_at=decided_at,
                source="execution.dry_run",
                symbol="BTCUSDT",
                ref_id=f"order_intent:BTCUSDT:{decided_at}",
                payload={
                    "status": "dry_run",
                    "intent": {
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "entry_price": 100,
                        "stop_price": 98.8,
                        "target_price": 102.2,
                        "notional_usdt": 12,
                        "decided_at": decided_at,
                    },
                    "risk": {"accepted": True, "reason_codes": ["risk_accepted"]},
                },
                event_type="order_intent",
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "trade-trace",
                "--db",
                str(db_path),
                "--symbol",
                "BTCUSDT",
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["found"])
        self.assertEqual(payload["status"], "trace_ready")
        self.assertEqual([stage["stage"] for stage in payload["decision_flow"]], [
            "candidate",
            "quant_setup",
            "ai_overlay",
            "risk_and_intent",
        ])
        self.assertEqual(payload["decision_flow"][1]["factor_scores"][0]["name"], "momentum")
        self.assertEqual(payload["decision_flow"][1]["regime"], "trend_expansion")
        self.assertEqual(payload["decision_flow"][1]["price_basis"]["stop_basis"]["anchor"], "support_price")
        self.assertEqual(payload["decision_flow"][3]["risk_reasons"], ["risk_accepted"])

    def test_ops_resume_check_requires_exchange_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()

            code, stdout, stderr = self.invoke(
                "ops",
                "resume-check",
                "--skip-binance",
                "--db",
                str(db_path),
                env={
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BFA_DB_PATH": str(db_path),
                },
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertFalse(payload["resume_allowed"])
        self.assertEqual(payload["status"], "keep_paused")
        self.assertIn("exchange_evidence_missing", payload["reasons"])

    def test_ops_risk_change_check_requires_exchange_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()

            code, stdout, stderr = self.invoke(
                "ops",
                "risk-change-check",
                "--skip-binance",
                "--target-leverage",
                "8",
                "--db",
                str(db_path),
                env={
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BFA_DB_PATH": str(db_path),
                    "BFA_MAX_LEVERAGE": "5",
                },
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertFalse(payload["risk_change_allowed"])
        self.assertEqual(payload["status"], "keep_current_profile")
        self.assertEqual(payload["target_leverage"], 8)
        self.assertEqual(payload["current_max_leverage"], 5.0)
        self.assertIn("exchange_evidence_missing", payload["reasons"])

    def test_ops_risk_profile_plan_outputs_8x_dynamic_diff(self):
        code, stdout, stderr = self.invoke(
            "ops",
            "risk-profile-plan",
            "--profile",
            "30u_8x_dynamic",
            env={
                "BFA_MODE": "live",
                "BFA_MAX_LEVERAGE": "5",
                "BFA_MAX_POSITION_NOTIONAL_USDT": "12",
                "BFA_MAX_OPEN_POSITIONS": "1",
                "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
            },
        )

        payload = json.loads(stdout)
        changed = {item["key"]: item["target"] for item in payload["diff"] if item["changed"]}
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["target_leverage"], 8)
        self.assertEqual(changed["BFA_MAX_LEVERAGE"], "8")
        self.assertEqual(changed["BFA_DYNAMIC_POSITION_SIZING_ENABLED"], "true")
        self.assertTrue(payload["confirmation_token"].startswith("RISK-PROFILE-30U_8X_DYNAMIC-"))

    def test_ops_exposure_status_explains_blocked_entry_capacity(self):
        class FakeSignedClient:
            def account(self):
                return {"availableBalance": "27.9", "totalWalletBalance": "30.1"}

            def position_risk(self):
                return [
                    {
                        "symbol": "HYPEUSDT",
                        "positionAmt": "0.16",
                        "positionSide": "LONG",
                        "entryPrice": "70.266",
                        "markPrice": "70.69",
                        "unRealizedProfit": "0.0678",
                    }
                ]

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return [
                    {"symbol": "HYPEUSDT", "positionSide": "LONG"},
                    {"symbol": "HYPEUSDT", "positionSide": "LONG"},
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            intent = OrderIntent(
                symbol="HYPEUSDT",
                side="BUY",
                quantity=0.16,
                notional_usdt=11.24256,
                entry_price=70.266,
                stop_price=69.6,
                target_price=71.5,
                leverage=5,
                mode="live",
                decided_at="2026-06-20T05:26:07Z",
            )
            persist_order_intent(
                store,
                intent=intent,
                status="submitted",
                risk=RiskDecision(True, ["risk_accepted"]),
            )
            persist_exchange_response(
                store,
                intent=intent,
                response={
                    "entry_order": {"orderId": 1},
                    "stop_loss_order": {"algoId": 2},
                    "take_profit_order": {"algoId": 3},
                },
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "exposure-status",
                "--db",
                str(db_path),
                "--hypothetical-symbol",
                "HYPEUSDT",
                "--hypothetical-side",
                "long",
                env={
                    "BFA_MODE": "live",
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BFA_ACCOUNT_CAPITAL_USDT": "30",
                    "BFA_MAX_LEVERAGE": "5",
                    "BFA_MAX_POSITION_NOTIONAL_USDT": "12",
                    "BFA_MAX_RISK_PER_TRADE_USDT": "0.3",
                    "BFA_MAX_DAILY_LOSS_USDT": "1",
                    "BFA_MAX_OPEN_POSITIONS": "1",
                    "BFA_POSITION_MODE": "hedge",
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: FakeSignedClient(),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "ready_for_profile_switch")
        self.assertTrue(payload["direction_support"]["long_entries_supported"])
        self.assertTrue(payload["direction_support"]["short_entries_supported"])
        self.assertFalse(payload["entry_capacity"]["can_open_new_position"])
        self.assertIn("max_open_positions_reached", payload["entry_capacity"]["reasons"])
        self.assertEqual(payload["target_profile"]["target_leverage"], 10)
        self.assertTrue(payload["risk_change"]["risk_change_allowed"])

    def test_ops_risk_profile_apply_blocks_active_position_without_writing_env(self):
        class FakeSignedClient:
            def account(self):
                return {"availableBalance": "30", "totalWalletBalance": "30"}

            def position_risk(self):
                return [{"symbol": "HYPEUSDT", "positionAmt": "0.16", "positionSide": "LONG"}]

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return [{"symbol": "HYPEUSDT", "positionSide": "LONG"}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()
            env_path = root / "env"
            env_path.write_text(
                "\n".join(
                    [
                        "BFA_MODE=live",
                        "BFA_MAX_LEVERAGE=5",
                        "BFA_MAX_POSITION_NOTIONAL_USDT=12",
                        "BFA_RUNTIME_DIR=" + str(runtime),
                        "BINANCE_API_KEY=synthetic-binance-key-abcdef",
                        "BINANCE_API_SECRET=synthetic-binance-secret-abcdef",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            plan_code, plan_stdout, _ = self.invoke(
                "ops",
                "risk-profile-plan",
                "--env-file",
                str(env_path),
            )
            token = json.loads(plan_stdout)["confirmation_token"]

            code, stdout, stderr = self.invoke(
                "ops",
                "risk-profile-apply",
                "--env-file",
                str(env_path),
                "--db",
                str(db_path),
                "--confirm-token",
                token,
                signed_client_factory=lambda _config: FakeSignedClient(),
            )
            text = env_path.read_text(encoding="utf-8")

        payload = json.loads(stdout)
        self.assertEqual(plan_code, 0)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["status"], "apply_blocked")
        self.assertIn("risk_change_not_allowed", payload["reasons"])
        self.assertIn("active_position_present", payload["reasons"])
        self.assertIn("BFA_MAX_LEVERAGE=5", text)
        self.assertNotIn("BFA_MAX_LEVERAGE=8", text)

    def test_ops_live_resume_plan_reads_operator_packet_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = root / "operator-decision.json"
            packet.write_text(
                json.dumps(
                    {
                        "schema": "bfa_operator_resume_decision_v1",
                        "status": "collect_more_paper",
                        "eligible_for_operator_resume": False,
                        "readiness_status": "keep_live_paused",
                        "readiness_live_resume_allowed": False,
                        "recommendation": {
                            "next_action": "collect_more_guarded_paper_or_recalibrate_before_live_resume",
                            "blocking_categories": ["paper"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "ops",
                "live-resume-plan",
                "--operator-decision-report",
                str(packet),
                "--current-live-timer-state",
                "active",
                "--current-live-service-state",
                "inactive",
                "--current-paper-timer-state",
                "active",
                "--current-paper-service-state",
                "inactive",
                env={
                    "BFA_MODE": "live",
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_live_resume_plan_v1")
        self.assertEqual(payload["status"], "resume_apply_blocked")
        self.assertFalse(payload["resume_allowed"])
        self.assertFalse(payload["applies_changes"])
        self.assertFalse(payload["read_only"]["writes_env_files"])
        self.assertEqual(payload["risk_boundaries"]["max_position_notional_usdt"], 100.0)

    def test_ops_live_resume_apply_blocks_non_eligible_packet_without_writing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = root / "operator-decision.json"
            env_path = root / "env"
            packet.write_text(
                json.dumps(
                    {
                        "schema": "bfa_operator_resume_decision_v1",
                        "status": "collect_more_paper",
                        "eligible_for_operator_resume": False,
                        "readiness_status": "keep_live_paused",
                        "readiness_live_resume_allowed": False,
                        "recommendation": {
                            "next_action": "collect_more_guarded_paper_or_recalibrate_before_live_resume",
                            "blocking_categories": ["paper"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            env_path.write_text(
                "\n".join(
                    [
                        "BFA_MODE=live",
                        "BFA_MAX_LEVERAGE=10",
                        "BFA_MAX_POSITION_NOTIONAL_USDT=60",
                        "BINANCE_API_KEY=synthetic-binance-key-abcdef",
                        "BINANCE_API_SECRET=synthetic-binance-secret-abcdef",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "ops",
                "live-resume-apply",
                "--env-file",
                str(env_path),
                "--operator-decision-report",
                str(packet),
                "--confirm-token",
                "wrong",
            )
            text = env_path.read_text(encoding="utf-8")
            backup_files = [item.name for item in root.iterdir() if ".bak." in item.name]

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertFalse(payload["applied"])
        self.assertIn("operator_decision_not_eligible", payload["reasons"])
        self.assertIn("BFA_MAX_LEVERAGE=10", text)
        self.assertEqual(backup_files, [])

    def test_ops_trade_outcome_persists_latest_submitted_trade(self):
        class FakeSignedClient:
            def user_trades(self, symbol, *, start_time=None, limit=500):
                return [
                    {
                        "id": 10,
                        "orderId": 100,
                        "symbol": symbol,
                        "side": "BUY",
                        "qty": "0.032",
                        "price": "467.68",
                        "quoteQty": "14.96576",
                        "realizedPnl": "0",
                        "commission": "0.00748288",
                        "commissionAsset": "USDT",
                        "time": 1781923762837,
                    },
                    {
                        "id": 11,
                        "orderId": 101,
                        "symbol": symbol,
                        "side": "SELL",
                        "qty": "0.032",
                        "price": "471.49",
                        "quoteQty": "15.08768",
                        "realizedPnl": "0.12192",
                        "commission": "0.00754384",
                        "commissionAsset": "USDT",
                        "time": 1781924000000,
                    },
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-06-20T02:49:17Z",
                source="execution.live",
                symbol="ZECUSDT",
                ref_id="order_intent:ZECUSDT:2026-06-20T02:49:17Z",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "ZECUSDT",
                        "side": "BUY",
                        "quantity": 0.032,
                        "entry_price": 467.68,
                        "leverage": 3,
                    },
                },
                event_type="order_intent",
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "trade-outcome",
                "--db",
                str(db_path),
                "--symbol",
                "ZECUSDT",
                "--persist",
                env={
                    "BFA_MODE": "live",
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: FakeSignedClient(),
            )
            check = sqlite3.connect(db_path)
            try:
                fill_count = check.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
                outcome_count = check.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
            finally:
                check.close()

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["found"])
        self.assertEqual(payload["outcome"]["status"], "closed")
        self.assertAlmostEqual(payload["outcome"]["net_realized_pnl_usdt"], 0.10689328)
        self.assertEqual(fill_count, 2)
        self.assertEqual(outcome_count, 1)

    def test_ops_reconcile_outcomes_persists_only_closed_outcomes(self):
        class FakeSignedClient:
            def user_trades(self, symbol, *, start_time=None, end_time=None, limit=500):
                if symbol == "ZECUSDT":
                    return [
                        {
                            "id": 10,
                            "orderId": 100,
                            "symbol": symbol,
                            "side": "BUY",
                            "qty": "0.032",
                            "price": "467.68",
                            "quoteQty": "14.96576",
                            "realizedPnl": "0",
                            "commission": "0.00748288",
                            "commissionAsset": "USDT",
                            "time": 1781923762837,
                        },
                        {
                            "id": 11,
                            "orderId": 101,
                            "symbol": symbol,
                            "side": "SELL",
                            "qty": "0.032",
                            "price": "471.49",
                            "quoteQty": "15.08768",
                            "realizedPnl": "0.12192",
                            "commission": "0.00754384",
                            "commissionAsset": "USDT",
                            "time": 1781924000000,
                        },
                    ]
                return [
                    {
                        "id": 20,
                        "orderId": 200,
                        "symbol": symbol,
                        "side": "BUY",
                        "qty": "0.01",
                        "price": "581.47",
                        "quoteQty": "5.8147",
                        "realizedPnl": "0",
                        "commission": "0.00232588",
                        "commissionAsset": "USDT",
                        "time": 1781926994383,
                    }
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-06-20T02:49:17Z",
                source="execution.live",
                symbol="ZECUSDT",
                ref_id="order_intent:ZECUSDT:2026-06-20T02:49:17Z",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "ZECUSDT",
                        "side": "BUY",
                        "quantity": 0.032,
                        "entry_price": 467.68,
                        "leverage": 3,
                    },
                },
                event_type="order_intent",
            )
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-06-20T03:43:09Z",
                source="execution.live",
                symbol="BNBUSDT",
                ref_id="order_intent:BNBUSDT:2026-06-20T03:43:09Z",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "BNBUSDT",
                        "side": "BUY",
                        "quantity": 0.01,
                        "entry_price": 581.47,
                        "leverage": 5,
                    },
                },
                event_type="order_intent",
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "reconcile-outcomes",
                "--db",
                str(db_path),
                "--persist-closed",
                env={
                    "BFA_MODE": "live",
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: FakeSignedClient(),
            )
            check = sqlite3.connect(db_path)
            try:
                fill_count = check.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
                outcome_count = check.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
            finally:
                check.close()

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["found"])
        self.assertEqual(payload["report"]["summary"]["closed"], 1)
        self.assertEqual(payload["report"]["summary"]["open_or_partial"], 1)
        self.assertEqual(payload["report"]["summary"]["persisted_outcomes_inserted"], 1)
        self.assertEqual(fill_count, 2)
        self.assertEqual(outcome_count, 1)

    def test_ops_position_hold_check_reports_expired_live_hold_window(self):
        class FakeSignedClient:
            def account(self):
                return {"availableBalance": "30", "totalWalletBalance": "30"}

            def position_risk(self):
                return [
                    {
                        "symbol": "BNBUSDT",
                        "positionAmt": "0.01",
                        "positionSide": "LONG",
                        "entryPrice": "581.47",
                        "markPrice": "581.00",
                        "unRealizedProfit": "-0.0047",
                    }
                ]

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return [
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-06-20T03:43:09Z",
                source="execution.live",
                symbol="BNBUSDT",
                ref_id="order_intent:BNBUSDT:2026-06-20T03:43:09Z",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "BNBUSDT",
                        "side": "BUY",
                        "quantity": 0.01,
                        "entry_price": 581.47,
                        "leverage": 5,
                        "metadata": {"hold_time_minutes": 30},
                    },
                },
                event_type="order_intent",
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "position-hold-check",
                "--db",
                str(db_path),
                "--now",
                "2026-06-20T04:20:00Z",
                env={
                    "BFA_MODE": "live",
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: FakeSignedClient(),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "review_required")
        self.assertTrue(payload["action_required"])
        self.assertIn("hold_time_expired", payload["reasons"])
        self.assertEqual(payload["positions"][0]["matching_intent"]["hold_time_minutes"], 30)

    def test_ops_time_exit_plan_outputs_read_only_close_plan(self):
        class FakeSignedClient:
            def account(self):
                return {"availableBalance": "30", "totalWalletBalance": "30"}

            def position_risk(self):
                return [
                    {
                        "symbol": "BNBUSDT",
                        "positionAmt": "0.01",
                        "positionSide": "LONG",
                        "entryPrice": "581.47",
                        "markPrice": "581.00",
                        "unRealizedProfit": "-0.0047",
                    }
                ]

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return [
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-06-20T03:43:09Z",
                source="execution.live",
                symbol="BNBUSDT",
                ref_id="order_intent:BNBUSDT:2026-06-20T03:43:09Z",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "BNBUSDT",
                        "side": "BUY",
                        "quantity": 0.01,
                        "entry_price": 581.47,
                        "leverage": 5,
                        "metadata": {"hold_time_minutes": 30},
                    },
                },
                event_type="order_intent",
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "time-exit-plan",
                "--db",
                str(db_path),
                "--now",
                "2026-06-20T04:20:00Z",
                env={
                    "BFA_MODE": "live",
                    "BFA_POSITION_MODE": "hedge",
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: FakeSignedClient(),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["exit_allowed"])
        self.assertEqual(payload["status"], "exit_plan_ready")
        order_plan = payload["plans"][0]["order_plan"]
        self.assertEqual(order_plan["symbol"], "BNBUSDT")
        self.assertEqual(order_plan["side"], "SELL")
        self.assertEqual(order_plan["order_type"], "MARKET")
        self.assertEqual(order_plan["quantity"], 0.01)
        self.assertEqual(order_plan["position_side"], "LONG")
        self.assertFalse(order_plan["reduce_only"])

    def test_ops_position_review_outputs_read_only_recommendation(self):
        class FakeSignedClient:
            def account(self):
                return {"availableBalance": "30", "totalWalletBalance": "30"}

            def position_risk(self):
                return [
                    {
                        "symbol": "BNBUSDT",
                        "positionAmt": "0.01",
                        "positionSide": "LONG",
                        "entryPrice": "100",
                        "markPrice": "107",
                        "unRealizedProfit": "0.07",
                    }
                ]

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return [
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-06-20T03:43:09Z",
                source="execution.live",
                symbol="BNBUSDT",
                ref_id="order_intent:BNBUSDT:2026-06-20T03:43:09Z",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "BNBUSDT",
                        "side": "BUY",
                        "quantity": 0.01,
                        "entry_price": 100,
                        "stop_price": 96,
                        "target_price": 108,
                        "leverage": 5,
                        "metadata": {"hold_time_minutes": 120},
                    },
                },
                event_type="order_intent",
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "position-review",
                "--db",
                str(db_path),
                "--now",
                "2026-06-20T04:00:00Z",
                env={
                    "BFA_MODE": "live",
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: FakeSignedClient(),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "review_ok")
        self.assertEqual(payload["positions"][0]["recommendation"], "trail_or_reduce")
        self.assertIn("near_target", payload["positions"][0]["reasons"])

    def test_ops_position_adjustment_plan_outputs_read_only_partial_reduce(self):
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

        class FakeSignedClient:
            def account(self):
                return {"availableBalance": "30", "totalWalletBalance": "30"}

            def position_risk(self):
                return [
                    {
                        "symbol": "BTCUSDT",
                        "positionAmt": "0.2",
                        "positionSide": "LONG",
                        "entryPrice": "100",
                        "markPrice": "107",
                        "unRealizedProfit": "1.4",
                    }
                ]

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return [
                    {"symbol": "BTCUSDT", "positionSide": "LONG"},
                    {"symbol": "BTCUSDT", "positionSide": "LONG"},
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            store.insert_artifact(
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
                        "metadata": {"hold_time_minutes": 120},
                    },
                },
                event_type="order_intent",
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "position-adjustment-plan",
                "--db",
                str(db_path),
                "--now",
                "2026-06-20T04:00:00Z",
                env={
                    "BFA_MODE": "live",
                    "BFA_POSITION_MODE": "hedge",
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                client_factory=lambda _config: FakeMarketClient(),
                signed_client_factory=lambda _config: FakeSignedClient(),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "adjustment_plan_ready")
        order_plan = payload["plans"][0]["order_plan"]
        self.assertEqual(order_plan["action"], "partial_take_profit")
        self.assertEqual(order_plan["quantity"], 0.1)
        self.assertEqual(order_plan["position_side"], "LONG")
        diagnostic = payload["diagnostics"][0]
        self.assertEqual(diagnostic["symbol"], "BTCUSDT")
        self.assertEqual(diagnostic["lifecycle_decision"], "reduce")
        self.assertEqual(diagnostic["candidate_action"], "partial_take_profit")
        self.assertEqual(diagnostic["exchange_filter_state"], "checked")
        self.assertEqual(diagnostic["failed_preconditions"], [])

    def test_ops_time_exit_execute_requires_token_before_order(self):
        class FakeSignedClient:
            def __init__(self):
                self.orders = []

            def account(self):
                return {"availableBalance": "30", "totalWalletBalance": "30"}

            def position_risk(self):
                return [
                    {
                        "symbol": "BNBUSDT",
                        "positionAmt": "0.01",
                        "positionSide": "LONG",
                        "entryPrice": "581.47",
                        "markPrice": "581.00",
                        "unRealizedProfit": "-0.0047",
                    }
                ]

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return [
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                    {"symbol": "BNBUSDT", "positionSide": "LONG"},
                ]

            def new_order(self, **kwargs):
                self.orders.append(kwargs)
                return {"orderId": 42}

        fake_client = FakeSignedClient()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            runtime = root / "runtime"
            runtime.mkdir()
            connection = sqlite3.connect(db_path)
            store = EventStore(connection)
            store.insert_artifact(
                "order_intents",
                occurred_at="2026-06-20T03:43:09Z",
                source="execution.live",
                symbol="BNBUSDT",
                ref_id="order_intent:BNBUSDT:2026-06-20T03:43:09Z",
                payload={
                    "status": "submitted",
                    "intent": {
                        "symbol": "BNBUSDT",
                        "side": "BUY",
                        "quantity": 0.01,
                        "entry_price": 581.47,
                        "leverage": 5,
                        "metadata": {"hold_time_minutes": 30},
                    },
                },
                event_type="order_intent",
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "time-exit-execute",
                "--db",
                str(db_path),
                "--now",
                "2026-06-20T04:20:00Z",
                env={
                    "BFA_MODE": "live",
                    "BFA_POSITION_MODE": "hedge",
                    "BFA_RUNTIME_DIR": str(runtime),
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: fake_client,
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["status"], "confirmation_required")
        self.assertTrue(payload["confirmation_required"])
        self.assertTrue(payload["expected_confirmation_token"].startswith("TIME-EXIT-BNBUSDT-"))
        self.assertEqual(fake_client.orders, [])

    def test_backtest_fetch_klines_uses_fake_client_and_writes_dataset(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def klines(self, symbol, *, interval, limit=30, start_time=None, end_time=None):
                self.calls.append((symbol, interval, limit, start_time, end_time))
                return MarketDataResponse(
                    endpoint="/fapi/v1/klines",
                    params={},
                    payload=[test_kline(1_700_000_000_000)],
                )

        fake_client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "klines.json"
            code, stdout, stderr = self.invoke(
                "backtest",
                "fetch-klines",
                "--symbols",
                "btcusdt,ethusdt",
                "--interval",
                "5m",
                "--limit",
                "1",
                "--output",
                str(output),
                client_factory=lambda _config: fake_client,
            )
            dataset = json.loads(output.read_text(encoding="utf-8"))

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["bar_counts"], {"BTCUSDT": 1, "ETHUSDT": 1})
        self.assertEqual(sorted(dataset["symbols"]), ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(len(fake_client.calls), 2)

    def test_backtest_run_and_sweep_emit_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "klines.json"
            report = root / "report.json"
            rows = []
            price = 100.0
            for index in range(16):
                close = price * 1.01
                rows.append(
                    test_kline(
                        1_700_000_000_000 + index * 300_000,
                        open_price=str(price),
                        high=str(close * 1.025),
                        low=str(price * 0.998),
                        close=str(close),
                    )
                )
                price = close
            dataset.write_text(
                json.dumps({"schema": "bfa_klines_v1", "interval": "5m", "symbols": {"BTCUSDT": rows}}),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "backtest",
                "run",
                "--input",
                str(dataset),
                "--variant",
                "balanced",
                "--include-trades",
                "--output",
                str(report),
            )
            run_payload = json.loads(stdout)
            saved_payload = json.loads(report.read_text(encoding="utf-8"))

            sweep_code, sweep_stdout, sweep_stderr = self.invoke(
                "backtest",
                "sweep",
                "--input",
                str(dataset),
                "--window-bars",
                "8",
                "--step-bars",
                "4",
                "--variants",
                "balanced,aggressive",
            )
            sweep_payload = json.loads(sweep_stdout)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(run_payload["schema"], "bfa_backtest_result_v1")
        self.assertEqual(saved_payload["schema"], "bfa_backtest_result_v1")
        self.assertGreaterEqual(run_payload["summary"]["trade_count"], 1)
        self.assertIn("trades", run_payload)
        self.assertEqual(sweep_code, 0)
        self.assertEqual(sweep_stderr, "")
        self.assertEqual(sweep_payload["schema"], "bfa_staged_backtest_sweep_v1")
        self.assertEqual(sweep_payload["window_count"], 3)

    def test_backtest_quant_setup_variant_emits_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "klines.json"
            rows = []
            price = 100.0
            for index in range(16):
                close = price * 1.012
                rows.append(
                    test_kline(
                        1_700_000_000_000 + index * 300_000,
                        open_price=str(price),
                        high=str(close * 1.025),
                        low=str(price * 0.997),
                        close=str(close),
                    )
                )
                price = close
            dataset.write_text(
                json.dumps({"schema": "bfa_klines_v1", "interval": "5m", "symbols": {"BTCUSDT": rows}}),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "backtest",
                "run",
                "--input",
                str(dataset),
                "--variant",
                "quant_setup",
                "--include-trades",
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["config"]["strategy_type"], "quant_setup")
        self.assertGreaterEqual(payload["summary"]["trade_count"], 1)
        self.assertEqual(payload["trades"][0]["side"], "long")

    def test_backtest_quant_setup_selective_variant_emits_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "klines.json"
            rows = []
            price = 100.0
            for index in range(18):
                close = price * 1.012
                rows.append(
                    test_kline(
                        1_700_000_000_000 + index * 300_000,
                        open_price=str(price),
                        high=str(close * 1.025),
                        low=str(price * 0.997),
                        close=str(close),
                    )
                )
                price = close
            dataset.write_text(
                json.dumps({"schema": "bfa_klines_v1", "interval": "5m", "symbols": {"BTCUSDT": rows}}),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "backtest",
                "run",
                "--input",
                str(dataset),
                "--variant",
                "quant_setup_selective",
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["config"]["setup_profile"]["name"], "selective")

    def test_backtest_quant_setup_selective_guarded_variant_emits_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "klines.json"
            rows = []
            price = 100.0
            for index in range(18):
                close = price * 1.012
                rows.append(
                    test_kline(
                        1_700_000_000_000 + index * 300_000,
                        open_price=str(price),
                        high=str(close * 1.025),
                        low=str(price * 0.997),
                        close=str(close),
                    )
                )
                price = close
            dataset.write_text(
                json.dumps({"schema": "bfa_klines_v1", "interval": "5m", "symbols": {"BTCUSDT": rows}}),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "backtest",
                "run",
                "--input",
                str(dataset),
                "--variant",
                "quant_setup_selective_guarded",
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["config"]["setup_profile"]["name"], "selective_guarded")
        self.assertEqual(payload["config"]["setup_profile"]["disabled_sides"], ["short"])
        self.assertIn("BICOUSDT", payload["config"]["setup_profile"]["excluded_symbols"])

    def test_backtest_quant_setup_loss_recalibrated_variant_emits_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "klines.json"
            rows = []
            price = 100.0
            for index in range(20):
                close = price * 1.012
                rows.append(
                    test_kline(
                        1_700_000_000_000 + index * 300_000,
                        open_price=str(price),
                        high=str(close * 1.025),
                        low=str(price * 0.997),
                        close=str(close),
                    )
                )
                price = close
            dataset.write_text(
                json.dumps({"schema": "bfa_klines_v1", "interval": "5m", "symbols": {"BTCUSDT": rows}}),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "backtest",
                "run",
                "--input",
                str(dataset),
                "--variant",
                "quant_setup_loss_recalibrated",
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["config"]["setup_profile"]["name"], "loss_recalibrated")
        self.assertEqual(payload["config"]["setup_profile"]["disabled_sides"], ["short"])
        self.assertIn("taker_flow_acceleration", payload["config"]["setup_profile"]["blocked_factor_reasons"])
        self.assertIn("volume_impulse", payload["config"]["setup_profile"]["blocked_factor_names"])

    def test_backtest_matrix_suite_emits_multi_universe_report(self):
        class FakeClient:
            def ticker_24hr(self, symbol=None):
                return MarketDataResponse(
                    endpoint="/fapi/v1/ticker/24hr",
                    params={},
                    payload=[
                        {"symbol": "HOTUSDT", "priceChangePercent": "6", "quoteVolume": "90000000", "count": 1000},
                        {"symbol": "MOVEUSDT", "priceChangePercent": "-4", "quoteVolume": "70000000", "count": 1000},
                    ],
                )

            def klines(self, symbol, *, interval, limit=30, start_time=None, end_time=None):
                rows = []
                price = 100.0
                for index in range(limit):
                    close = price * 1.01
                    rows.append(
                        test_kline(
                            1_700_000_000_000 + index * 300_000,
                            open_price=str(price),
                            high=str(close * 1.025),
                            low=str(price * 0.997),
                            close=str(close),
                        )
                    )
                    price = close
                return MarketDataResponse(endpoint="/fapi/v1/klines", params={}, payload=rows)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "matrix-suite.json"
            code, stdout, stderr = self.invoke(
                "backtest",
                "matrix-suite",
                "--intervals",
                "5m",
                "--limit",
                "16",
                "--window-bars",
                "8",
                "--step-bars",
                "4",
                "--variants",
                "quant_setup_selective,quant_setup_loss_recalibrated",
                "--universe-presets",
                "broad,momentum",
                "--output",
                str(output),
                client_factory=lambda _config: FakeClient(),
            )
            wrote_output = output.exists()

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_hot_backtest_matrix_suite_v1")
        self.assertEqual([item["preset"] for item in payload["matrices"]], ["broad", "momentum"])
        self.assertIn("quant_setup_loss_recalibrated", payload["promotion"]["variants"])
        self.assertTrue(wrote_output)

    def test_backtest_matrix_auto_selects_hot_symbols_and_writes_report(self):
        class FakeClient:
            def ticker_24hr(self, symbol=None):
                return MarketDataResponse(
                    endpoint="/fapi/v1/ticker/24hr",
                    params={},
                    payload=[
                        {
                            "symbol": "HOTUSDT",
                            "priceChangePercent": "7.5",
                            "quoteVolume": "25000000",
                            "count": 1000,
                        },
                        {
                            "symbol": "SLOWUSDT",
                            "priceChangePercent": "1.0",
                            "quoteVolume": "90000000",
                            "count": 1000,
                        },
                    ],
                )

            def klines(self, symbol, *, interval, limit=30, start_time=None, end_time=None):
                rows = []
                price = 100.0
                for index in range(limit):
                    close = price * 1.01
                    rows.append(
                        test_kline(
                            1_700_000_000_000 + index * 300_000,
                            open_price=str(price),
                            high=str(close * 1.025),
                            low=str(price * 0.998),
                            close=str(close),
                        )
                    )
                    price = close
                return MarketDataResponse(endpoint="/fapi/v1/klines", params={}, payload=rows)

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "matrix.json"
            code, stdout, stderr = self.invoke(
                "backtest",
                "matrix",
                "--intervals",
                "5m",
                "--limit",
                "16",
                "--window-bars",
                "8",
                "--step-bars",
                "4",
                "--variants",
                "balanced",
                "--top-n",
                "1",
                "--output",
                str(report),
                client_factory=lambda _config: FakeClient(),
            )
            payload = json.loads(stdout)
            saved = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_hot_backtest_matrix_v1")
        self.assertEqual(payload["symbols"], ["HOTUSDT"])
        self.assertEqual(saved["schema"], "bfa_hot_backtest_matrix_v1")
        self.assertIn("overall", payload["promotion"])

    def test_ops_strategy_promotion_check_blocks_negative_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "matrix.json"
            report.write_text(
                json.dumps(
                    {
                        "schema": "bfa_hot_backtest_matrix_v1",
                        "promotion": {
                            "overall": "keep_caps_unchanged_drawdown_risk",
                            "cells": [
                                {
                                    "interval": "5m",
                                    "variant": "quant_setup",
                                    "verdict": "negative_or_flat",
                                    "trade_count": 10,
                                    "net_pnl_usdt": -0.5,
                                    "positive_window_rate": 0.33,
                                    "worst_drawdown_usdt": 2.2,
                                    "max_daily_loss_usdt": 2.0,
                                }
                            ],
                            "variants": {
                                "quant_setup": {
                                    "total_net_pnl_usdt": -0.5,
                                    "worst_drawdown_usdt": 2.2,
                                    "verdict": "drawdown_exceeds_pilot_cap",
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "ops",
                "strategy-promotion-check",
                "--matrix-report",
                str(report),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertFalse(payload["promotion_allowed"])
        self.assertIn("variant_not_promoted", payload["reasons"])

    def test_ops_strategy_promotion_check_accepts_selected_interval_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "matrix.json"
            report.write_text(
                json.dumps(
                    {
                        "schema": "bfa_hot_backtest_matrix_v1",
                        "promotion": {
                            "overall": "keep_caps_unchanged_drawdown_risk",
                            "cells": [
                                {
                                    "interval": "5m",
                                    "variant": "quant_setup_selective",
                                    "verdict": "candidate_for_forward_paper",
                                    "trade_count": 51,
                                    "net_pnl_usdt": 1.62,
                                    "positive_window_rate": 1.0,
                                    "worst_drawdown_usdt": 1.27,
                                    "max_daily_loss_usdt": 1.5,
                                },
                                {
                                    "interval": "15m",
                                    "variant": "quant_setup_selective",
                                    "verdict": "negative_or_flat",
                                    "trade_count": 60,
                                    "net_pnl_usdt": -1.4,
                                    "positive_window_rate": 0.33,
                                    "worst_drawdown_usdt": 2.39,
                                    "max_daily_loss_usdt": 1.5,
                                },
                            ],
                            "variants": {
                                "quant_setup_selective": {
                                    "total_net_pnl_usdt": 0.22,
                                    "worst_drawdown_usdt": 2.39,
                                    "verdict": "drawdown_exceeds_pilot_cap",
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "ops",
                "strategy-promotion-check",
                "--matrix-report",
                str(report),
                "--variant",
                "quant_setup_selective",
                "--scope",
                "selected-intervals",
                "--intervals",
                "5m",
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["promotion_allowed"])
        self.assertFalse(payload["live_resume_allowed"])
        self.assertEqual(payload["status"], "forward_paper_allowed")
        self.assertEqual(payload["reasons"], ["selected_intervals_promoted"])
        self.assertEqual(payload["scope"], "selected-intervals")
        self.assertEqual(payload["intervals"], ["5m"])
        self.assertEqual(payload["cell_checks"][0]["interval"], "5m")

    def test_ops_forward_paper_run_records_paper_signal_only(self):
        class FakeClient:
            def ticker_24hr(self, symbol=None):
                return MarketDataResponse(endpoint="/fapi/v1/ticker/24hr", params={}, payload=[])

            def klines(self, symbol, *, interval, limit=30, start_time=None, end_time=None):
                rows = []
                price = 100.0
                for index in range(limit):
                    close = price * 1.018
                    rows.append(
                        test_kline(
                            1_700_000_000_000 + index * 300_000,
                            open_price=str(price),
                            high=str(close * 1.018),
                            low=str(price * 0.999),
                            close=str(close),
                        )
                    )
                    price = close
                return MarketDataResponse(endpoint="/fapi/v1/klines", params={}, payload=rows)

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            code, stdout, stderr = self.invoke(
                "ops",
                "forward-paper-run",
                "--db",
                str(db),
                "--symbols",
                "btcusdt",
                "--interval",
                "5m",
                "--variant",
                "quant_setup",
                "--limit",
                "18",
                "--now",
                "2026-06-20T00:00:00Z",
                client_factory=lambda _config: FakeClient(),
            )
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            try:
                signal_count = connection.execute("SELECT COUNT(*) AS count FROM paper_signals").fetchone()["count"]
                observation_count = connection.execute("SELECT COUNT(*) AS count FROM paper_observations").fetchone()["count"]
                intent_count = connection.execute("SELECT COUNT(*) AS count FROM order_intents").fetchone()["count"]
            finally:
                connection.close()

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_forward_paper_run_v1")
        self.assertEqual(payload["persisted"]["paper_signals"], 1)
        self.assertEqual(payload["persisted"]["paper_observations"], 1)
        self.assertEqual(payload["observation_summary"], {"generated_signal": 1})
        self.assertEqual(payload["source_health"]["symbol_selection"]["mode"], "cli_symbols")
        self.assertEqual(signal_count, 1)
        self.assertEqual(observation_count, 1)
        self.assertEqual(intent_count, 0)

    def test_ops_forward_paper_run_auto_selects_hot_symbols(self):
        class FakeClient:
            def __init__(self):
                self.kline_symbols = []

            def ticker_24hr(self, symbol=None):
                return MarketDataResponse(
                    endpoint="/fapi/v1/ticker/24hr",
                    params={},
                    payload=[
                        {"symbol": "HOTUSDT", "priceChangePercent": "6", "quoteVolume": "90000000", "count": 1000},
                        {"symbol": "SLOWUSDT", "priceChangePercent": "0.1", "quoteVolume": "100000000", "count": 1000},
                        {"symbol": "USDCUSDT", "priceChangePercent": "8", "quoteVolume": "120000000", "count": 1000},
                    ],
                )

            def klines(self, symbol, *, interval, limit=30, start_time=None, end_time=None):
                self.kline_symbols.append(symbol)
                rows = []
                price = 100.0
                for index in range(limit):
                    close = price * 1.01
                    rows.append(
                        test_kline(
                            1_700_000_000_000 + index * 300_000,
                            open_price=str(price),
                            high=str(close * 1.01),
                            low=str(price * 0.999),
                            close=str(close),
                        )
                    )
                    price = close
                return MarketDataResponse(endpoint="/fapi/v1/klines", params={}, payload=rows)

        fake_client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            code, stdout, stderr = self.invoke(
                "ops",
                "forward-paper-run",
                "--db",
                str(db),
                "--top-n",
                "2",
                "--min-quote-volume-usdt",
                "10000000",
                "--min-abs-price-change-percent",
                "0.5",
                "--interval",
                "5m",
                "--variant",
                "quant_setup_selective",
                "--limit",
                "18",
                client_factory=lambda _config: fake_client,
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["symbols"], ["HOTUSDT"])
        self.assertEqual(payload["source_health"]["symbol_selection"]["mode"], "binance_24h_ticker")
        self.assertEqual(payload["source_health"]["binance_24h_ticker"]["payload_count"], 3)
        self.assertEqual(fake_client.kline_symbols, ["HOTUSDT"])

    def test_ops_forward_paper_performance_check_reports_insufficient_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            code, stdout, stderr = self.invoke(
                "ops",
                "forward-paper-performance-check",
                "--db",
                str(db),
                "--min-outcomes",
                "1",
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_forward_paper_performance_v1")
        self.assertEqual(payload["status"], "no_paper_evidence")
        self.assertFalse(payload["live_resume_allowed"])

    def test_ops_forward_paper_loss_attribution_reports_negative_groups(self):
        from tests.test_ops_forward_paper_loss_attribution import outcome_payload, signal_payload

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            from bfa.event_store.migrations import connect

            connection = connect(db)
            store = EventStore(connection)
            signal_id = store.insert_artifact(
                "paper_signals",
                occurred_at="2026-06-20T00:00:00Z",
                source="test",
                symbol="BICOUSDT",
                ref_id="paper_signal:test",
                event_type="paper_signal",
                payload=signal_payload("BICOUSDT", warnings=["crowding_risk"]),
            )
            store.insert_artifact(
                "paper_outcomes",
                occurred_at="2026-06-20T00:20:00Z",
                source="test",
                symbol="BICOUSDT",
                ref_id=f"paper_outcome:{signal_id}",
                event_type="paper_outcome",
                payload=outcome_payload(signal_id, "BICOUSDT", -0.3),
            )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "forward-paper-loss-attribution",
                "--db",
                str(db),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_forward_paper_loss_attribution_v1")
        self.assertEqual(payload["status"], "loss_attribution_ready")
        self.assertFalse(payload["live_resume_allowed"])
        self.assertEqual(payload["worst_groups"]["symbols"][0]["name"], "BICOUSDT")
        self.assertTrue(payload["recalibration_candidates"])

    def test_ops_strategy_evidence_baseline_reports_live_resume_blockers(self):
        from tests.test_ops_forward_paper_performance import outcome_payload, signal_payload

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "paper.sqlite"
            from bfa.event_store.migrations import connect

            connection = connect(db)
            store = EventStore(connection)
            for index, pnl in enumerate([-0.3, 0.1]):
                signal_id = store.insert_artifact(
                    "paper_signals",
                    occurred_at=f"2026-06-20T00:0{index}:00Z",
                    source="test",
                    symbol="BICOUSDT",
                    ref_id=f"paper_signal:{index}",
                    event_type="paper_signal",
                    payload=signal_payload(
                        "BICOUSDT",
                        index,
                        opened_at=f"2026-06-20T00:0{index}:00Z",
                    ),
                )
                store.insert_artifact(
                    "paper_outcomes",
                    occurred_at=f"2026-06-20T01:0{index}:00Z",
                    source="test",
                    symbol="BICOUSDT",
                    ref_id=f"paper_outcome:{signal_id}",
                    event_type="paper_outcome",
                    payload=outcome_payload(
                        signal_id,
                        "BICOUSDT",
                        pnl,
                        closed_at=f"2026-06-20T01:0{index}:00Z",
                        exit_reason="stop_loss" if pnl < 0 else "take_profit",
                    ),
                )
            connection.close()

            code, stdout, stderr = self.invoke(
                "ops",
                "strategy-evidence-baseline",
                "--db",
                str(db),
                "--min-outcomes",
                "2",
                "--min-profit-factor",
                "1.1",
                "--no-systemd-check",
                "--paper-timer-state",
                "active",
                "--live-timer-state",
                "inactive",
                "--live-service-state",
                "inactive",
                "--exchange-state",
                "clear",
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_strategy_evidence_baseline_v1")
        self.assertEqual(payload["status"], "keep_live_paused")
        self.assertFalse(payload["live_resume_allowed"])
        self.assertEqual(payload["server_state"]["paper.timer"]["state"], "active")
        self.assertIn("paper_total_net_pnl_not_above_min", payload["reasons"]["strategy_evidence"])
        self.assertEqual(payload["reasons"]["server_state"], [])
        self.assertEqual(payload["reasons"]["exchange_state"], [])
        self.assertEqual(payload["reasons"]["confirmation"], ["operator_confirmation_required"])

    def test_ops_operator_resume_decision_reads_readiness_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            readiness = Path(tmp) / "readiness.json"
            readiness.write_text(
                json.dumps(
                    {
                        "schema": "bfa_live_resume_readiness_v1",
                        "status": "keep_live_paused",
                        "live_resume_allowed": False,
                        "reasons": {
                            "matrix": ["suite_variant_not_promoted"],
                            "strategy_evidence": ["paper_signals_missing"],
                            "server_state": [],
                            "exchange_state": ["manual_or_unattributed_exchange_exposure_present"],
                            "risk_profile": ["active_position_present"],
                            "confirmation": ["operator_confirmation_required"],
                        },
                        "exchange_review": {
                            "manual_or_unattributed_symbols": ["ETHUSDT"],
                            "agent_managed_symbols": [],
                            "manual_exposure_is_agent_evidence": False,
                            "position_count": 1,
                            "open_order_count": 0,
                            "open_algo_order_count": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke(
                "ops",
                "operator-resume-decision",
                "--readiness-report",
                str(readiness),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_operator_resume_decision_v1")
        self.assertEqual(payload["status"], "resolve_exposure")
        self.assertEqual(payload["exposure"]["manual_or_unattributed_symbols"], ["ETHUSDT"])
        self.assertFalse(payload["read_only"]["places_orders"])

    def test_ops_exposure_clearance_reports_manual_blocker(self):
        class FakeSignedClient:
            def account(self):
                return {"availableBalance": "30", "totalWalletBalance": "30"}

            def position_risk(self):
                return [
                    {
                        "symbol": "ETHUSDT",
                        "positionAmt": "0.01",
                        "positionSide": "LONG",
                        "entryPrice": "3500",
                        "markPrice": "3490",
                    }
                ]

            def open_orders(self):
                return []

            def open_algo_orders(self):
                return [{"symbol": "ETHUSDT", "positionSide": "LONG", "algoId": 1}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            code, stdout, stderr = self.invoke(
                "ops",
                "exposure-clearance",
                "--manual-exposure-symbols",
                "ETHUSDT",
                env={
                    "BFA_MODE": "live",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                },
                signed_client_factory=lambda _config: FakeSignedClient(),
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_exposure_clearance_v1")
        self.assertEqual(payload["status"], "resolve_exposure")
        self.assertEqual(payload["positions"][0]["classification"], "manual")
        self.assertFalse(payload["read_only"]["mutates_exchange_state"])

    def test_ops_manual_loss_record_persists_incident(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db = root / "agent.sqlite"
            code, stdout, stderr = self.invoke(
                "ops",
                "manual-loss-record",
                "--db",
                str(db),
                "--symbol",
                "SOLUSDT",
                "--side",
                "long",
                "--leverage",
                "20",
                "--entry-price",
                "100",
                "--liquidation-price",
                "95",
                "--stop-loss-status",
                "none",
                "--trigger-reason",
                "manual chase",
                "--lesson",
                "no stop",
                "--occurred-at",
                "2026-06-21T01:00:00Z",
                env={
                    "BFA_MODE": "live",
                    "BFA_DB_PATH": str(db),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                },
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_manual_loss_record_v1")
        self.assertTrue(payload["recorded"])
        self.assertEqual(payload["incident"]["symbol"], "SOLUSDT")
        self.assertFalse(payload["read_only_exchange"]["places_orders"])

    def test_ops_manual_loss_review_reports_risk_guard_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            db = root / "agent.sqlite"
            env = {
                "BFA_MODE": "live",
                "BFA_DB_PATH": str(db),
                "BFA_RUNTIME_DIR": str(root / "runtime"),
                "BFA_MAX_LEVERAGE": "10",
            }
            self.invoke(
                "ops",
                "manual-loss-record",
                "--db",
                str(db),
                "--symbol",
                "SOLUSDT",
                "--side",
                "long",
                "--leverage",
                "20",
                "--entry-price",
                "100",
                "--liquidation-price",
                "99",
                "--stop-loss-status",
                "none",
                "--occurred-at",
                "2026-06-21T01:00:00Z",
                env=env,
            )

            code, stdout, stderr = self.invoke(
                "ops",
                "manual-loss-review",
                "--db",
                str(db),
                "--skip-paper-guard",
                env=env,
            )

        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["schema"], "bfa_manual_loss_review_v1")
        self.assertEqual(payload["status"], "review_ready")
        self.assertEqual(payload["items"][0]["guard_outcome"], "would_block_by_risk_guard")
        self.assertFalse(payload["read_only_exchange"]["writes_env_files"])


if __name__ == "__main__":
    unittest.main()
