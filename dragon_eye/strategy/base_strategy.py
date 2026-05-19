"""
dragon_eye.strategy.base_strategy — 策略基类

所有选股策略继承此类，实现 scan() 方法。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ..data_models import Kline, Market


@dataclass
class StrategyResult:
    """策略输出结果"""
    code: str                          # 6位代码
    name: str = ""                     # 股票名称
    signal_type: str = ""              # 信号类型: bottom_breakout / pullback_buy
    triggered: bool = False            # 是否触发
    strength: float = 0.0              # 信号强度 0-100
    entry_price: float = 0.0           # 建议买入价
    stop_loss: float = 0.0             # 止损价
    target_price: float = 0.0         # 目标价
    risk_reward: float = 0.0           # 风险收益比
    details: dict = field(default_factory=dict)   # 详细信息
    score: dict = field(default_factory=dict)      # 评分明细


class BaseStrategy(ABC):
    """策略基类"""

    name: str = "base"
    description: str = ""

    @abstractmethod
    def scan(self, klines: list[Kline], **kwargs) -> StrategyResult:
        """扫描单只股票

        Args:
            klines: 日K线数据
            **kwargs: 可选参数 code(代码) name(名称)

        Returns:
            StrategyResult
        """
        pass

    def scan_batch(self, stock_data: dict[str, list[Kline]], **kwargs) -> list[StrategyResult]:
        """批量扫描

        Args:
            stock_data: {code: [Kline, ...], ...}

        Returns:
            触发信号的策略结果列表，按信号强度降序
        """
        results = []
        for code, klines in stock_data.items():
            result = self.scan(klines, code=code, **kwargs)
            if result and result.triggered:
                results.append(result)
        results.sort(key=lambda r: r.strength, reverse=True)
        return results
