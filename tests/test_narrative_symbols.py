import unittest

from bfa.narrative.symbols import extract_symbol_mentions


class NarrativeSymbolTests(unittest.TestCase):
    def test_extracts_explicit_pairs_slash_dash_and_cashtags(self):
        result = extract_symbol_mentions(
            "ESPORTSUSDT broke out while BTC/USDT holds and ETH-USDT follows $SOL.",
            known_symbols=["SOLUSDT"],
        )

        self.assertEqual(result.symbols, ["ESPORTSUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"])
        self.assertEqual(result.quality_flags, [])

    def test_bare_base_requires_known_symbol_allowlist(self):
        without_allowlist = extract_symbol_mentions("ETH is strong")
        with_allowlist = extract_symbol_mentions("ETH is strong", known_symbols=["ETHUSDT"])

        self.assertEqual(without_allowlist.symbols, [])
        self.assertIn("ambiguous_symbol_mentions", without_allowlist.quality_flags)
        self.assertEqual(with_allowlist.symbols, ["ETHUSDT"])

    def test_deduplicates_symbols_in_first_seen_order(self):
        result = extract_symbol_mentions(
            "BTCUSDT $BTC BTC/USDT SOLUSDT $SOL",
            known_symbols=["BTCUSDT", "SOLUSDT"],
        )

        self.assertEqual(result.symbols, ["BTCUSDT", "SOLUSDT"])

    def test_no_symbol_mentions_flag(self):
        result = extract_symbol_mentions("market looks hot but no ticker here")

        self.assertEqual(result.symbols, [])
        self.assertIn("no_symbol_mentions", result.quality_flags)


if __name__ == "__main__":
    unittest.main()

