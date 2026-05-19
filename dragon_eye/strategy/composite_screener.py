"""
dragon_eye.strategy.composite_screener — 综合选股策略引擎

将所有策略融合，结合板块热度、K线形态、技术趋势进行综合评分

综合评分 = 策略信号(40%) + K线形态(25%) + 板块热度(20%) + 趋势(15%)

策略信号来源:
  - 底部潜伏 (bottom_breakout)
  - 缩量蓄势 (pullback_buy)
  - MA120踩穿反转 (ma120_reversal)

K线形态:
  - 下影线/十字星/锤子线
  - 放量阳线
  - 涨停板打开

板块热度:
  - 行业板块强度
  - 概念板块热度
  - 板块轮动信号

趋势:
  - MA多头/空头排列
  - 均线角度
  - 趋势方向
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..data_models import Kline, Market
from ..signals import ma, atr, check_ma_cross, check_volume, check_stop_drop, check_breakout, check_ma_alignment, ma_angle
from ..tdx_reader import get_reader
from ..stock_list import get_stock_list
from .base_strategy import BaseStrategy, StrategyResult
from .bottom_breakout import BottomBreakout
from .pullback_buy import PullbackBuy
from .ma120_reversal import MA120Reversal


# ============================================================
# 综合评分结果
# ============================================================

@dataclass
class CompositeResult:
    """综合选股结果"""
    code: str
    name: str = ""
    # 四维评分
    strategy_score: float = 0.0     # 策略信号分 0-100
    pattern_score: float = 0.0      # K线形态分 0-100
    sector_score: float = 0.0       # 板块热度分 0-100
    trend_score: float = 0.0        # 趋势分 0-100
    # 综合分
    total_score: float = 0.0        # 综合分 0-100
    # 策略信号
    triggered_strategies: list[str] = field(default_factory=list)
    # 交易参数
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_price: float = 0.0
    risk_reward: float = 0.0
    # 板块信息
    industry: str = ""
    concepts: list[str] = field(default_factory=list)
    sector_signal: str = ""         # 板块轮动信号
    # 详细评分
    score_details: dict = field(default_factory=dict)


# ============================================================
# K线形态评分
# ============================================================

def score_pattern(klines: list[Kline]) -> float:
    """K线形态评分 0-100

    检测:
    - 下影线/锤子线/十字星（止跌信号）
    - 放量阳线（启动信号）
    - 缩量阴线（洗盘信号）
    """
    if len(klines) < 3:
        return 0.0

    score = 50.0  # 基础分
    recent = klines[-3:]  # 近3日K线

    # 1. 止跌信号（下影线/锤子线/十字星）
    for k in recent:
        body = abs(k.close - k.open)
        total = k.high - k.low
        if total <= 0:
            continue

        lower_shadow = min(k.open, k.close) - k.low
        upper_shadow = k.high - max(k.open, k.close)

        # 锤子线：下影线>2倍实体，上影线短
        if lower_shadow > body * 2 and upper_shadow < body * 0.5 and body > 0:
            score += 15
        # 十字星：实体<10%
        elif body / total < 0.1:
            score += 10
        # 下影线>60%
        elif lower_shadow / total > 0.6:
            score += 12

    # 2. 放量阳线
    if len(klines) >= 6:
        vol_5d = sum(k.volume for k in klines[-6:-1]) / 5
        last = klines[-1]
        if vol_5d > 0 and last.close > last.open:
            if last.volume > vol_5d * 1.5:
                score += 10  # 放量阳线
            if last.volume > vol_5d * 2.0:
                score += 5   # 大幅放量

    # 3. 缩量阴线（洗盘）
    if len(klines) >= 6:
        vol_5d = sum(k.volume for k in klines[-6:-1]) / 5
        last = klines[-1]
        if vol_5d > 0 and last.close < last.open:
            if last.volume < vol_5d * 0.7:
                score += 5  # 缩量阴线，洗盘可能

    return min(100, max(0, score))


def score_trend(klines: list[Kline]) -> float:
    """趋势评分 0-100

    基于:
    - MA多头/空头排列
    - 均线角度
    - 价格与MA位置关系
    """
    if len(klines) < 60:
        return 50.0

    score = 50.0

    # 1. 均线排列
    align = check_ma_alignment(klines)
    if align.direction == "bull":
        score += 20 if align.strength >= 80 else 10
    elif align.direction == "bear":
        score -= 20 if align.strength >= 80 else 10

    # 2. 均线角度
    ang10 = ma_angle(klines, 10)
    ang20 = ma_angle(klines, 20)

    if 15 < ang10 < 40:
        score += 10  # 健康上升角度
    elif ang10 < -15:
        score -= 10  # 下降趋势

    if 10 < ang20 < 30:
        score += 5

    # 3. 价格与MA20位置
    closes = [k.close for k in klines]
    ma20_vals = ma(closes, 20)
    if ma20_vals[-1] is not None:
        if closes[-1] > ma20_vals[-1]:
            score += 5  # 在MA20上方
        else:
            score -= 5

    return min(100, max(0, score))


# ============================================================
# 综合选股引擎
# ============================================================

class CompositeScreener:
    """综合选股引擎

    四维评分:
    - 策略信号(40%): 底部潜伏 + 缩量蓄势 + MA120踩穿反转
    - K线形态(25%): 止跌信号 + 放量阳线 + 缩量洗盘
    - 板块热度(20%): 行业/概念板块强度
    - 趋势(15%): MA排列 + 均线角度 + 价格位置

    用法:
        screener = CompositeScreener()
        results = screener.scan_all()
        results = screener.scan_with_sector_filter(min_sector_grade="A")
    """

    # 评分权重
    WEIGHTS = {
        "strategy": 0.40,
        "pattern": 0.25,
        "sector": 0.20,
        "trend": 0.15,
    }

    def __init__(self, strategies: list[BaseStrategy] | None = None):
        self.strategies = strategies or [
            BottomBreakout(),
            PullbackBuy(),
            MA120Reversal(),
        ]
        self.reader = get_reader()
        self.stock_list = get_stock_list()
        self._sector_cache: dict[str, tuple[str, list[str]]] = {}  # {code: (industry, [concepts])}

    def _load_sector_data(self):
        """加载板块归属数据"""
        if self._sector_cache:
            return

        try:
            from ..sector.ths_sector import get_mapper
            mapper = get_mapper()
            for code6, industry in mapper.industry_map.items():
                concepts = mapper.get_concepts(code6)
                self._sector_cache[code6] = (industry, concepts)
        except Exception as e:
            print(f"[CompositeScreener] 加载板块数据失败: {e}")

    def _get_sector_score(self, code6: str) -> tuple[float, str, list[str], str]:
        """获取板块热度评分

        Returns:
            (score, industry, concepts, signal)
        """
        self._load_sector_data()

        industry, concepts = self._sector_cache.get(code6, ("", []))

        if not industry:
            return 50.0, industry, concepts, ""  # 无数据给中位分

        # 尝试获取板块强度
        try:
            from ..sector.ths_sector import ThsSectorFetcher, SectorRanker
            fetcher = ThsSectorFetcher()
            ranker = SectorRanker()

            # 查找行业在排名中的位置
            industries = fetcher.get_industry_summary()
            if industries:
                ranked = ranker.rank(industries)
                for s in ranked:
                    if s.name == industry:
                        score = s.strength_score
                        signal = s.rotation_signal
                        return score, industry, concepts, signal
        except Exception:
            pass

        return 50.0, industry, concepts, ""

    def scan_stock(self, klines: list[Kline], code: str = "",
                   name: str = "") -> CompositeResult:
        """综合扫描单只股票

        Args:
            klines: 日K线数据
            code: 股票代码
            name: 股票名称

        Returns:
            CompositeResult
        """
        result = CompositeResult(code=code, name=name)

        if len(klines) < 60:
            return result

        # ---- 1. 策略信号评分(40%) ----
        max_strategy_score = 0.0
        triggered = []
        strategy_details = {}
        best_entry = 0.0
        best_stop = 0.0
        best_target = 0.0
        best_rr = 0.0

        for strategy in self.strategies:
            sr = strategy.scan(klines, code=code, name=name)
            if sr.triggered:
                triggered.append(strategy.name)
                if sr.strength > max_strategy_score:
                    max_strategy_score = sr.strength
                    best_entry = sr.entry_price
                    best_stop = sr.stop_loss
                    best_target = sr.target_price
                    best_rr = sr.risk_reward
                strategy_details[strategy.name] = {
                    "strength": sr.strength,
                    "entry": sr.entry_price,
                    "stop": sr.stop_loss,
                    "target": sr.target_price,
                }

        result.strategy_score = max_strategy_score
        result.triggered_strategies = triggered
        result.entry_price = best_entry
        result.stop_loss = best_stop
        result.target_price = best_target
        result.risk_reward = best_rr

        # ---- 2. K线形态评分(25%) ----
        result.pattern_score = score_pattern(klines)

        # ---- 3. 板块热度评分(20%) ----
        sector_score, industry, concepts, sector_signal = self._get_sector_score(code)
        result.sector_score = sector_score
        result.industry = industry
        result.concepts = concepts
        result.sector_signal = sector_signal

        # ---- 4. 趋势评分(15%) ----
        result.trend_score = score_trend(klines)

        # ---- 综合评分 ----
        result.total_score = round(
            result.strategy_score * self.WEIGHTS["strategy"] +
            result.pattern_score * self.WEIGHTS["pattern"] +
            result.sector_score * self.WEIGHTS["sector"] +
            result.trend_score * self.WEIGHTS["trend"],
            1
        )

        result.score_details = {
            "strategy": round(result.strategy_score, 1),
            "pattern": round(result.pattern_score, 1),
            "sector": round(result.sector_score, 1),
            "trend": round(result.trend_score, 1),
            "industry": industry,
            "concepts": concepts[:3],  # 只显示前3个
            "triggered": triggered,
            **strategy_details,
        }

        return result

    def scan_all(self, min_score: float = 0.0,
                 sector_filter: str | None = None,
                 strategy_filter: str | None = None,
                 min_days: int = 60) -> list[CompositeResult]:
        """全市场综合扫描

        Args:
            min_score: 最低综合分
            sector_filter: 板块过滤（行业名关键词）
            strategy_filter: 策略过滤（必须触发某策略）
            min_days: 最少K线天数

        Returns:
            综合评分结果列表
        """
        stocks = self.stock_list.get_all()
        t0 = time.time()

        # 批量读取K线
        stock_pairs = [(s.code, s.market) for s in stocks]
        batch_data = self.reader.get_day_klines_batch(stock_pairs)

        print(f"[CompositeScreener] 读取 {len(batch_data)}/{len(stocks)} 只股票K线 "
              f"({time.time() - t0:.1f}s)")

        # 过滤数据不足的
        valid_data = {
            code: klines
            for code, klines in batch_data.items()
            if len(klines) >= min_days
        }

        print(f"[CompositeScreener] 有效股票 {len(valid_data)} 只")

        # 板块过滤预处理
        if sector_filter:
            self._load_sector_data()
            valid_data = {
                code: klines
                for code, klines in valid_data.items()
                if self._sector_cache.get(code, ("", []))[0] and
                   sector_filter in self._sector_cache.get(code, ("", []))[0]
            }
            print(f"[CompositeScreener] 板块过滤({sector_filter}): {len(valid_data)} 只")

        # 逐只扫描
        results = []
        for code, klines in valid_data.items():
            result = self.scan_stock(klines, code=code)
            if result.total_score >= min_score:
                results.append(result)

        # 按综合分降序
        results.sort(key=lambda r: r.total_score, reverse=True)

        print(f"[CompositeScreener] 扫描完成: {len(results)} 只达标 "
              f"(总耗时 {time.time() - t0:.1f}s)")

        return results

    def scan_hot_sectors(self, top_n: int = 30,
                         min_score: float = 40.0) -> list[CompositeResult]:
        """热门板块选股 — 只在S/A级板块中选股

        Args:
            top_n: 取前N个热门板块
            min_score: 最低综合分

        Returns:
            热门板块中的优质个股
        """
        from ..sector.ths_sector import get_hot_sectors

        # 获取热门行业
        hot_industries = get_hot_sectors("industry", top_n=top_n)
        hot_names = [s.name for s in hot_industries if s.grade in ("S", "A")]

        print(f"[CompositeScreener] 热门板块: {len(hot_names)} 个")

        results = []
        for ind_name in hot_names:
            ind_results = self.scan_all(
                min_score=min_score,
                sector_filter=ind_name,
            )
            for r in ind_results:
                r.sector_signal = next(
                    (s.rotation_signal for s in hot_industries if s.name == ind_name),
                    ""
                )
            results.extend(ind_results)

        results.sort(key=lambda r: r.total_score, reverse=True)
        return results

    def to_strategy_results(self, composites: list[CompositeResult]) -> list[StrategyResult]:
        """将综合结果转为策略结果（兼容现有页面）

        Args:
            composites: 综合评分结果

        Returns:
            策略结果列表
        """
        results = []
        for c in composites:
            sr = StrategyResult(
                code=c.code,
                name=c.name,
                signal_type="+".join(c.triggered_strategies) if c.triggered_strategies else "composite",
                triggered=True,
                strength=c.total_score,
                entry_price=c.entry_price,
                stop_loss=c.stop_loss,
                target_price=c.target_price,
                risk_reward=c.risk_reward,
                details={
                    "strategy_score": c.strategy_score,
                    "pattern_score": c.pattern_score,
                    "sector_score": c.sector_score,
                    "trend_score": c.trend_score,
                    "industry": c.industry,
                    "concepts": c.concepts[:3],
                    "sector_signal": c.sector_signal,
                },
                score=c.score_details,
            )
            results.append(sr)
        return results
