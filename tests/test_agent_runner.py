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
        return MarketDataResponse(endpoint="/fapi/v1/exchangeInfo", params={}, payload=exchange_info_payload())


def exchange_info_payload(*symbols):
    payload = json.loads(EXCHANGE_INFO.read_text(encoding="utf-8"))
    if not symbols:
        return payload
    existing = {item["symbol"]: item for item in payload["symbols"]}
    template = dict(existing["BTCUSDT"])
    result = []
    for symbol in symbols:
        item = dict(existing.get(symbol, template))
        item["symbol"] = symbol
        item["pair"] = symbol
        result.append(item)
    return {**payload, "symbols": result}


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


def snapshots_for_symbol(symbol, *, price_change="5.2", quote_volume="12000000", ratio="1.2"):
    return [
        NormalizedMarketSnapshot(
            source="binance_usdm",
            event_type="ticker_24h",
            symbol=symbol,
            event_time=1700000000000,
            received_at="2026-06-20T10:00:00Z",
            payload={"price_change_percent": price_change, "quote_volume": quote_volume},
        ),
        NormalizedMarketSnapshot(
            source="binance_usdm",
            event_type="kline",
            symbol=symbol,
            event_time=1700000000001,
            received_at="2026-06-20T10:00:00Z",
            payload={"high": "101", "low": "99", "close": "100"},
        ),
        NormalizedMarketSnapshot(
            source="binance_usdm",
            event_type="funding_rate",
            symbol=symbol,
            event_time=1700000000002,
            received_at="2026-06-20T10:00:00Z",
            payload={"funding_rate": "0.0001"},
        ),
        NormalizedMarketSnapshot(
            source="binance_usdm",
            event_type="open_interest_hist",
            symbol=symbol,
            event_time=1700000000003,
            received_at="2026-06-20T10:00:00Z",
            payload={"sum_open_interest_value": "5000000"},
        ),
        NormalizedMarketSnapshot(
            source="binance_usdm",
            event_type="taker_buy_sell_volume",
            symbol=symbol,
            event_time=1700000000004,
            received_at="2026-06-20T10:00:00Z",
            payload={"buy_sell_ratio": ratio},
        ),
    ]


class TwoSymbolCollector:
    def collect_rest_snapshots(self):
        return [
            *snapshots_for_symbol("HYPEUSDT", price_change="7.5", quote_volume="18000000", ratio="1.25"),
            *snapshots_for_symbol("BTCUSDT", price_change="5.2", quote_volume="12000000", ratio="1.2"),
        ]


class UntradableBtcCollector(FakeCollector):
    def collect_rest_snapshots(self):
        return [
            *super().collect_rest_snapshots(),
            NormalizedMarketSnapshot(
                source="binance_usdm",
                event_type="exchange_symbol",
                symbol="BTCUSDT",
                event_time=1700000000005,
                received_at="2026-06-20T10:00:00Z",
                payload={
                    "status": "TRADING",
                    "contract_type": "PERPETUAL",
                    "filters": {
                        "MARKET_LOT_SIZE": {"minQty": "0.001", "stepSize": "0.001"},
                        "MIN_NOTIONAL": {"notional": "50"},
                    },
                },
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


class TwoSymbolNarrativeRunner:
    def collect(self):
        return [
            NormalizedNarrativeRecord(
                source="binance_square",
                source_id="square-hype-1",
                author="poster",
                symbol_mentions=["HYPEUSDT"],
                text="HYPEUSDT breakout narrative",
                url=None,
                published_at="2026-06-20T09:58:00Z",
                collected_at="2026-06-20T10:00:00Z",
                engagement={"likes": 90, "comments": 9},
                raw={},
                quality_flags=[],
            ),
            NormalizedNarrativeRecord(
                source="binance_square",
                source_id="square-btc-1",
                author="poster",
                symbol_mentions=["BTCUSDT"],
                text="BTCUSDT breakout narrative",
                url=None,
                published_at="2026-06-20T09:58:00Z",
                collected_at="2026-06-20T10:00:00Z",
                engagement={"likes": 50, "comments": 5},
                raw={},
                quality_flags=[],
            ),
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


class FakeSignedClient:
    def __init__(self, positions=None):
        self.positions = [] if positions is None else positions
        self.calls = []

    def position_risk(self):
        return list(self.positions)

    def account(self):
        self.calls.append(("account",))
        return {"availableBalance": "100"}

    def change_margin_type(self, symbol, *, margin_type):
        self.calls.append(("margin", symbol, margin_type))
        return {"symbol": symbol, "marginType": margin_type}

    def change_initial_leverage(self, symbol, *, leverage):
        self.calls.append(("leverage", symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def new_order(self, **kwargs):
        self.calls.append(("new_order", kwargs))
        return {"orderId": 1, **kwargs}

    def new_algo_order(self, **kwargs):
        self.calls.append(("new_algo_order", kwargs))
        return {"algoId": len(self.calls), **kwargs}


class TwoSymbolMarketClient:
    def exchange_info(self):
        return MarketDataResponse(
            endpoint="/fapi/v1/exchangeInfo",
            params={},
            payload=exchange_info_payload("HYPEUSDT", "BTCUSDT"),
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

    def test_run_once_skips_ai_when_candidate_cannot_fit_notional_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(
                {
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_MAX_POSITION_NOTIONAL_USDT": "20",
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
                collector=UntradableBtcCollector(),
                narrative_runner=FakeNarrativeRunner(),
                ai_client=ai_client,
            )

        self.assertEqual(result.status, "no_candidate")
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(ai_client.calls, 0)

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

    def test_live_run_once_short_circuits_when_entry_capacity_is_full(self):
        class CountingCollector(FakeCollector):
            def __init__(self):
                self.calls = 0

            def collect_rest_snapshots(self):
                self.calls += 1
                return super().collect_rest_snapshots()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = CountingCollector()
            ai_client = FakeAiClient()
            config = load_config(
                {
                    "BFA_MODE": "live",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_MAX_OPEN_POSITIONS": "1",
                    "BFA_MULTI_POSITION_ENABLED": "false",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )

            result = run_agent_once(
                config=config,
                db_path=str(root / "agent.sqlite"),
                market_client=FakeMarketClient(),
                collector=collector,
                narrative_runner=FakeNarrativeRunner(),
                ai_client=ai_client,
                signed_client=FakeSignedClient(
                    positions=[
                        {
                            "symbol": "HYPEUSDT",
                            "positionAmt": "0.16",
                            "positionSide": "LONG",
                        }
                    ]
                ),
            )

        self.assertEqual(result.status, "entry_capacity_blocked")
        self.assertTrue(result.ok)
        self.assertFalse(result.submitted)
        self.assertEqual(result.risk_reasons, ["multi_position_disabled", "max_open_positions_reached"])
        self.assertEqual(result.market_snapshot_count, 0)
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(collector.calls, 0)
        self.assertEqual(ai_client.calls, 0)

    def test_live_run_once_continues_when_multi_position_capacity_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ai_client = FakeAiClient()
            config = load_config(
                {
                    "BFA_MODE": "live",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_MAX_OPEN_POSITIONS": "2",
                    "BFA_MULTI_POSITION_ENABLED": "true",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )

            result = run_agent_once(
                config=config,
                db_path=str(root / "agent.sqlite"),
                market_client=FakeMarketClient(),
                collector=FakeCollector(),
                narrative_runner=FakeNarrativeRunner(),
                ai_client=ai_client,
                signed_client=FakeSignedClient(
                    positions=[
                        {
                            "symbol": "HYPEUSDT",
                            "positionAmt": "0.16",
                            "positionSide": "LONG",
                            "notional": "11.25",
                            "initialMargin": "2.25",
                            "leverage": "5",
                        }
                    ]
                ),
            )

        self.assertNotEqual(result.status, "entry_capacity_blocked")
        self.assertEqual(result.selected_symbol, "BTCUSDT")
        self.assertGreaterEqual(result.market_snapshot_count, 1)
        self.assertEqual(ai_client.calls, 1)

    def test_live_run_once_tries_next_candidate_after_duplicate_exposure_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ai_client = FakeAiClient()
            signed_client = FakeSignedClient(
                positions=[
                    {
                        "symbol": "HYPEUSDT",
                        "positionAmt": "0.16",
                        "positionSide": "LONG",
                        "notional": "11.25",
                        "initialMargin": "2.25",
                        "leverage": "5",
                    }
                ]
            )
            config = load_config(
                {
                    "BFA_MODE": "live",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BINANCE_API_KEY": "synthetic-binance-key-abcdef",
                    "BINANCE_API_SECRET": "synthetic-binance-secret-abcdef",
                    "BFA_MARKET_SYMBOLS": "HYPEUSDT,BTCUSDT",
                    "BFA_MAX_OPEN_POSITIONS": "2",
                    "BFA_MULTI_POSITION_ENABLED": "true",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )

            result = run_agent_once(
                config=config,
                db_path=str(root / "agent.sqlite"),
                market_client=TwoSymbolMarketClient(),
                collector=TwoSymbolCollector(),
                narrative_runner=TwoSymbolNarrativeRunner(),
                ai_client=ai_client,
                signed_client=signed_client,
                top_n=2,
            )

        self.assertEqual(result.status, "submitted")
        self.assertTrue(result.submitted)
        self.assertEqual(result.selected_symbol, "BTCUSDT")
        self.assertEqual(result.evaluated_symbols, ["HYPEUSDT", "BTCUSDT"])
        self.assertEqual(ai_client.calls, 2)
        self.assertIn("HYPEUSDT:duplicate_symbol_direction_exposure", result.risk_reasons)
        self.assertIn("risk_accepted", result.risk_reasons)


if __name__ == "__main__":
    unittest.main()
