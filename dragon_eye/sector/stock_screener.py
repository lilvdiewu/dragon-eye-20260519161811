"""
dragon_eye.sector.stock_screener — 龙头筛选器

多维度筛选龙头股：市值/趋势/技术面/量能/估值
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..tdx_reader import TdxReader, get_reader
from ..akshare_bridge import AkShareBridge, get_bridge
from ..data_models import Market, market_from_code
from ..signals import score_technical

logger = logging.getLogger(__name__)


@dataclass
class StockScore:
    """个股综合评分"""
    code: str
    name: str = ""
    score: float = 0.0           # 综合评分 0-100
    market_cap_rank: float = 0.0  # 市值排名评分
    tech_rank: float = 0.0        # 技术面评分
    fund_rank: float = 0.0        # 资金面(涨幅)评分
    valuation_rank: float = 0.0   # 估值评分
    volume_rank: float = 0.0      # 量能评分
    market_cap: float = 0.0        # 总市值(亿)
    pe_ttm: float = 0.0           # 市盈率TTM
    pb: float = 0.0               # 市净率


# 评分权重
WEIGHTS = {
    "market_cap": 0.25,   # 市值排名
    "trend": 0.20,        # 近N日涨幅
    "technical": 0.30,    # 技术面
    "volume": 0.15,       # 量比/换手
    "valuation": 0.10,    # 估值
}


class StockScreener:
    """龙头股筛选器

    用法:
        screener = StockScreener()
        scores = screener.screen(["603618", "300750", "002594"])
    """

    def __init__(self, reader: Optional[TdxReader] = None, bridge: Optional[AkShareBridge] = None):
        self._reader = reader or get_reader()
        self._bridge = bridge or get_bridge()  # 全局单例
        self._name_map: Optional[dict[str, str]] = None

    def _get_name_map(self) -> dict[str, str]:
        """获取股票名称映射（懒加载）"""
        if self._name_map is None:
            try:
                self._name_map = self._bridge.enrich_stock_names([])
            except Exception:
                self._name_map = {}
        return self._name_map

    def _get_stock_name(self, code6: str) -> str:
        """获取股票名称"""
        return self._get_name_map().get(code6, "")

    def screen(self, stocks: list[str]) -> list[StockScore]:
        """筛选并排序龙头股

        Args:
            stocks: 6位股票代码列表
        Returns:
            按综合评分降序排列的 StockScore 列表
        """
        if not stocks:
            return []

        scores: list[StockScore] = []

        for code6 in stocks:
            try:
                sc = self._score_single(code6)
                if sc is not None:
                    scores.append(sc)
            except Exception as e:
                logger.debug("评分失败 %s: %s", code6, e)
                continue

        # 综合评分降序
        scores.sort(key=lambda s: s.score, reverse=True)
        return scores

    def _score_single(self, code6: str) -> Optional[StockScore]:
        """对单只股票进行多维度评分"""
        market = market_from_code(code6)
        klines = self._reader.get_day_klines(code6, market)

        if not klines or len(klines) < 30:
            return None

        sc = StockScore(
            code=code6,
            name=self._get_stock_name(code6),
        )

        # 各维度评分
        sc.market_cap_rank = self.score_market_cap(code6)
        sc.fund_rank = self.score_trend(code6, days=20)
        sc.tech_rank = self.score_technical(code6)
        sc.volume_rank = self.score_volume(code6)
        sc.valuation_rank = self.score_valuation(code6)

        # 加权综合评分
        sc.score = round(
            sc.market_cap_rank * WEIGHTS["market_cap"]
            + sc.fund_rank * WEIGHTS["trend"]
            + sc.tech_rank * WEIGHTS["technical"]
            + sc.volume_rank * WEIGHTS["volume"]
            + sc.valuation_rank * WEIGHTS["valuation"],
            1,
        )

        return sc

    def score_market_cap(self, code6: str) -> float:
        """市值排名评分

        市值越大评分越高（龙头股通常市值较大）
        以万亿=100分，百亿=50分为基准
        """
        try:
            spot = self._bridge.get_realtime_spot(code6)
            if spot and spot.get("total_mv", 0) > 0:
                total_mv = spot["total_mv"] / 1e8  # 转为亿
                if total_mv <= 0:
                    return 0.0
                import math
                score = min(100, max(0, 20 + 20 * math.log10(total_mv / 100)))
                return round(score, 1)
        except Exception:
            pass

        # 无实时数据时，用通达信K线成交额近似
        try:
            market = market_from_code(code6)
            klines = self._reader.get_day_klines(code6, market)
            if klines and klines[-1].amount > 0:
                amount_yi = klines[-1].amount / 1e8
                return min(100, max(0, amount_yi * 5))
        except Exception:
            pass

        return 0.0

    def score_trend(self, code6: str, days: int = 20) -> float:
        """近N日涨幅评分

        涨幅越大评分越高（趋势龙头）
        涨幅映射: -10%→0分, 0%→30分, 10%→60分, 30%→90分
        """
        market = market_from_code(code6)
        klines = self._reader.get_day_klines(code6, market)

        if not klines or len(klines) < days:
            return 0.0

        recent = klines[-days:]
        start_close = recent[0].close
        end_close = recent[-1].close

        if start_close <= 0:
            return 0.0

        change_pct = (end_close - start_close) / start_close * 100

        # 线性映射: -10%→0, 0%→30, 10%→60, 30%→100
        if change_pct <= -10:
            return 0.0
        elif change_pct <= 0:
            return round(30 * (change_pct + 10) / 10, 1)
        elif change_pct <= 30:
            return round(30 + 70 * change_pct / 30, 1)
        else:
            return 100.0

    def score_technical(self, code6: str) -> float:
        """技术面综合评分(复用signals.score_technical)"""
        market = market_from_code(code6)
        klines = self._reader.get_day_klines(code6, market)

        if not klines or len(klines) < 30:
            return 0.0

        result = score_technical(klines)
        return float(result.get("total_score", 0))

    def score_volume(self, code6: str) -> float:
        """量能评分

        量比/换手率评估: 量能配合度
        """
        market = market_from_code(code6)
        klines = self._reader.get_day_klines(code6, market)

        if not klines or len(klines) < 20:
            return 0.0

        # 计算近5日平均量 vs 20日平均量
        recent_vols = [k.volume for k in klines[-5:]]
        avg_vols = [k.volume for k in klines[-20:]]

        if not avg_vols or not recent_vols:
            return 0.0

        avg_20 = sum(avg_vols) / len(avg_vols)
        avg_5 = sum(recent_vols) / len(recent_vols)

        if avg_20 <= 0:
            return 0.0

        vol_ratio = avg_5 / avg_20

        # 量比映射: 0.5→10分, 1.0→40分, 1.5→70分, 2.0→100分
        if vol_ratio <= 0.5:
            return 10.0
        elif vol_ratio <= 1.0:
            return round(10 + 30 * (vol_ratio - 0.5) / 0.5, 1)
        elif vol_ratio <= 1.5:
            return round(40 + 30 * (vol_ratio - 1.0) / 0.5, 1)
        elif vol_ratio <= 2.0:
            return round(70 + 30 * (vol_ratio - 1.5) / 0.5, 1)
        else:
            return 100.0

    def score_valuation(self, code6: str) -> float:
        """估值评分

        优先从实时行情获取PE/PB，失败时用K线数据近似。
        估值越合理评分越高:
        PE 10-30: 高分(合理估值)
        PE <0 或 >100: 低分(亏损或泡沫)
        PB 1-3: 高分
        """
        # 尝试获取实时PE/PB
        pe = 0.0
        pb = 0.0
        try:
            spot = self._bridge.get_realtime_spot(code6)
            if spot:
                pe = float(spot.get("pe_ttm", 0) or 0)
                pb = float(spot.get("pb", 0) or 0)
        except Exception:
            pass

        # 无PE数据时给中位数（不阻塞）
        if pe == 0 and pb == 0:
            return 50.0

        # PE评分
        if pe <= 0:
            pe_score = 10.0  # 亏损
        elif pe <= 10:
            pe_score = 80.0  # 低估
        elif pe <= 30:
            pe_score = 90.0  # 合理
        elif pe <= 60:
            pe_score = 50.0  # 偏高
        elif pe <= 100:
            pe_score = 30.0  # 高估
        else:
            pe_score = 10.0  # 泡沫

        # PB评分
        if pb <= 0:
            pb_score = 10.0
        elif pb <= 1:
            pb_score = 70.0  # 破净或低估
        elif pb <= 3:
            pb_score = 80.0  # 合理
        elif pb <= 6:
            pb_score = 50.0  # 偏高
        else:
            pb_score = 20.0  # 高估

        return round(pe_score * 0.6 + pb_score * 0.4, 1)
