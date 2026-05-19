"""
dragon_eye.data_models — 龙瞳Pro统一数据模型

所有数据层返回标准化对象，上层无需关心数据来源（通达信/AkShare/pytdx）
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ============================================================
# 市场枚举
# ============================================================

class Market(enum.Enum):
    SH = "sh"   # 上海
    SZ = "sz"   # 深圳
    BJ = "bj"   # 北交所


class StockType(enum.Enum):
    MAINLAND_SH = "sh_main"      # 沪主板 600xxx
    KCB = "sh_kcb"               # 科创板 688xxx
    MAINLAND_SZ = "sz_main"      # 深主板 000xxx/001xxx
    CYB = "sz_cyb"               # 创业板 300xxx
    BSE = "bse"                  # 北交所 4xxxxx/8xxxxx


class KlinePeriod(enum.Enum):
    DAILY = "day"
    MIN1 = "1min"
    MIN5 = "5min"
    MIN15 = "15min"
    MIN30 = "30min"
    MIN60 = "60min"
    FENSHI = "fenshi"           # 分时（逐笔）


# ============================================================
# 核心数据类
# ============================================================

@dataclass
class Kline:
    """单根K线"""
    date: str                   # YYYY-MM-DD or YYYY-MM-DD HH:MM
    open: float
    high: float
    low: float
    close: float
    volume: float               # 手
    amount: float               # 元
    # 涨跌（仅日线有）
    change_pct: Optional[float] = None   # 涨跌幅%


@dataclass
class StockInfo:
    """股票基本信息"""
    code: str                   # 6位代码 如 "603618"
    name: str                   # 股票名称
    market: Market              # 市场
    stock_type: StockType       # 类型
    # 通达信文件路径
    day_file: str = ""
    min_file: str = ""          # 5分钟线
    fenshi_file: str = ""       # 分时线

    @property
    def ticker(self) -> str:
        """TradingAgents格式 如 603618.SS"""
        suffix = "SS" if self.market == Market.SH else "SZ" if self.market == Market.SZ else "BJ"
        return f"{self.code}.{suffix}"

    @property
    def tdx_code(self) -> str:
        """通达信文件名前缀 如 sh603618"""
        return f"{self.market.value}{self.code}"

    @property
    def limit_pct(self) -> float:
        """涨跌停幅度"""
        if self.stock_type in (StockType.CYB, StockType.KCB):
            return 20.0
        if self.stock_type == StockType.BSE:
            return 30.0
        return 10.0


@dataclass
class Quote:
    """实时行情快照"""
    code: str
    name: str
    price: float                # 最新价
    open: float
    high: float
    low: float
    close: float                # 昨收
    volume: float               # 手
    amount: float               # 元
    bid1: float = 0.0           # 买一
    ask1: float = 0.0           # 卖一
    change_pct: float = 0.0     # 涨跌幅
    turnover_rate: float = 0.0  # 换手率
    timestamp: str = ""


@dataclass
class Financial:
    """财务数据摘要"""
    code: str
    name: str
    report_date: str            # 报告期
    eps: float = 0.0            # 每股收益
    bvps: float = 0.0           # 每股净资产
    roe: float = 0.0            # 净资产收益率%
    revenue: float = 0.0         # 营业收入(亿)
    revenue_yoy: float = 0.0    # 营收同比%
    net_profit: float = 0.0     # 净利润(亿)
    profit_yoy: float = 0.0     # 净利润同比%
    pe_ttm: float = 0.0         # 市盈率TTM
    pb: float = 0.0             # 市净率
    total_mv: float = 0.0       # 总市值(亿)
    circ_mv: float = 0.0        # 流通市值(亿)


@dataclass
class SectorInfo:
    """板块/概念信息"""
    name: str                   # 板块名 如 "固态电池"
    code: str                   # 板块代码
    sector_type: str            # industry/concept
    change_pct: float = 0.0     # 涨跌幅
    stocks: list[str] = field(default_factory=list)   # 成分股代码列表
    top_stocks: list[str] = field(default_factory=list)  # 龙头股代码


# ============================================================
# 工具函数
# ============================================================

def classify_stock(code6: str, market: Market) -> StockType:
    """根据代码和市场判断股票类型"""
    if market == Market.BJ:
        return StockType.BSE
    if market == Market.SH:
        if code6.startswith("688"):
            return StockType.KCB
        return StockType.MAINLAND_SH
    # 深圳
    if code6.startswith("300") or code6.startswith("301"):
        return StockType.CYB
    return StockType.MAINLAND_SZ


def market_from_code(code6: str) -> Market:
    """从6位代码推断市场"""
    if code6.startswith("6"):
        return Market.SH
    if code6.startswith("4") or code6.startswith("8"):
        return Market.BJ
    return Market.SZ
