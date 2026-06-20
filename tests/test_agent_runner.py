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

    def ticker_24hr(self, symbol=None):
        return MarketDataResponse(endpoint="/fapi/v1/ticker/24hr", params={}, payload=[])


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
        setup = context.get("quant_setup") or {}
        payload = {
            "decision": setup.get("decision", "trade"),
            "side": setup.get("side", "long"),
            "confidence": setup.get("confidence", 0.74),
            "entry_price": setup.get("entry_price", 100.0),
            "stop_price": setup.get("stop_price", 96.0),
            "target_price": setup.get("target_price", 108.0),
            "notional_usdt": setup.get("notional_usdt", 20.0),
            "hold_time_minutes": setup.get("hold_time_minutes", 30),
            "reasons": setup.get("reasons", ["narrative heat plus market confirmation"]),
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


class AutoHotMarketClient:
    def __init__(self):
        self.calls = []

    def ticker_24hr(self, symbol=None):
        self.calls.append(("ticker_24hr", symbol))
        return MarketDataResponse(
            endpoint="/fapi/v1/ticker/24hr",
            params={},
            payload=[
                {"symbol": "HOTUSDT", "priceChangePercent": "9.0", "quoteVolume": "95000000", "count": 1000},
                {"symbol": "ALTUSDT", "priceChangePercent": "-7.0", "quoteVolume": "90000000", "count": 1000},
                {"symbol": "SLOWUSDT", "priceChangePercent": "0.1", "quoteVolume": "100000000", "count": 1000},
            ],
        )

    def exchange_info(self):
        self.calls.append(("exchange_info",))
        return MarketDataResponse(
            endpoint="/fapi/v1/exchangeInfo",
            params={},
            payload=exchange_info_payload("HOTUSDT", "ALTUSDT"),
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

    def test_run_once_can_scan_auto_hot_symbols_beyond_fixed_live_allowlist(self):
        class AutoHotCollector:
            def __init__(self, symbols):
                self.symbols = symbols

            def collect_rest_snapshots(self):
                snapshots = []
                for symbol in self.symbols:
                    snapshots.extend(snapshots_for_symbol(symbol, price_change="8.0", quote_volume="50000000"))
                return snapshots

        class AutoHotNarrativeRunner:
            def __init__(self, symbols):
                self.symbols = symbols

            def collect(self):
                return [
                    NormalizedNarrativeRecord(
                        source="binance_square",
                        source_id=f"square-{symbol}",
                        author="poster",
                        symbol_mentions=[symbol],
                        text=f"{symbol} hot narrative",
                        url=None,
                        published_at="2026-06-20T09:58:00Z",
                        collected_at="2026-06-20T10:00:00Z",
                        engagement={"likes": 70, "comments": 7},
                        raw={},
                        quality_flags=[],
                    )
                    for symbol in self.symbols
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            market_client = AutoHotMarketClient()
            config = load_config(
                {
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_LIVE_AUTO_HOT_SYMBOLS": "true",
                    "BFA_LIVE_AUTO_HOT_TOP_N": "2",
                    "BFA_LIVE_AUTO_HOT_MIN_QUOTE_VOLUME_USDT": "10000000",
                    "BFA_LIVE_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT": "0.5",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )

            result = run_agent_once(
                config=config,
                db_path=str(root / "agent.sqlite"),
                market_client=market_client,
                collector=AutoHotCollector(["HOTUSDT", "ALTUSDT"]),
                narrative_runner=AutoHotNarrativeRunner(["HOTUSDT", "ALTUSDT"]),
                ai_client=FakeAiClient(),
                top_n=1,
            )

        self.assertEqual(result.scan_symbols, ["HOTUSDT", "ALTUSDT"])
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(len(result.evaluated_symbols), 1)
        self.assertIn(result.selected_symbol, {"HOTUSDT", "ALTUSDT"})
        self.assertIn(("ticker_24hr", None), market_client.calls)

    def test_run_once_auto_hot_falls_back_to_market_symbols_when_empty(self):
        class EmptyHotMarketClient(FakeMarketClient):
            def __init__(self):
                self.calls = []

            def ticker_24hr(self, symbol=None):
                self.calls.append(("ticker_24hr", symbol))
                return MarketDataResponse(
                    endpoint="/fapi/v1/ticker/24hr",
                    params={},
                    payload=[
                        {"symbol": "SLOWUSDT", "priceChangePercent": "0.1", "quoteVolume": "100000000", "count": 1000}
                    ],
                )

            def exchange_info(self):
                self.calls.append(("exchange_info",))
                return MarketDataResponse(endpoint="/fapi/v1/exchangeInfo", params={}, payload=exchange_info_payload())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            market_client = EmptyHotMarketClient()
            config = load_config(
                {
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_LIVE_AUTO_HOT_SYMBOLS": "true",
                    "BFA_LIVE_AUTO_HOT_MIN_ABS_PRICE_CHANGE_PERCENT": "5",
                    "BFA_DB_PATH": str(root / "agent.sqlite"),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                }
            )

            result = run_agent_once(
                config=config,
                db_path=str(root / "agent.sqlite"),
                market_client=market_client,
                collector=FakeCollector(),
                narrative_runner=FakeNarrativeRunner(),
                ai_client=FakeAiClient(),
            )

        self.assertEqual(result.scan_symbols, ["BTCUSDT"])
        self.assertEqual(result.selected_symbol, "BTCUSDT")
        self.assertIn(("ticker_24hr", None), market_client.calls)

    def test_run_once_forward_paper_guard_rejects_blocked_symbol_before_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "agent.sqlite"
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            from bfa.event_store.store import EventStore

            store = EventStore(connection)
            for index in range(3):
                signal_id = store.insert_artifact(
                    "paper_signals",
                    occurred_at=f"2026-06-20T00:0{index}:00Z",
                    source="test",
                    symbol="BTCUSDT",
                    ref_id=f"paper_signal:btc:{index}",
                    event_type="paper_signal",
                    payload={
                        "schema": "bfa_paper_signal_v1",
                        "symbol": "BTCUSDT",
                        "interval": "5m",
                        "variant": "quant_setup_selective",
                        "opened_at": f"2026-06-20T00:0{index}:00Z",
                        "expiry_time": "2026-06-20T00:20:00Z",
                        "side": "long",
                        "entry_price": 100.0,
                        "stop_price": 98.0,
                        "target_price": 104.0,
                        "notional_usdt": 12.0,
                        "hold_bars": 4,
                        "status": "open",
                        "setup": {"factor_scores": []},
                    },
                )
                store.insert_artifact(
                    "paper_outcomes",
                    occurred_at=f"2026-06-20T01:0{index}:00Z",
                    source="test",
                    symbol="BTCUSDT",
                    ref_id=f"paper_outcome:btc:{index}",
                    event_type="paper_outcome",
                    payload={
                        "schema": "bfa_paper_outcome_v1",
                        "signal_event_id": signal_id,
                        "symbol": "BTCUSDT",
                        "interval": "5m",
                        "variant": "quant_setup_selective",
                        "opened_at": f"2026-06-20T00:0{index}:00Z",
                        "closed_at": f"2026-06-20T01:0{index}:00Z",
                        "side": "long",
                        "entry_price": 100.0,
                        "exit_price": 98.0,
                        "quantity": 0.12,
                        "notional_usdt": 12.0,
                        "gross_pnl_usdt": -0.3,
                        "fees_usdt": 0.0,
                        "slippage_usdt": 0.0,
                        "net_pnl_usdt": -0.3,
                        "exit_reason": "stop_loss",
                    },
                )
            connection.close()
            ai_client = FakeAiClient()
            config = load_config(
                {
                    "BFA_MODE": "dry_run",
                    "BFA_OPENAI_ENABLED": "true",
                    "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                    "BFA_MARKET_SYMBOLS": "BTCUSDT",
                    "BFA_DB_PATH": str(db_path),
                    "BFA_RUNTIME_DIR": str(root / "runtime"),
                    "SQUARE_EXPORT_DIR": str(root / "runtime" / "square_exports"),
                    "BFA_FORWARD_PAPER_GUARD_MIN_TOTAL_OUTCOMES": "3",
                    "BFA_FORWARD_PAPER_GUARD_MIN_SYMBOL_OUTCOMES": "3",
                    "BFA_FORWARD_PAPER_GUARD_SYMBOL_MIN_LOSS_USDT": "0.5",
                    "BFA_FORWARD_PAPER_GUARD_SYMBOL_MAX_WIN_RATE": "0.1",
                }
            )

            result = run_agent_once(
                config=config,
                db_path=str(db_path),
                market_client=FakeMarketClient(),
                collector=FakeCollector(),
                narrative_runner=FakeNarrativeRunner(),
                ai_client=ai_client,
            )

        self.assertEqual(result.status, "no_candidate")
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(ai_client.calls, 0)
        self.assertEqual(result.paper_guard["status"], "active")
        self.assertIn("BTCUSDT", result.paper_guard["symbol_blocks"])


if __name__ == "__main__":
    unittest.main()
