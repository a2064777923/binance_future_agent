import unittest

from bfa.config import RuntimeMode, load_config, market_symbols, rss_feed_urls, telegram_channels, validate_config


PILOT_SYMBOLS = [
    "HYPEUSDT",
    "SOLUSDT",
    "ZECUSDT",
    "WLDUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "NEARUSDT",
    "ADAUSDT",
]


def base_env(**overrides):
    env = {
        "BFA_MODE": "dry_run",
        "BFA_OPENAI_ENABLED": "false",
        "BFA_ACCOUNT_CAPITAL_USDT": "100",
        "BFA_MAX_LEVERAGE": "3",
        "BFA_MAX_POSITION_NOTIONAL_USDT": "20",
        "BFA_MAX_RISK_PER_TRADE_USDT": "1",
        "BFA_MAX_DAILY_LOSS_USDT": "3",
        "BFA_MAX_OPEN_POSITIONS": "2",
        "BFA_KILL_SWITCH_FILE": "/tmp/binance-futures-agent/KILL_SWITCH",
        "BFA_DB_PATH": "/tmp/binance-futures-agent/data/agent.sqlite",
        "BFA_LOG_DIR": "/tmp/binance-futures-agent/logs",
        "BFA_RUNTIME_DIR": "/tmp/binance-futures-agent/runtime",
        "BFA_MARKET_SYMBOLS": ",".join(PILOT_SYMBOLS),
        "BFA_MARKET_HEAT_NARRATIVE_ENABLED": "true",
        "BFA_MARKET_HEAT_MIN_QUOTE_VOLUME_USDT": "5000000",
        "BFA_MARKET_HEAT_MIN_PRICE_CHANGE_PERCENT": "0.3",
        "BFA_MARKET_HEAT_MIN_TAKER_BUY_SELL_RATIO": "1.05",
        "BFA_MARKET_HEAT_MIN_OPEN_INTEREST_VALUE_USDT": "1000000",
        "BFA_MARKET_HEAT_MAX_KLINE_RANGE_PERCENT": "15",
        "BFA_MARKET_HEAT_MAX_RECORDS": "3",
        "BINANCE_API_KEY": "",
        "BINANCE_API_SECRET": "",
        "BINANCE_FUTURES_BASE_URL": "https://fapi.binance.com",
        "BINANCE_FUTURES_WS_BASE_URL": "wss://fstream.binance.com",
        "BINANCE_USE_TESTNET": "false",
        "OPENAI_API_KEY": "",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "OPENAI_MODEL": "gpt-5.4",
        "OPENAI_RETRY_AFTER_SECONDS": "300",
    }
    env.update(overrides)
    return env


class ConfigTests(unittest.TestCase):
    def test_dry_run_passes_without_binance_credentials(self):
        config = load_config(base_env())
        result = validate_config(config)

        self.assertTrue(result.valid)
        self.assertEqual(result.mode, RuntimeMode.DRY_RUN)
        self.assertEqual(result.errors, [])

    def test_market_symbols_default_to_small_controlled_allowlist(self):
        config = load_config({})

        self.assertEqual(market_symbols(config), PILOT_SYMBOLS)

    def test_market_symbols_are_trimmed_uppercased_and_ordered(self):
        config = load_config(base_env(BFA_MARKET_SYMBOLS=" btcusdt, ethusdt,,solusdt "))

        self.assertEqual(market_symbols(config), ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    def test_narrative_source_lists_are_trimmed_and_ordered(self):
        config = load_config(
            base_env(
                RSS_FEED_URLS=" https://news.example.test/rss.xml,https://blog.example.test/feed.xml ",
                TELEGRAM_CHANNELS=" SquareWatch, hotcoins ",
            )
        )

        self.assertEqual(
            rss_feed_urls(config),
            ["https://news.example.test/rss.xml", "https://blog.example.test/feed.xml"],
        )
        self.assertEqual(telegram_channels(config), ["SquareWatch", "hotcoins"])

    def test_testnet_requires_binance_credentials(self):
        config = load_config(base_env(BFA_MODE="testnet"))
        result = validate_config(config)

        self.assertFalse(result.valid)
        self.assertIn("BINANCE_API_KEY is required for testnet mode", result.errors)
        self.assertIn("BINANCE_API_SECRET is required for testnet mode", result.errors)

    def test_live_requires_binance_credentials(self):
        config = load_config(base_env(BFA_MODE="live"))
        result = validate_config(config)

        self.assertFalse(result.valid)
        self.assertIn("BINANCE_API_KEY is required for live mode", result.errors)
        self.assertIn("BINANCE_API_SECRET is required for live mode", result.errors)

    def test_live_requires_kill_switch_path_and_risk_caps(self):
        config = load_config(
            base_env(
                BFA_MODE="live",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
                BFA_KILL_SWITCH_FILE="",
                BFA_MAX_POSITION_NOTIONAL_USDT="",
                BFA_MAX_RISK_PER_TRADE_USDT="0",
                BFA_MAX_DAILY_LOSS_USDT="-1",
            )
        )
        result = validate_config(config)

        self.assertFalse(result.valid)
        self.assertIn("BFA_KILL_SWITCH_FILE is required for live mode", result.errors)
        self.assertIn("BFA_MAX_POSITION_NOTIONAL_USDT must be a positive number", result.errors)
        self.assertIn("BFA_MAX_RISK_PER_TRADE_USDT must be a positive number", result.errors)
        self.assertIn("BFA_MAX_DAILY_LOSS_USDT must be a positive number", result.errors)

    def test_live_requires_protective_orders(self):
        config = load_config(
            base_env(
                BFA_MODE="live",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
                BFA_REQUIRE_PROTECTIVE_ORDERS="false",
            )
        )
        result = validate_config(config)

        self.assertFalse(result.valid)
        self.assertIn("BFA_REQUIRE_PROTECTIVE_ORDERS must be true for live mode", result.errors)

    def test_unknown_mode_fails(self):
        config = load_config(base_env(BFA_MODE="reckless"))
        result = validate_config(config)

        self.assertFalse(result.valid)
        self.assertIn("BFA_MODE must be one of: dry_run, testnet, live", result.errors)

    def test_invalid_numeric_risk_values_fail(self):
        config = load_config(
            base_env(
                BFA_ACCOUNT_CAPITAL_USDT="lots",
                BFA_MAX_LEVERAGE="-3",
                BFA_MAX_OPEN_POSITIONS="0",
                BFA_MARKET_HEAT_MIN_QUOTE_VOLUME_USDT="0",
                BFA_MARKET_HEAT_MAX_RECORDS="0",
            )
        )
        result = validate_config(config)

        self.assertFalse(result.valid)
        self.assertIn("BFA_ACCOUNT_CAPITAL_USDT must be a positive number", result.errors)
        self.assertIn("BFA_MAX_LEVERAGE must be a positive number", result.errors)
        self.assertIn("BFA_MAX_OPEN_POSITIONS must be a positive integer", result.errors)
        self.assertIn("BFA_MARKET_HEAT_MIN_QUOTE_VOLUME_USDT must be a positive number", result.errors)
        self.assertIn("BFA_MARKET_HEAT_MAX_RECORDS must be a positive integer", result.errors)

    def test_invalid_openai_latency_controls_fail(self):
        config = load_config(
            base_env(
                OPENAI_TIMEOUT_SECONDS="0",
                OPENAI_MAX_OUTPUT_TOKENS="0",
                OPENAI_RETRY_AFTER_SECONDS="0",
            )
        )
        result = validate_config(config)

        self.assertFalse(result.valid)
        self.assertIn("OPENAI_TIMEOUT_SECONDS must be a positive number", result.errors)
        self.assertIn("OPENAI_MAX_OUTPUT_TOKENS must be a positive integer", result.errors)
        self.assertIn("OPENAI_RETRY_AFTER_SECONDS must be a positive number", result.errors)

    def test_openai_enabled_requires_openai_key(self):
        config = load_config(base_env(BFA_OPENAI_ENABLED="true"))
        result = validate_config(config)

        self.assertFalse(result.valid)
        self.assertIn("OPENAI_API_KEY is required when BFA_OPENAI_ENABLED=true", result.errors)

    def test_loader_ignores_unknown_environment_keys(self):
        config = load_config(base_env(UNRELATED_PUBLIC_PATH="do-not-print-me"))

        self.assertNotIn("UNRELATED_PUBLIC_PATH", config.values)

    def test_redacted_summary_excludes_sensitive_inputs(self):
        config = load_config(
            base_env(
                BFA_MODE="live",
                BINANCE_API_KEY="synthetic-binance-key-abcdef",
                BINANCE_API_SECRET="synthetic-binance-secret-abcdef",
                OPENAI_API_KEY="synthetic-openai-key-abcdef",
                BFA_OPENAI_ENABLED="true",
            )
        )
        result = validate_config(config)
        summary_text = repr(result.redacted)

        self.assertNotIn("synthetic-binance-key-abcdef", summary_text)
        self.assertNotIn("synthetic-binance-secret-abcdef", summary_text)
        self.assertNotIn("synthetic-openai-key-abcdef", summary_text)
        self.assertIn("live", summary_text)


if __name__ == "__main__":
    unittest.main()
