"""
dragon_eye — 龙瞳Pro A股智能投研平台

数据层 → 引擎层 → 策略层 → 分析层 → UI层 → 推送层
"""

from .tdx_reader import TdxReader, get_reader
from .stock_list import StockList, get_stock_list
from .data_models import (
    Kline, StockInfo, Quote, Financial, SectorInfo,
    Market, StockType, KlinePeriod,
    classify_stock, market_from_code,
)

__version__ = "0.2.0"
__all__ = [
    "TdxReader", "get_reader",
    "StockList", "get_stock_list",
    "Kline", "StockInfo", "Quote", "Financial", "SectorInfo",
    "Market", "StockType", "KlinePeriod",
    "classify_stock", "market_from_code",
]
