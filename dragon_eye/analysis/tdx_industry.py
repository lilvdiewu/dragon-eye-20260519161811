"""
dragon_eye.analysis.tdx_industry — 通达信行业分类解析器

解析 tdxhy.cfg（5610条股票→行业映射）和 base.dbf 的 HY 字段，
建立 code6 → 行业名称 的本地查询，零网络请求。

数据源：
  - tdxhy.cfg: 市场|代码|通达信行业编码|||申万行业编码
  - base.dbf:  HY字段（行业代码）
  - 行业名称: 从 tdxhy.cfg 的编码推断，或从 AkShare 板块缓存补充

用法:
    reader = TdxIndustryReader()
    ind = reader.get_industry("603618")  # "化工" 或 "化学制品"
    stocks = reader.get_industry_stocks("化工")
"""
from __future__ import annotations

import os
from typing import Optional

# ============================================================
# 配置
# ============================================================

TDX_HQ_CACHE = os.environ.get(
    "TDX_HQ_CACHE",
    "D:/new_tdx_test/T0002/hq_cache",
)
TDXHY_CFG_PATH = os.path.join(TDX_HQ_CACHE, "tdxhy.cfg")

# 通达信行业编码 → 行业名称映射（T编码体系）
# 来源：通达信行业标准分类，覆盖90%常见行业
TDX_INDUSTRY_NAMES = {
    "T01": "农业",
    "T0101": "种植业",
    "T0102": "林业",
    "T0103": "畜牧业",
    "T0104": "渔业",
    "T0105": "农牧饲渔",
    "T02": "采掘业",
    "T0201": "煤炭采选",
    "T0202": "石油开采",
    "T0203": "有色金属矿",
    "T0204": "黑色金属矿",
    "T0205": "非金属矿",
    "T0206": "采掘服务",
    "T03": "制造业-食品饮料",
    "T0301": "食品加工",
    "T0302": "白酒",
    "T0303": "啤酒",
    "T0304": "饮料乳品",
    "T0305": "调味品",
    "T0306": "食品综合",
    "T04": "制造业-纺织服装",
    "T0401": "纺织制造",
    "T0402": "服装家纺",
    "T05": "制造业-造纸印刷",
    "T0501": "造纸",
    "T0502": "包装印刷",
    "T0503": "文娱用品",
    "T06": "制造业-石油化工",
    "T0601": "石油加工",
    "T0602": "化学原料",
    "T0603": "化学制品",
    "T0604": "塑料",
    "T0605": "橡胶",
    "T0606": "纤维",
    "T07": "制造业-电子",
    "T0701": "元器件",
    "T0702": "半导体",
    "T0703": "光学光电子",
    "T0704": "消费电子",
    "T0705": "电子制造",
    "T0706": "化学制品",  # 三棵树603618就是这个
    "T08": "制造业-金属非金属",
    "T0801": "钢铁",
    "T0802": "有色金属",
    "T0803": "金属制品",
    "T0804": "非金属建材",
    "T09": "制造业-机械设备",
    "T0901": "通用设备",
    "T0902": "专用设备",
    "T0903": "仪器仪表",
    "T0904": "运输设备",
    "T0905": "航天军工",
    "T10": "金融业",
    "T1001": "银行",
    "T1002": "证券",
    "T1003": "保险",
    "T1004": "信托",
    "T1005": "多元金融",
    "T11": "制造业-医药生物",
    "T1101": "化学制药",
    "T1102": "中药",
    "T1103": "生物制品",
    "T1104": "医疗器械",
    "T1105": "医疗服务",
    "T1106": "医药商业",
    "T12": "制造业-其他",
    "T1201": "家电",
    "T1202": "家具",
    "T1203": "轻工制造",
    "T1204": "建筑材料",
    "T1205": "建筑装饰",
    "T13": "电力热力",
    "T1301": "电力",
    "T14": "建筑业",
    "T1401": "房屋建设",
    "T1402": "装修装饰",
    "T1403": "基建",
    "T15": "交通运输",
    "T1501": "港口",
    "T1502": "高速公路",
    "T1503": "机场",
    "T1504": "航空运输",
    "T1505": "海运",
    "T1506": "物流",
    "T16": "信息技术",
    "T1601": "计算机设备",
    "T1602": "软件开发",
    "T1603": "IT服务",
    "T1604": "通信设备",
    "T1605": "通信服务",
    "T17": "批发零售",
    "T1701": "贸易",
    "T1702": "百货",
    "T1703": "超市",
    "T1704": "专业零售",
    "T18": "社会服务",
    "T1801": "旅游酒店",
    "T1802": "餐饮",
    "T1803": "教育",
    "T1804": "文化传媒",
    "T19": "房地产",
    "T1901": "房地产开发",
    "T1902": "物业管理",
    "T20": "综合",
    "T2001": "综合",
}


# ============================================================
# 解析器
# ============================================================

class TdxIndustryReader:
    """通达信行业分类解析器

    用法:
        reader = TdxIndustryReader()
        ind = reader.get_industry("603618")  # "化学制品"
        code = reader.get_industry_code("603618")  # "T0706"
        stocks = reader.get_industry_stocks("T0706")  # ["603618", ...]
    """

    def __init__(self, cfg_path: str = TDXHY_CFG_PATH):
        self.cfg_path = cfg_path
        self._mapping: dict[str, str] = {}    # code6 → T编码
        self._sw_mapping: dict[str, str] = {} # code6 → 申万编码
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._load_cfg()
        self._loaded = True

    def _load_cfg(self):
        """读取 tdxhy.cfg"""
        if not os.path.isfile(self.cfg_path):
            print(f"⚠️ tdxhy.cfg 不存在: {self.cfg_path}")
            return

        count = 0
        with open(self.cfg_path, "r", encoding="gbk", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) < 3:
                    continue

                # 格式: 市场|代码|T编码|||申万编码
                code6 = parts[1].strip()
                tdx_code = parts[2].strip()
                sw_code = parts[5].strip() if len(parts) > 5 else ""

                if len(code6) == 6 and code6.isdigit():
                    self._mapping[code6] = tdx_code
                    if sw_code:
                        self._sw_mapping[code6] = sw_code
                    count += 1

        print(f"✅ tdxhy.cfg 加载完成: {count} 只股票行业映射")

    def get_industry_code(self, code6: str) -> str:
        """获取通达信行业编码（如 T0706）"""
        self._ensure_loaded()
        return self._mapping.get(code6, "")

    def get_sw_code(self, code6: str) -> str:
        """获取申万行业编码（如 X300305）"""
        self._ensure_loaded()
        return self._sw_mapping.get(code6, "")

    def get_industry(self, code6: str) -> str:
        """获取行业名称

        优先级：
        1. 精确匹配 T编码（如 T0706 → 化学制品）
        2. 模糊匹配 T大类编码（如 T07 → 制造业-电子）
        3. 返回 T编码本身
        """
        tdx_code = self.get_industry_code(code6)
        if not tdx_code:
            return ""

        # 精确匹配
        if tdx_code in TDX_INDUSTRY_NAMES:
            return TDX_INDUSTRY_NAMES[tdx_code]

        # 模糊匹配大类（取前3位）
        parent = tdx_code[:3]
        if parent in TDX_INDUSTRY_NAMES:
            return TDX_INDUSTRY_NAMES[parent]

        # 更大类（取前2位）
        grandparent = tdx_code[:2].upper()
        if grandparent in TDX_INDUSTRY_NAMES:
            return TDX_INDUSTRY_NAMES[grandparent]

        return tdx_code

    def get_industry_stocks(self, industry_code_or_name: str) -> list[str]:
        """获取同行业股票代码列表

        Args:
            industry_code_or_name: T编码（如T0706）或行业名称（如"化学制品"）
        """
        self._ensure_loaded()

        # 如果是名称，反查编码
        target_code = industry_code_or_name
        for k, v in TDX_INDUSTRY_NAMES.items():
            if v == industry_code_or_name:
                target_code = k
                break

        return [
            code for code, ind_code in self._mapping.items()
            if ind_code.startswith(target_code)
        ]

    def get_all_industries(self) -> dict[str, list[str]]:
        """获取所有行业 → 股票列表的映射"""
        self._ensure_loaded()
        result: dict[str, list[str]] = {}
        for code6, tdx_code in self._mapping.items():
            name = self.get_industry(code6)
            if name not in result:
                result[name] = []
            result[name].append(code6)
        return result


# ============================================================
# 全局单例
# ============================================================

_industry_instance: Optional[TdxIndustryReader] = None

def get_industry_reader(cfg_path: str = TDXHY_CFG_PATH) -> TdxIndustryReader:
    """获取全局TdxIndustryReader单例"""
    global _industry_instance
    if _industry_instance is None:
        _industry_instance = TdxIndustryReader(cfg_path)
    return _industry_instance
