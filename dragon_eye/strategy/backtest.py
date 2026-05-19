"""
dragon_eye.strategy.backtest — 策略回测引擎

遍历历史数据，模拟策略信号触发、买入、持仓、卖出。
支持A股T+1规则，最长持仓20天。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ..data_models import Kline, Market
from ..tdx_reader import TdxReader, get_reader
from .base_strategy import BaseStrategy, StrategyResult


# ============================================================
# 回测数据类
# ============================================================

@dataclass
class BacktestTrade:
    """单笔回测交易"""
    entry_date: str                  # 买入日期
    entry_price: float               # 买入价格
    exit_date: str = ""              # 卖出日期
    exit_price: float = 0.0          # 卖出价格
    exit_reason: str = ""            # take_profit / stop_loss / timeout / signal_reverse
    pnl_pct: float = 0.0            # 盈亏百分比
    hold_days: int = 0               # 持仓天数


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    code: str = ""
    trades: list[BacktestTrade] = field(default_factory=list)
    total_return: float = 0.0        # 总收益率%
    win_rate: float = 0.0            # 胜率%
    max_drawdown: float = 0.0        # 最大回撤%
    sharpe_ratio: float = 0.0        # 夏普比率
    total_trades: int = 0
    avg_hold_days: float = 0.0


# ============================================================
# 回测引擎
# ============================================================

MAX_HOLD_DAYS = 20  # 最长持仓天数


class BacktestEngine:
    """策略回测引擎"""

    def __init__(self, strategy: BaseStrategy):
        self.strategy = strategy
        self.reader = get_reader()

    def run(self, code6: str, market: Market,
            start_date: str, end_date: str,
            initial_capital: float = 100000.0) -> BacktestResult:
        """单股回测

        遍历历史数据，每个交易日用strategy.scan检测信号。
        信号触发后买入，设置止损/止盈。
        持仓期间每日检查止损/止盈条件。
        最长持仓20天自动平仓。

        Args:
            code6: 6位股票代码
            market: 市场
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            initial_capital: 初始资金

        Returns:
            BacktestResult
        """
        result = BacktestResult(
            strategy_name=self.strategy.name,
            code=code6,
        )

        # 读取完整K线
        all_klines = self.reader.get_day_klines(code6, market)
        if not all_klines:
            return result

        # 过滤到回测区间
        klines_in_range = [
            k for k in all_klines
            if start_date <= k.date <= end_date
        ]

        if len(klines_in_range) < 60:
            return result

        # 生成日期索引，方便查找
        date_index = {k.date: i for i, k in enumerate(all_klines)}

        trades: list[BacktestTrade] = []
        position: Optional[BacktestTrade] = None  # 当前持仓
        position_entry_idx: int = 0  # 在all_klines中的买入索引

        # 从有60日数据的起点开始
        start_idx = 0
        for i, k in enumerate(all_klines):
            if k.date >= start_date:
                start_idx = i
                break

        for i in range(start_idx, len(all_klines)):
            cur_kline = all_klines[i]

            # 超出回测区间
            if cur_kline.date > end_date:
                break

            # ---- 持仓中: 检查止损/止盈/超时 ----
            if position is not None:
                hold_days = i - position_entry_idx

                # T+1: 买入当天不能卖出
                can_sell = hold_days >= 1

                if can_sell:
                    # 检查止损
                    if cur_kline.low <= position.entry_price * 0.95:
                        # 简化：用止损价成交（实际可能更低）
                        exit_price = round(position.entry_price * 0.95, 2)
                        position.exit_date = cur_kline.date
                        position.exit_price = exit_price
                        position.exit_reason = "stop_loss"
                        position.hold_days = hold_days
                        position.pnl_pct = round(
                            (exit_price - position.entry_price) / position.entry_price * 100, 2
                        )
                        trades.append(position)
                        position = None
                        continue

                    # 检查止盈（目标价）
                    if cur_kline.high >= position.exit_price * 1.0:
                        # exit_price在策略信号中存放了target_price
                        # 这里需要从details中获取
                        pass  # 下面统一处理

                # 超时平仓
                if hold_days >= MAX_HOLD_DAYS and can_sell:
                    exit_price = cur_kline.close
                    position.exit_date = cur_kline.date
                    position.exit_price = round(exit_price, 2)
                    position.exit_reason = "timeout"
                    position.hold_days = hold_days
                    position.pnl_pct = round(
                        (exit_price - position.entry_price) / position.entry_price * 100, 2
                    )
                    trades.append(position)
                    position = None
                    continue

                # 每日检查止损（用策略信号的止损价）
                if can_sell and hasattr(position, '_stop_loss'):
                    stop = position._stop_loss  # type: ignore
                    if cur_kline.low <= stop:
                        exit_price = round(stop, 2)
                        position.exit_date = cur_kline.date
                        position.exit_price = exit_price
                        position.exit_reason = "stop_loss"
                        position.hold_days = hold_days
                        position.pnl_pct = round(
                            (exit_price - position.entry_price) / position.entry_price * 100, 2
                        )
                        trades.append(position)
                        position = None
                        continue

                # 检查止盈（用策略信号的目标价）
                if can_sell and hasattr(position, '_target_price'):
                    target = position._target_price  # type: ignore
                    if cur_kline.high >= target:
                        exit_price = round(target, 2)
                        position.exit_date = cur_kline.date
                        position.exit_price = exit_price
                        position.exit_reason = "take_profit"
                        position.hold_days = hold_days
                        position.pnl_pct = round(
                            (exit_price - position.entry_price) / position.entry_price * 100, 2
                        )
                        trades.append(position)
                        position = None
                        continue

            # ---- 空仓: 检测买入信号 ----
            if position is None:
                # 需要至少60日数据
                if i < 59:
                    continue

                # 取当前日期及之前的K线用于策略扫描
                historical = all_klines[:i + 1]
                sig = self.strategy.scan(historical, code=code6)

                if sig.triggered and sig.entry_price > 0:
                    # 用次日开盘价买入（更真实）
                    if i + 1 < len(all_klines):
                        next_kline = all_klines[i + 1]
                        if next_kline.date > end_date:
                            continue
                        entry_price = next_kline.open
                        entry_date = next_kline.date
                        entry_idx = i + 1
                    else:
                        continue

                    trade = BacktestTrade(
                        entry_date=entry_date,
                        entry_price=round(entry_price, 2),
                    )
                    # 保存止损/止盈价（用内部属性）
                    trade._stop_loss = sig.stop_loss  # type: ignore
                    trade._target_price = sig.target_price  # type: ignore
                    trade.exit_price = sig.target_price  # 临时存目标价

                    position = trade
                    position_entry_idx = entry_idx

        # ---- 回测结束，平仓未平持仓 ----
        if position is not None and len(all_klines) > 0:
            last_kline = all_klines[-1]
            exit_price = last_kline.close
            hold_days = len(all_klines) - 1 - position_entry_idx
            position.exit_date = last_kline.date
            position.exit_price = round(exit_price, 2)
            position.exit_reason = "end_of_backtest"
            position.hold_days = max(1, hold_days)
            position.pnl_pct = round(
                (exit_price - position.entry_price) / position.entry_price * 100, 2
            )
            trades.append(position)

        # ---- 统计结果 ----
        result.trades = trades
        result.total_trades = len(trades)

        if trades:
            # 总收益
            pnls = [t.pnl_pct for t in trades]
            result.total_return = round(sum(pnls), 2)

            # 胜率
            wins = sum(1 for t in trades if t.pnl_pct > 0)
            result.win_rate = round(wins / len(trades) * 100, 1)

            # 平均持仓天数
            result.avg_hold_days = round(
                sum(t.hold_days for t in trades) / len(trades), 1
            )

            # 最大回撤
            result.max_drawdown = self._calc_max_drawdown(trades)

            # 夏普比率（简化）
            result.sharpe_ratio = self._calc_sharpe(pnls)

        return result

    def run_batch(self, codes: list[tuple[str, Market]],
                  start_date: str, end_date: str) -> list[BacktestResult]:
        """批量回测

        Args:
            codes: [(code6, market), ...]
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            回测结果列表
        """
        results = []
        for code6, market in codes:
            r = self.run(code6, market, start_date, end_date)
            results.append(r)
        return results

    def summarize(self, results: list[BacktestResult]) -> dict:
        """汇总回测统计

        Args:
            results: 回测结果列表

        Returns:
            汇总统计字典
        """
        if not results:
            return {}

        valid = [r for r in results if r.total_trades > 0]

        if not valid:
            return {
                "total_stocks": len(results),
                "valid_stocks": 0,
                "total_trades": 0,
            }

        total_trades = sum(r.total_trades for r in valid)
        avg_return = sum(r.total_return for r in valid) / len(valid)
        avg_win_rate = sum(r.win_rate for r in valid) / len(valid)
        avg_drawdown = sum(r.max_drawdown for r in valid) / len(valid)
        avg_sharpe = sum(r.sharpe_ratio for r in valid) / len(valid)

        # 最好/最差
        best = max(valid, key=lambda r: r.total_return)
        worst = min(valid, key=lambda r: r.total_return)

        # 盈利股票占比
        profitable = sum(1 for r in valid if r.total_return > 0)

        return {
            "total_stocks": len(results),
            "valid_stocks": len(valid),
            "total_trades": total_trades,
            "avg_return_pct": round(avg_return, 2),
            "avg_win_rate": round(avg_win_rate, 1),
            "avg_max_drawdown": round(avg_drawdown, 2),
            "avg_sharpe": round(avg_sharpe, 2),
            "best_stock": {"code": best.code, "return": best.total_return},
            "worst_stock": {"code": worst.code, "return": worst.total_return},
            "profitable_ratio": round(profitable / len(valid) * 100, 1),
        }

    # ---- 内部方法 ----

    @staticmethod
    def _calc_max_drawdown(trades: list[BacktestTrade]) -> float:
        """计算最大回撤（基于累计收益）"""
        if not trades:
            return 0.0

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0

        for t in trades:
            cumulative += t.pnl_pct
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return round(max_dd, 2)

    @staticmethod
    def _calc_sharpe(pnls: list[float], annual_factor: float = 252.0) -> float:
        """简化夏普比率计算"""
        if len(pnls) < 2:
            return 0.0

        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std_pnl = math.sqrt(variance) if variance > 0 else 0.001

        # 年化
        sharpe = (mean_pnl / std_pnl) * math.sqrt(annual_factor)
        return round(sharpe, 2)
