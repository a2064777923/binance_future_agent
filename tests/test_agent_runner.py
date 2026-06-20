import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bfa.agent import run_agent_once
from bfa.ai.client import OpenAIAPIError, OpenAIResponse
from bfa.config import load_config
from bfa.market.models import MarketDataResponse, NormalizedMarketSnapshot
from bfa.narrative.models import NormalizedNarrativeRecord


EXCHANGE_INFO = Path(__file__).parent / "fixtures" / "binance_market" / "exchange_info.json"


class FakeMarketClient:
    def exchange_info(self):
        return MarketDataResponse(
            endpoint="/fapi/v1/exchangeInfo",
            params={},
            payload=json.loads(EXCHANGE_INFO.read_text(encoding="utf-8")),
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


class EmptyNarrativeRunner:
    def collect(self):
        return []


class FakeAiClient:
    def __init__(self):
        self.calls = 0
        self.contexts = []

    def create_decision(self, context, *, instructions, schema):
        self.calls += 1
        self.contexts.append(context)
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


class AgentRunnerTests(unittest.TestCase):
    def test_run_once_collects_decides_and_executes_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(
                {
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )

            result = run_agent_once(
                config=config,
                db_path=str(root / "agent.sqlite"),
                journal_path=str(root / "ai.jsonl"),
                market_client=FakeMarketClient(),
                collector=FakeCollector(),
                narrative_runner=FakeNarrativeRunner(),
                ai_client=FakeAiClient(),
            )

        self.assertEqual(result.status, "dry_run")
        self.assertFalse(result.submitted)
        self.assertEqual(result.selected_symbol, "BTCUSDT")
        self.assertEqual(result.market_snapshot_count, 5)
        self.assertEqual(result.narrative_record_count, 1)
        self.assertTrue(result.ai_accepted)
        self.assertEqual(result.risk_reasons, ["risk_accepted"])
        self.assertGreaterEqual(result.persisted["candidates"], 1)
        self.assertEqual(result.persisted["ai_decisions"], 1)
        self.assertGreaterEqual(result.persisted["order_intent"], 1)

    def test_run_once_sends_reference_price_to_ai_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(
                {
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )
            ai_client = FakeAiClient()

            result = run_agent_once(
                config=config,
                db_path=str(root / "agent.sqlite"),
                market_client=FakeMarketClient(),
                collector=FakeCollector(),
                narrative_runner=FakeNarrativeRunner(),
                ai_client=ai_client,
            )

        self.assertEqual(result.status, "dry_run")
        self.assertEqual(ai_client.contexts[0]["candidate"]["features"]["reference_price"], 100.0)

    def test_run_once_uses_market_heat_when_narratives_are_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(
                {
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )
            ai_client = FakeAiClient()

            result = run_agent_once(
                config=config,
                db_path=str(root / "agent.sqlite"),
                market_client=FakeMarketClient(),
                collector=FakeCollector(),
                narrative_runner=EmptyNarrativeRunner(),
                ai_client=ai_client,
            )

        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.selected_symbol, "BTCUSDT")
        self.assertEqual(result.narrative_record_count, 1)
        self.assertEqual(ai_client.calls, 1)
        self.assertGreaterEqual(result.persisted["order_intent"], 1)

    def test_run_once_stops_before_execution_when_openai_errors(self):
        class FailingAiClient:
            def __init__(self):
                self.calls = 0

            def create_decision(self, context, *, instructions, schema):
                self.calls += 1
                raise OpenAIAPIError(
                    status_code=None,
                    message="timed out",
                    payload={},
                    headers={},
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            config = load_config(
                {
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_DB_PATH": str(db_path),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )

            failing_ai = FailingAiClient()
            result = run_agent_once(
                config=config,
                db_path=str(db_path),
                market_client=FakeMarketClient(),
                collector=FakeCollector(),
                narrative_runner=FakeNarrativeRunner(),
                ai_client=failing_ai,
            )
            recovered_ai = FakeAiClient()
            backoff_result = run_agent_once(
                config=config,
                db_path=str(db_path),
                market_client=FakeMarketClient(),
                collector=FakeCollector(),
                narrative_runner=FakeNarrativeRunner(),
                ai_client=recovered_ai,
            )
            connection = sqlite3.connect(db_path)
            try:
                order_intents = connection.execute(
                    "SELECT COUNT(*) FROM order_intents"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(result.status, "ai_error")
        self.assertFalse(result.submitted)
        self.assertEqual(failing_ai.calls, 1)
        self.assertEqual(backoff_result.status, "openai_backoff")
        self.assertEqual(recovered_ai.calls, 0)
        self.assertEqual(order_intents, 0)
        self.assertIn("openai_error:none:timed out", result.validation_errors)


if __name__ == "__main__":
    unittest.main()
