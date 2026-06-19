import json
import unittest
from pathlib import Path

from bfa.execution.filters import SymbolExecutionFilters


FIXTURE = Path(__file__).parent / "fixtures" / "binance_market" / "exchange_info.json"


class ExecutionFilterTests(unittest.TestCase):
    def load_exchange_info(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_parses_symbol_filters_and_rounds_down(self):
        filters = SymbolExecutionFilters.from_exchange_info(self.load_exchange_info(), "BTCUSDT")

        values = filters.apply(
            quantity=0.0019,
            entry_price=100.19,
            stop_price=96.17,
            target_price=108.99,
        )

        self.assertEqual(values.quantity, 0.001)
        self.assertEqual(values.entry_price, 100.1)
        self.assertEqual(values.stop_price, 96.1)
        self.assertEqual(values.target_price, 108.9)
        self.assertEqual(values.rejection_reasons, ["notional_below_min"])

    def test_min_notional_passes_after_quantization(self):
        filters = SymbolExecutionFilters.from_exchange_info(self.load_exchange_info(), "BTCUSDT")

        values = filters.apply(
            quantity=0.2,
            entry_price=100.19,
            stop_price=96.17,
            target_price=108.99,
        )

        self.assertEqual(values.rejection_reasons, [])
        self.assertAlmostEqual(values.notional_usdt, 20.02)

    def test_unknown_symbol_is_rejected(self):
        with self.assertRaises(ValueError):
            SymbolExecutionFilters.from_exchange_info(self.load_exchange_info(), "NOTREALUSDT")


if __name__ == "__main__":
    unittest.main()
