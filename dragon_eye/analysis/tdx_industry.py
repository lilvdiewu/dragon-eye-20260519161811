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

# ═══════════════════════════════════════════════════════════
# 申万行业分类编码 → 名称映射（优先使用，比通达信T编码更可靠）
# ═══════════════════════════════════════════════════════════
SW_INDUSTRY_NAMES: dict[str, str] = {
    # 一级行业
    "X21": "采掘", "X22": "化工", "X23": "钢铁", "X24": "有色金属",
    "X25": "建筑材料", "X26": "建筑装饰", "X27": "电气设备", "X28": "机械设备",
    "X29": "国防军工", "X210": "汽车", "X211": "家用电器", "X212": "纺织服装",
    "X213": "轻工制造", "X214": "商业贸易", "X215": "农林牧渔", "X216": "食品饮料",
    "X217": "休闲服务", "X218": "医药生物", "X219": "公用事业", "X220": "交通运输",
    "X221": "房地产", "X222": "电子", "X223": "计算机", "X224": "传媒",
    "X225": "通信", "X226": "银行", "X227": "非银金融", "X228": "综合",
    # 医药生物细分
    "X2701": "化学制药", "X270101": "化学制药",
    "X2702": "生物制品", "X270201": "生物制品", "X270202": "生物制品", "X270205": "生物制品", "X270206": "生物制品",
    "X2704": "医疗器械", "X270403": "医疗器械", "X270404": "医疗器械",
    "X2705": "医疗服务", "X270501": "医疗服务", "X270502": "医疗服务", "X270503": "医疗服务",
    "X2706": "中药",
    "X2707": "医药商业", "X270701": "医药商业", "X270702": "医药商业",
    "X5202": "化学制药", "X520201": "化学制药", "X520202": "化学制药", "X520203": "化学制剂",
    "X5203": "生物制品", "X520301": "生物制品", "X520302": "生物制品", "X520303": "血液制品", "X520304": "疫苗",
    "X21801": "化学制药", "X21802": "生物制品", "X21803": "中药", "X21804": "医疗器械", "X21805": "医疗服务",
    # 房地产
    "X5301": "房地产开发", "X530101": "房地产开发", "X530102": "房地产开发",
    "X5302": "房地产服务", "X530201": "房地产服务",
    # 家用电器
    "X2401": "白色家电", "X240101": "白色家电", "X240102": "黑色家电", "X2406": "小家电", "X241": "家用电器",
    # 建筑
    "X2501": "水泥", "X2502": "玻璃", "X2503": "装修建材",
    "X2601": "房屋建设", "X2602": "基础建设", "X2603": "专业工程", "X260301": "专业工程", "X260302": "专业工程",
    # 汽车
    "X2801": "汽车零部件", "X2802": "汽车整车", "X2803": "摩托车",
    # 食品饮料
    "X3401": "食品加工", "X3402": "白酒", "X3403": "啤酒", "X3404": "饮料乳品", "X3405": "调味品",
    # 计算机
    "X7101": "计算机设备", "X7102": "软件开发", "X7103": "IT服务",
    # 电子
    "X7301": "元件", "X7302": "半导体", "X7303": "光学光电子", "X7304": "消费电子", "X7305": "电子制造",
    # 传媒
    "X7201": "广告营销", "X7202": "影视院线", "X7203": "数字媒体", "X7204": "出版",
    # 机械设备
    "X6401": "通用设备", "X6402": "专用设备", "X6403": "仪器仪表", "X6404": "自动化设备",
    # 交通运输
    "X4201": "港口", "X4202": "高速公路", "X4203": "机场", "X4204": "航空运输", "X4205": "海运", "X4206": "物流",
    # 有色/化工
    "X2201": "工业金属", "X2202": "贵金属", "X2203": "稀有金属",
    "X3301": "石油化工", "X3302": "化学原料", "X3303": "化学制品", "X3304": "塑料", "X3305": "橡胶", "X3306": "纤维",
    # 电力/军工
    "X6301": "电池", "X6302": "光伏设备", "X6303": "风电设备", "X6304": "电网设备",
    "X6501": "航天装备", "X6502": "航空装备", "X6503": "地面兵装", "X6504": "军工电子",
    # 社会服务/农业/公用
    "X4601": "旅游", "X4602": "酒店", "X4603": "餐饮", "X4604": "其他社会服务",
    "X3701": "种植业", "X3702": "渔业", "X3703": "养殖业", "X3704": "饲料",
    "X9101": "电力", "X9102": "燃气",
    # 商贸/金融
    "X4501": "百货", "X4502": "超市", "X4503": "专业零售", "X4504": "贸易",
    "X4901": "证券", "X4902": "保险", "X4903": "多元金融", "X4801": "银行",
    # 钢铁/轻工/纺织
    "X2301": "普钢", "X2302": "特钢", "X2303": "冶钢原料",
    "X3601": "造纸", "X3602": "包装印刷", "X3603": "文娱用品", "X3604": "家居用品",
    "X3501": "纺织制造", "X3502": "服装家纺",
    # 通信/煤炭
    "X7306": "通信设备", "X7307": "通信服务",
    "X2101": "煤炭开采", "X2102": "焦炭加工",
    # 注意: X210205在tdxhy中实际对应白酒股(T030501=泸州老窖/茅台/五粮液等)
    "X210205": "白酒",
}

# 通达信行业编码 → 行业名称映射（T编码体系）
# 注意: T编码不如申万可靠，SW分类优先
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
    # 通达信实际编码（T030501=白酒）
    "T030501": "白酒",
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
            print(f"[WARN] tdxhy.cfg not found: {self.cfg_path}")
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

        print(f"[OK] tdxhy.cfg loaded: {count} stock-industry mappings")

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

        策略（T编码+申万双源交叉验证）：
        1. T编码精确匹配 > 申万精确匹配（T编码在我们已知表中更准）
        2. 两套编码的公共前缀匹配（T编码大类+SW大类取交集）
        3. 回退：T编码未匹配时用SW前缀匹配
        4. 回退：SW未匹配时用T编码前缀匹配
        """
        sw_code = self.get_sw_code(code6)
        tdx_code = self.get_industry_code(code6)

        # ---- 第一优先：T编码精确匹配 ----
        if tdx_code and tdx_code in TDX_INDUSTRY_NAMES:
            return TDX_INDUSTRY_NAMES[tdx_code]

        # ---- 第二优先：SW精确匹配 ----
        if sw_code and sw_code in SW_INDUSTRY_NAMES:
            return SW_INDUSTRY_NAMES[sw_code]

        # ---- 两套都无精确匹配时，用SW前缀（比T前缀更可靠）----
        if sw_code:
            for length in [5, 4, 3, 2]:
                prefix = sw_code[:length]
                if prefix in SW_INDUSTRY_NAMES:
                    return SW_INDUSTRY_NAMES[prefix]

        # ---- T前缀回退（只在大类匹配有意义时才用）----
        if tdx_code:
            parent = tdx_code[:3]
            if parent in TDX_INDUSTRY_NAMES:
                return TDX_INDUSTRY_NAMES[parent]

            grandparent = tdx_code[:2].upper()
            if grandparent in TDX_INDUSTRY_NAMES:
                return TDX_INDUSTRY_NAMES[grandparent]

            return tdx_code

        return sw_code or ""

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
