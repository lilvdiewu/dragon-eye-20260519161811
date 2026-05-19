"""
dragon_eye.strategy — 龙瞳Pro选股策略引擎

策略:
  - BottomBreakout  底部潜伏
  - PullbackBuy     缩量蓄势
  - MA120Reversal   MA120踩穿反转
  - CompositeScreener 综合选股引擎

扫描:
  - Screener 全市场扫描器
  - BacktestEngine 回测引擎
"""
from __future__ import annotations

from .base_strategy import BaseStrategy, StrategyResult
from .bottom_breakout import BottomBreakout
from .pullback_buy import PullbackBuy
from .ma120_reversal import MA120Reversal
from .composite_screener import CompositeScreener, CompositeResult
from .screener import Screener
from .backtest import BacktestEngine, BacktestResult, BacktestTrade

__all__ = [
    "BaseStrategy",
    "StrategyResult",
    "BottomBreakout",
    "PullbackBuy",
    "MA120Reversal",
    "CompositeScreener",
    "CompositeResult",
    "Screener",
    "BacktestEngine",
    "BacktestResult",
    "BacktestTrade",
]
