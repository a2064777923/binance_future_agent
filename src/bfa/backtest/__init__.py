"""Small-capital backtesting utilities for Binance futures strategies."""

from bfa.backtest.engine import run_hot_momentum_backtest, run_staged_sweep
from bfa.backtest.matrix import BacktestMatrixConfig, HotUniverseConfig, run_hot_backtest_matrix, select_hot_usdt_symbols
from bfa.backtest.models import BacktestBar, BacktestConfig, BacktestResult

__all__ = [
    "BacktestBar",
    "BacktestConfig",
    "BacktestMatrixConfig",
    "BacktestResult",
    "HotUniverseConfig",
    "run_hot_momentum_backtest",
    "run_hot_backtest_matrix",
    "run_staged_sweep",
    "select_hot_usdt_symbols",
]
