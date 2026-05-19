"""
dragon_eye.strategy.screener — 全市场扫描器

通达信8900只极速扫，先粗筛再精扫。
"""
from __future__ import annotations

import time
from typing import Optional

from ..tdx_reader import TdxReader, get_reader
from ..stock_list import StockList, get_stock_list
from ..data_models import Market, StockInfo
from .base_strategy import BaseStrategy, StrategyResult
from .bottom_breakout import BottomBreakout
from .pullback_buy import PullbackBuy


class Screener:
    """全市场扫描器 — 通达信8900只极速扫"""

    def __init__(self, strategies: list[BaseStrategy] | None = None):
        self.strategies = strategies or [BottomBreakout(), PullbackBuy()]
        self.reader = get_reader()
        self.stock_list = get_stock_list()

    def _get_strategy(self, strategy_name: str | None = None) -> list[BaseStrategy]:
        """获取要执行的策略列表"""
        if strategy_name is None:
            return self.strategies
        return [s for s in self.strategies if s.name == strategy_name]

    def scan_all(self, strategy_name: str | None = None,
                 min_days: int = 60) -> list[StrategyResult]:
        """全市场扫描

        用TdxReader批量读取日K线，然后对每只股票应用策略
        预期: 8900只 < 60秒

        Args:
            strategy_name: 策略名，None=所有策略
            min_days: 最少K线天数（数据不足的跳过）

        Returns:
            触发信号的策略结果列表
        """
        strategies = self._get_strategy(strategy_name)
        stocks = self.stock_list.get_all()
        all_results: list[StrategyResult] = []

        t0 = time.time()

        # 批量读取所有股票日K线
        stock_pairs = [(s.code, s.market) for s in stocks]
        batch_data = self.reader.get_day_klines_batch(stock_pairs)

        print(f"[Screener] 读取 {len(batch_data)}/{len(stocks)} 只股票K线 "
              f"({time.time() - t0:.1f}s)")

        # 过滤数据不足的股票
        valid_data = {
            code: klines
            for code, klines in batch_data.items()
            if len(klines) >= min_days
        }

        print(f"[Screener] 有效股票 {len(valid_data)} 只 (>= {min_days}天)")

        # 逐策略扫描
        scan_t0 = time.time()
        for strategy in strategies:
            results = strategy.scan_batch(valid_data)
            all_results.extend(results)
            print(f"[Screener] {strategy.name}: {len(results)} 只触发")

        # 按信号强度全局排序
        all_results.sort(key=lambda r: r.strength, reverse=True)

        print(f"[Screener] 扫描完成: {len(all_results)} 只触发 "
              f"(扫描耗时 {time.time() - scan_t0:.1f}s, "
              f"总耗时 {time.time() - t0:.1f}s)")

        return all_results

    def scan_sector(self, sector_code: str,
                    strategy_name: str | None = None) -> list[StrategyResult]:
        """按板块扫描

        Args:
            sector_code: 板块代码
            strategy_name: 策略名

        Returns:
            触发信号的策略结果列表
        """
        strategies = self._get_strategy(strategy_name)

        # 尝试从AkShare获取板块成分股
        try:
            from ..akshare_bridge import get_bridge
            bridge = get_bridge()
            codes = bridge.get_sector_stocks(sector_code)
        except Exception:
            print(f"[Screener] 无法获取板块 {sector_code} 成分股")
            return []

        if not codes:
            return []

        # 读取K线
        stock_data = {}
        for code6 in codes:
            from ..data_models import market_from_code
            market = market_from_code(code6)
            klines = self.reader.get_day_klines(code6, market)
            if klines and len(klines) >= 30:
                stock_data[code6] = klines

        # 扫描
        all_results = []
        for strategy in strategies:
            results = strategy.scan_batch(stock_data)
            all_results.extend(results)

        all_results.sort(key=lambda r: r.strength, reverse=True)
        return all_results

    def scan_watchlist(self, codes: list[str],
                       strategy_name: str | None = None) -> list[StrategyResult]:
        """扫描自选股

        Args:
            codes: 股票代码列表
            strategy_name: 策略名

        Returns:
            触发信号的策略结果列表
        """
        strategies = self._get_strategy(strategy_name)

        # 读取K线
        stock_data = {}
        for code6 in codes:
            from ..data_models import market_from_code
            market = market_from_code(code6)
            klines = self.reader.get_day_klines(code6, market)
            if klines:
                stock_data[code6] = klines

        # 扫描
        all_results = []
        for strategy in strategies:
            results = strategy.scan_batch(stock_data)
            all_results.extend(results)

        all_results.sort(key=lambda r: r.strength, reverse=True)
        return all_results

    def quick_scan(self, top_n: int = 50) -> list[StrategyResult]:
        """快速扫描 — 只看近几日有异动的股

        先粗筛（放量/涨幅>3%），再精扫。
        速度比全市场扫描快5-10倍。

        Args:
            top_n: 最多返回N只

        Returns:
            触发信号的策略结果列表
        """
        stocks = self.stock_list.get_all()
        t0 = time.time()

        # ---- 粗筛: 找近3日有异动的股票 ----
        candidates: dict[str, list] = {}

        for stock in stocks:
            klines = self.reader.get_day_klines(stock.code, stock.market)
            if not klines or len(klines) < 25:
                continue

            recent = klines[-5:] if len(klines) >= 5 else klines

            # 异动条件: 近3日涨幅>3% 或 近1日涨幅>5%
            has_big_gain = False
            has_volume_surge = False

            if len(recent) >= 4:
                gain_3d = (recent[-1].close - recent[-4].close) / recent[-4].close * 100
                if gain_3d > 3:
                    has_big_gain = True

            if recent[-1].change_pct is not None and recent[-1].change_pct > 5:
                has_big_gain = True

            # 放量: 当日量 > 5日均量 * 2
            if len(klines) >= 6:
                avg_vol_5 = sum(k.volume for k in klines[-6:-1]) / 5
                if avg_vol_5 > 0 and klines[-1].volume > avg_vol_5 * 2:
                    has_volume_surge = True

            if has_big_gain or has_volume_surge:
                candidates[stock.code] = klines

        print(f"[Screener] 粗筛: {len(candidates)}/{len(stocks)} 只异动 "
              f"({time.time() - t0:.1f}s)")

        # ---- 精扫: 对候选股应用策略 ----
        all_results = []
        for strategy in self.strategies:
            results = strategy.scan_batch(candidates)
            all_results.extend(results)

        all_results.sort(key=lambda r: r.strength, reverse=True)

        print(f"[Screener] 快速扫描完成: {len(all_results)} 只触发 "
              f"(总耗时 {time.time() - t0:.1f}s)")

        return all_results[:top_n]
