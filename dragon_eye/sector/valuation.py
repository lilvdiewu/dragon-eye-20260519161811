"""
dragon_eye.sector.valuation — 估值分析

单股估值分析、历史PE/PB分位、同行业估值比较
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..tdx_reader import TdxReader, get_reader
from ..akshare_bridge import AkShareBridge, get_bridge
from ..data_models import Market, market_from_code

logger = logging.getLogger(__name__)


# ============================================================
# 数据类
# ============================================================

@dataclass
class ValuationResult:
    """单股估值分析结果"""
    code: str
    name: str = ""
    pe_ttm: float = 0.0          # 市盈率TTM
    pb: float = 0.0              # 市净率
    pe_percentile: float = 0.0   # PE历史分位 (0-100)
    pb_percentile: float = 0.0   # PB历史分位 (0-100)
    valuation_level: str = "未知"  # 低估/合理/高估


@dataclass
class SectorCompare:
    """同行业估值比较"""
    code: str
    name: str = ""
    pe_ttm: float = 0.0
    pb: float = 0.0
    sector_avg_pe: float = 0.0     # 行业平均PE
    sector_avg_pb: float = 0.0     # 行业平均PB
    pe_rank_in_sector: int = 0     # 行业内PE排名
    sector_stock_count: int = 0    # 行业内股票总数
    relative_level: str = "未知"    # 偏低/适中/偏高


# ============================================================
# 估值分析器
# ============================================================

class ValuationAnalyzer:
    """估值分析器

    用法:
        va = ValuationAnalyzer()
        result = va.analyze("603618")
        pe_history = va.get_pe_history("603618")
        compare = va.compare_sector("603618", "BK0428")
    """

    def __init__(self, reader: Optional[TdxReader] = None, bridge: Optional[AkShareBridge] = None):
        self._reader = reader or get_reader()
        self._bridge = bridge or get_bridge()  # 全局单例

    def analyze(self, code6: str) -> ValuationResult:
        """单股估值分析

        综合PE/PB及其历史分位判断估值水平
        """
        result = ValuationResult(code=code6)

        # 获取实时PE/PB
        spot = None
        try:
            spot = self._bridge.get_realtime_spot(code6)
        except Exception as e:
            logger.debug("获取实时行情失败 %s: %s", code6, e)

        if spot:
            result.pe_ttm = float(spot.get("pe_ttm", 0) or 0)
            result.pb = float(spot.get("pb", 0) or 0)
            result.name = str(spot.get("name", ""))

        # 获取PE历史数据计算分位
        pe_history = self.get_pe_history(code6)
        if pe_history:
            pe_values = [v for _, v in pe_history if v > 0]
            if pe_values and result.pe_ttm > 0:
                result.pe_percentile = round(
                    sum(1 for v in pe_values if v <= result.pe_ttm) / len(pe_values) * 100, 1
                )

        # PB历史分位（使用K线价格近似计算）
        pb_percentile = self._calc_pb_percentile(code6, result.pb)
        result.pb_percentile = pb_percentile

        # 判断估值水平
        result.valuation_level = self._judge_valuation(result)

        return result

    def get_pe_history(self, code6: str) -> list[tuple[str, float]]:
        """获取PE历史数据

        用通达信日K线价格 + AkShare财务数据估算历史PE
        Returns:
            [(date, pe_value), ...]
        """
        market = market_from_code(code6)
        klines = self._reader.get_day_klines(code6, market)

        if not klines:
            return []

        # 获取最新财务数据（EPS）
        financial = None
        try:
            financial = self._bridge.get_financial(code6)
        except Exception:
            pass

        eps = financial.eps if financial and financial.eps > 0 else 0

        if eps <= 0:
            # 无EPS数据，用实时PE估算
            spot = None
            try:
                spot = self._bridge.get_realtime_spot(code6)
            except Exception:
                pass
            if spot and spot.get("pe_ttm", 0) > 0 and spot.get("price", 0) > 0:
                # 用当前PE和价格反推EPS
                eps = spot["price"] / spot["pe_ttm"]

        if eps <= 0:
            return []

        # 用每日收盘价/EPS估算PE
        pe_history: list[tuple[str, float]] = []
        for k in klines:
            if k.close > 0:
                pe_val = round(k.close / eps, 2)
                pe_history.append((k.date, pe_val))

        return pe_history

    def compare_sector(self, code6: str, sector_code: str) -> SectorCompare:
        """同行业估值比较

        Args:
            code6: 股票6位代码
            sector_code: 板块代码
        Returns:
            SectorCompare 行业内估值比较结果
        """
        compare = SectorCompare(code=code6)

        # 获取目标股PE/PB
        spot = None
        try:
            spot = self._bridge.get_realtime_spot(code6)
        except Exception:
            pass

        if spot:
            compare.pe_ttm = float(spot.get("pe_ttm", 0) or 0)
            compare.pb = float(spot.get("pb", 0) or 0)
            compare.name = str(spot.get("name", ""))

        # 获取板块成分股
        sector_stocks: list[str] = []
        try:
            sector_stocks = self._bridge.get_sector_stocks(sector_code, "industry")
        except Exception:
            try:
                sector_stocks = self._bridge.get_sector_stocks(sector_code, "concept")
            except Exception:
                pass

        if not sector_stocks:
            return compare

        # 计算行业PE/PB统计
        # 🔑 优化：用腾讯API批量获取（走缓存），而非逐股调用东方财富
        pe_list: list[float] = []
        pb_list: list[float] = []

        for stock_code in sector_stocks:
            try:
                s = self._bridge.get_realtime_quote_tencent(stock_code)
                if not s:
                    continue
                pe = float(s.get("pe_ttm", 0) or 0)
                pb = float(s.get("pb", 0) or 0)

                if pe > 0:
                    pe_list.append(pe)
                if pb > 0:
                    pb_list.append(pb)
            except Exception:
                continue

        # 行业平均
        compare.sector_stock_count = len(sector_stocks)
        if pe_list:
            compare.sector_avg_pe = round(sum(pe_list) / len(pe_list), 2)
            # PE排名(从小到大)
            sorted_pe = sorted(pe_list)
            if compare.pe_ttm > 0:
                compare.pe_rank_in_sector = sum(
                    1 for v in sorted_pe if v <= compare.pe_ttm
                )
        if pb_list:
            compare.sector_avg_pb = round(sum(pb_list) / len(pb_list), 2)

        # 判断相对水平
        compare.relative_level = self._judge_relative(compare)

        return compare

    def _calc_pb_percentile(self, code6: str, current_pb: float) -> float:
        """计算PB历史分位

        用K线收盘价与每股净资产的比值近似PB
        """
        if current_pb <= 0:
            return 0.0

        market = market_from_code(code6)
        klines = self._reader.get_day_klines(code6, market)

        if not klines or len(klines) < 60:
            return 50.0  # 数据不足给中位数

        # 获取每股净资产
        financial = None
        try:
            financial = self._bridge.get_financial(code6)
        except Exception:
            pass

        bvps = financial.bvps if financial and financial.bvps > 0 else 0
        if bvps <= 0:
            return 50.0

        # 计算历史PB
        pb_values: list[float] = []
        for k in klines:
            if k.close > 0:
                pb_val = k.close / bvps
                pb_values.append(pb_val)

        if not pb_values:
            return 50.0

        # 计算当前PB在历史中的分位
        percentile = sum(1 for v in pb_values if v <= current_pb) / len(pb_values) * 100
        return round(percentile, 1)

    @staticmethod
    def _judge_valuation(result: ValuationResult) -> str:
        """判断估值水平

        综合PE/PB历史分位:
        - 分位 < 30%: 低估
        - 分位 30-70%: 合理
        - 分位 > 70%: 高估
        """
        # 优先用PE分位
        if result.pe_percentile > 0:
            avg_percentile = result.pe_percentile
            if result.pb_percentile > 0:
                avg_percentile = (result.pe_percentile + result.pb_percentile) / 2
        elif result.pb_percentile > 0:
            avg_percentile = result.pb_percentile
        else:
            # 无分位数据时用绝对值判断
            if result.pe_ttm <= 0:
                return "亏损"
            elif result.pe_ttm <= 15:
                return "低估"
            elif result.pe_ttm <= 40:
                return "合理"
            else:
                return "高估"

        if avg_percentile < 30:
            return "低估"
        elif avg_percentile <= 70:
            return "合理"
        else:
            return "高估"

    @staticmethod
    def _judge_relative(compare: SectorCompare) -> str:
        """判断个股相对行业估值水平"""
        if compare.sector_avg_pe <= 0 or compare.pe_ttm <= 0:
            return "未知"

        ratio = compare.pe_ttm / compare.sector_avg_pe

        if ratio < 0.8:
            return "偏低"
        elif ratio <= 1.2:
            return "适中"
        else:
            return "偏高"
