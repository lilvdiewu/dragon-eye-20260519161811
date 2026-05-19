"""
dragon_eye.stock_list — 通达信本地股票列表管理

从vipdoc目录扫描全市场股票文件，生成标准化的 StockInfo 列表。
过滤指数/基金/债券/B股等非个股标的。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .data_models import StockInfo, Market, StockType, classify_stock, market_from_code
from .tdx_reader import TDX_VIPDOC


# ============================================================
# 股票代码过滤规则
# ============================================================

# 有效个股代码首字符
VALID_FIRST_CHARS = {"0", "3", "6"}

# 沪市需要排除的指数代码
SH_INDEX_CODES = {
    "000001",  # 上证指数
    "000002",  # A股指数
    "000003",  # B股指数
    "000004",  # 工业指数
    "000005",  # 商业指数
    "000006",  # 地产指数
    "000007",  # 公用指数
    "000008",  # 综合指数
    "000009",  # 上证380
    "000010",  # 上证180
    "000011",  # 基金指数
    "000012",  # 国债指数
    "000013",  # 企债指数
    "000015",  # 红利指数
    "000016",  # 上证50
    "000017",  # 新综指
    "000300",  # 沪深300
}


def is_valid_stock(code6: str, market: Market) -> bool:
    """判断6位代码是否是有效A股个股

    排除: 指数、基金、债券、B股、ETF等
    保留: 沪主板(6xx)、科创板(688)、深主板(0xx)、创业板(300/301)
    """
    if len(code6) != 6:
        return False

    first = code6[0]
    if first not in VALID_FIRST_CHARS:
        return False

    # 沪市指数排除
    if market == Market.SH and code6 in SH_INDEX_CODES:
        return False

    # 沪市6开头除了688(科创)以外基本都是个股
    # 但要排除ETF: 51xxxx / 58xxxx（基金类）
    if market == Market.SH:
        if code6.startswith("5"):
            return False  # ETF/基金

    # 深市排除: 15xxxx(基金) 16xxxx(权证) 18xxxx(ETF) 19xxxx(其他) 20xxxx(B股)
    if market == Market.SZ:
        if code6.startswith("1") or code6.startswith("2"):
            return False  # 基金/B股

    return True


# ============================================================
# StockList 管理器
# ============================================================

class StockList:
    """通达信本地股票列表管理

    用法:
        sl = StockList()
        all_stocks = sl.get_all()
        sh_stocks = sl.get_by_market(Market.SH)
        stock = sl.get_stock("603618")
    """

    def __init__(self, vipdoc: str = TDX_VIPDOC):
        self.vipdoc = vipdoc
        self._stocks: Optional[list[StockInfo]] = None
        self._code_map: Optional[dict[str, StockInfo]] = None

    def _scan_vipdoc(self) -> list[StockInfo]:
        """扫描vipdoc目录，构建股票列表"""
        stocks = []

        for market in [Market.SH, Market.SZ]:
            mkt = market.value
            lday_dir = os.path.join(self.vipdoc, mkt, "lday")
            minline_dir = os.path.join(self.vipdoc, mkt, "minline")

            if not os.path.isdir(lday_dir):
                continue

            for fname in os.listdir(lday_dir):
                if not fname.endswith(".day"):
                    continue

                # 解析代码: sh603618.day → 603618
                prefix = mkt  # "sh" or "sz"
                if not fname.startswith(prefix):
                    continue
                code6 = fname[len(prefix):-4]  # 去掉前缀和.day

                if not is_valid_stock(code6, market):
                    continue

                stock_type = classify_stock(code6, market)
                day_path = os.path.join(lday_dir, fname)

                # 检查文件大小（至少30条记录=960字节）
                try:
                    file_size = os.path.getsize(day_path)
                    if file_size < 960:
                        continue
                except OSError:
                    continue

                # 5分钟线路径
                lc5_name = f"{prefix}{code6}.lc5"
                lc5_path = os.path.join(minline_dir, lc5_name) if os.path.isdir(minline_dir) else ""

                stocks.append(StockInfo(
                    code=code6,
                    name="",  # 名称后续从缓存/AkShare补充
                    market=market,
                    stock_type=stock_type,
                    day_file=day_path,
                    min_file=lc5_path if os.path.isfile(lc5_path) else "",
                ))

        return stocks

    def get_all(self, refresh: bool = False) -> list[StockInfo]:
        """获取全市场股票列表"""
        if self._stocks is None or refresh:
            self._stocks = self._scan_vipdoc()
            self._code_map = {s.code: s for s in self._stocks}
        return self._stocks

    def get_by_market(self, market: Market) -> list[StockInfo]:
        """按市场筛选"""
        return [s for s in self.get_all() if s.market == market]

    def get_by_type(self, stock_type: StockType) -> list[StockInfo]:
        """按类型筛选"""
        return [s for s in self.get_all() if s.stock_type == stock_type]

    def get_stock(self, code6: str) -> Optional[StockInfo]:
        """按代码查询"""
        self.get_all()  # 确保已加载
        return self._code_map.get(code6) if self._code_map else None

    def get_codes(self, market: Optional[Market] = None) -> list[str]:
        """获取代码列表"""
        stocks = self.get_by_market(market) if market else self.get_all()
        return [s.code for s in stocks]

    def count(self) -> dict[str, int]:
        """统计各市场股票数量"""
        stocks = self.get_all()
        stats = {}
        for mkt in [Market.SH, Market.SZ]:
            count = len([s for s in stocks if s.market == mkt])
            stats[mkt.value] = count
        stats["total"] = len(stocks)
        return stats

    def search(self, keyword: str) -> list[StockInfo]:
        """模糊搜索（代码或名称）"""
        stocks = self.get_all()
        keyword = keyword.lower()
        return [s for s in stocks if keyword in s.code or keyword in s.name.lower()]


# ============================================================
# 便捷函数
# ============================================================

_default_list: Optional[StockList] = None


def get_stock_list(vipdoc: str = TDX_VIPDOC) -> StockList:
    """获取全局StockList实例"""
    global _default_list
    if _default_list is None or _default_list.vipdoc != vipdoc:
        _default_list = StockList(vipdoc)
    return _default_list
