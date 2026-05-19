"""
dragon_eye.sector.sector_data — 板块概念数据层

整合通达信+AkShare的板块数据，提供统一的板块查询接口。
"""
from __future__ import annotations

from typing import Optional

from ..data_models import SectorInfo
from ..akshare_bridge import AkShareBridge, get_bridge


class SectorData:
    """板块概念数据层

    用法:
        sd = SectorData()
        industries = sd.get_industry_sectors()
        concepts = sd.get_concept_sectors()
        stocks = sd.get_sector_stocks("BK0428", "industry")
        results = sd.search_sector("固态电池")
        hot = sd.get_hot_sectors(10)
    """

    def __init__(self, bridge: Optional[AkShareBridge] = None):
        self._bridge = bridge or get_bridge()  # 全局单例

    def get_industry_sectors(self) -> list[SectorInfo]:
        """获取行业板块列表"""
        return self._bridge.get_industry_sectors()

    def get_concept_sectors(self) -> list[SectorInfo]:
        """获取概念板块列表"""
        return self._bridge.get_concept_sectors()

    def get_sector_stocks(self, sector_code: str, sector_type: str = "industry") -> list[str]:
        """获取板块成分股代码列表

        Args:
            sector_code: 板块代码
            sector_type: industry / concept
        Returns:
            6位股票代码列表
        """
        return self._bridge.get_sector_stocks(sector_code, sector_type)

    def search_sector(self, keyword: str) -> list[SectorInfo]:
        """模糊搜索板块（行业+概念）"""
        return self._bridge.search_sector(keyword)

    def get_hot_sectors(self, top_n: int = 10) -> list[SectorInfo]:
        """获取涨幅前排的热门板块

        综合行业板块和概念板块，按涨跌幅降序排列，取前N名。
        """
        all_sectors: list[SectorInfo] = []

        # 获取行业板块
        try:
            industries = self.get_industry_sectors()
            all_sectors.extend(industries)
        except Exception:
            pass

        # 获取概念板块
        try:
            concepts = self.get_concept_sectors()
            all_sectors.extend(concepts)
        except Exception:
            pass

        # 按涨跌幅降序排列
        all_sectors.sort(key=lambda s: s.change_pct, reverse=True)

        return all_sectors[:top_n]
