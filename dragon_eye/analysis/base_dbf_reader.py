"""
dragon_eye.analysis.base_dbf_reader — 通达信base.dbf财务数据解析器

通达信本地财务数据库（3.7MB），包含全A股：
  - 资产负债表：总资产/流动资产/固定资产/负债/净资产...
  - 利润表：营收/利润/投资收益/补贴...
  - 股本结构：总股本/流通A股/B股/H股...
  - 其他：行业代码/地域/上市日期...

优点：
  - 比AkShare快100倍（本地文件 vs 网络请求）
  - 通达信官方维护，数据最权威
  - 一次加载全量缓存，后续查询零延迟

用法：
    reader = BaseDbfReader()
    fin = reader.get_financial("603618")
    summary = reader.get_financial_summary("603618")  # 格式化文本，给Agent用
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ============================================================
# 配置
# ============================================================

TDX_HQ_CACHE = os.environ.get(
    "TDX_HQ_CACHE",
    "D:/new_tdx_test/T0002/hq_cache",
)
BASE_DBF_PATH = os.path.join(TDX_HQ_CACHE, "base.dbf")

# 字段映射：base.dbf缩写 → 中文标准名
FIELD_MAP = {
    "GPDM": "股票代码",
    "GXRQ": "更新日期",
    "ZGB": "总股本",
    "GJG": "国家股",
    "FQRFRG": "发起人法人股",
    "FRG": "法人股",
    "BG": "B股",
    "HG": "H股",
    "LTAG": "流通A股",
    "ZGG": "转配股",
    "ZPG": "配股",
    "ZZC": "总资产",
    "LDZC": "流动资产",
    "GDZC": "固定资产",
    "WXZC": "无形资产",
    "CQTZ": "长期投资",
    "LDFZ": "流动负债",
    "CQFZ": "长期负债",
    "ZBGJJ": "资本公积金",
    "JZC": "净资产",
    "ZYSY": "主营业务收入",
    "ZYLY": "主营业务利润",
    "QTLY": "其他利润",
    "YYLY": "营业利润",
    "TZSY": "投资收益",
    "BTSY": "补贴收入",
    "YYWSZ": "营业外收支",
    "SNSYTZ": "少数股东权益",
    "LYZE": "利润总额",
    "SHLY": "税后利润",
    "JLY": "净利润",
    "WFPLY": "未分配利润",
    "TZMGJZ": "投资买股价值",
    "DY": "地域",
    "HY": "行业代码",
    "ZBNB": "报表类别",
    "SSDATE": "上市日期",
    "MODIDATE": "修改日期",
    "GDRS": "股东人数",
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class FinancialData:
    """单只股票的完整财务数据"""
    code: str = ""                  # 6位代码
    name: str = ""                  # 名称（外部补充）
    update_date: str = ""           # 财报更新日期

    # 股本结构（单位：万股）
    total_shares: float = 0         # 总股本
    circulating_a: float = 0        # 流通A股
    b_shares: float = 0             # B股
    h_shares: float = 0             # H股

    # 资产负债表（单位：万元）
    total_assets: float = 0         # 总资产
    current_assets: float = 0       # 流动资产
    fixed_assets: float = 0         # 固定资产
    intangible_assets: float = 0    # 无形资产
    long_term_invest: float = 0     # 长期投资
    current_liabilities: float = 0  # 流动负债
    long_term_liabilities: float = 0  # 长期负债
    capital_reserve: float = 0      # 资本公积金
    net_assets: float = 0           # 净资产

    # 利润表（单位：万元）
    revenue: float = 0              # 主营业务收入
    main_profit: float = 0          # 主营业务利润
    operating_profit: float = 0     # 营业利润
    invest_income: float = 0        # 投资收益
    subsidy: float = 0              # 补贴收入
    non_operating: float = 0        # 营业外收支
    total_profit: float = 0         # 利润总额
    net_profit: float = 0           # 净利润
    undistributed: float = 0        # 未分配利润

    # 衍生指标（计算得出）
    debt_ratio: float = 0           # 资产负债率 (%)
    roe: float = 0                  # 净资产收益率 (%)
    eps_approx: float = 0           # 近似每股收益 (元)
    current_ratio: float = 0        # 流动比率
    net_profit_margin: float = 0    # 净利率 (%)
    revenue_per_share: float = 0    # 每股营收 (元)

    # 其他
    industry_code: str = ""         # 行业代码
    region: str = ""                # 地域
    list_date: str = ""             # 上市日期

    def is_valid(self) -> bool:
        """是否有有效数据"""
        return self.code != "" and (self.total_assets > 0 or self.net_assets > 0)


# ============================================================
# 解析器
# ============================================================

class BaseDbfReader:
    """通达信base.dbf财务数据解析器

    用法:
        reader = BaseDbfReader()
        fin = reader.get_financial("603618")
        print(fin.roe, fin.debt_ratio)
        summary = reader.get_financial_summary("603618")  # Agent可读文本
    """

    def __init__(self, dbf_path: str = BASE_DBF_PATH):
        self.dbf_path = dbf_path
        self._data: dict[str, dict] = {}  # code6 → raw record
        self._financials: dict[str, FinancialData] = {}  # code6 → FinancialData
        self._loaded = False

    def _ensure_loaded(self):
        """懒加载：首次查询时读取dbf文件"""
        if self._loaded:
            return
        self._load_dbf()
        self._loaded = True

    def _load_dbf(self):
        """读取base.dbf，解析全量数据到内存"""
        if not os.path.isfile(self.dbf_path):
            print(f"⚠️ base.dbf 不存在: {self.dbf_path}")
            return

        try:
            from dbfread import DBF
        except ImportError:
            print("⚠️ dbfread 未安装，请运行: pip install dbfread")
            return

        table = DBF(self.dbf_path, encoding="gbk")
        count = 0
        for record in table:
            code = str(record.get("GPDM", "")).strip()
            if not code or len(code) != 6 or not code.isdigit():
                continue
            self._data[code] = {k: v for k, v in record.items() if v is not None}
            count += 1

        print(f"✅ base.dbf 加载完成: {count} 只股票")

    def _parse_date(self, val) -> str:
        """解析通达信日期格式 (20260425 → 2026-04-25)"""
        s = str(val).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return s

    def _safe_float(self, val, default: float = 0.0) -> float:
        """安全转float"""
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _build_financial(self, code6: str) -> FinancialData:
        """从原始记录构建FinancialData"""
        raw = self._data.get(code6, {})
        if not raw:
            return FinancialData(code=code6)

        # 股本结构
        total_shares = self._safe_float(raw.get("ZGB"))
        circulating_a = self._safe_float(raw.get("LTAG"))
        b_shares = self._safe_float(raw.get("BG"))
        h_shares = self._safe_float(raw.get("HG"))

        # 资产负债表
        total_assets = self._safe_float(raw.get("ZZC"))
        current_assets = self._safe_float(raw.get("LDZC"))
        fixed_assets = self._safe_float(raw.get("GDZC"))
        intangible_assets = self._safe_float(raw.get("WXZC"))
        long_term_invest = self._safe_float(raw.get("CQTZ"))
        current_liabilities = self._safe_float(raw.get("LDFZ"))
        long_term_liabilities = self._safe_float(raw.get("CQFZ"))
        capital_reserve = self._safe_float(raw.get("ZBGJJ"))
        net_assets = self._safe_float(raw.get("JZC"))

        # 利润表
        revenue = self._safe_float(raw.get("ZYSY"))
        main_profit = self._safe_float(raw.get("ZYLY"))
        operating_profit = self._safe_float(raw.get("YYLY"))
        invest_income = self._safe_float(raw.get("TZSY"))
        subsidy = self._safe_float(raw.get("BTSY"))
        non_operating = self._safe_float(raw.get("YYWSZ"))
        total_profit = self._safe_float(raw.get("LYZE"))
        net_profit = self._safe_float(raw.get("JLY"))
        undistributed = self._safe_float(raw.get("WFPLY"))

        # ---- 衍生指标计算 ----
        # 资产负债率
        total_liabilities = current_liabilities + long_term_liabilities
        debt_ratio = (total_liabilities / total_assets * 100) if total_assets > 0 else 0

        # ROE
        roe = (net_profit / net_assets * 100) if net_assets > 0 else 0

        # 近似每股收益（万元/万股 = 元/股）
        eps_approx = (net_profit / circulating_a) if circulating_a > 0 else 0

        # 流动比率
        current_ratio = (current_assets / current_liabilities) if current_liabilities > 0 else 0

        # 净利率
        net_profit_margin = (net_profit / revenue * 100) if revenue > 0 else 0

        # 每股营收
        revenue_per_share = (revenue / circulating_a) if circulating_a > 0 else 0

        # 行业/地域
        hy = str(raw.get("HY", "")).strip()
        dy = str(raw.get("DY", "")).strip()
        list_date_val = raw.get("SSDATE", "")

        return FinancialData(
            code=code6,
            update_date=self._parse_date(raw.get("GXRQ", "")),
            total_shares=total_shares,
            circulating_a=circulating_a,
            b_shares=b_shares,
            h_shares=h_shares,
            total_assets=total_assets,
            current_assets=current_assets,
            fixed_assets=fixed_assets,
            intangible_assets=intangible_assets,
            long_term_invest=long_term_invest,
            current_liabilities=current_liabilities,
            long_term_liabilities=long_term_liabilities,
            capital_reserve=capital_reserve,
            net_assets=net_assets,
            revenue=revenue,
            main_profit=main_profit,
            operating_profit=operating_profit,
            invest_income=invest_income,
            subsidy=subsidy,
            non_operating=non_operating,
            total_profit=total_profit,
            net_profit=net_profit,
            undistributed=undistributed,
            debt_ratio=round(debt_ratio, 2),
            roe=round(roe, 2),
            eps_approx=round(eps_approx, 4),
            current_ratio=round(current_ratio, 2),
            net_profit_margin=round(net_profit_margin, 2),
            revenue_per_share=round(revenue_per_share, 4),
            industry_code=hy,
            region=dy,
            list_date=self._parse_date(list_date_val),
        )

    # --- 公开接口 ---

    def get_financial(self, code6: str) -> Optional[FinancialData]:
        """获取单只股票的财务数据"""
        self._ensure_loaded()

        if code6 in self._financials:
            return self._financials[code6]

        if code6 not in self._data:
            return None

        fin = self._build_financial(code6)
        self._financials[code6] = fin  # 缓存
        return fin

    def get_all_codes(self) -> list[str]:
        """获取所有有财务数据的股票代码"""
        self._ensure_loaded()
        return list(self._data.keys())

    def get_all_financials(self) -> dict[str, FinancialData]:
        """获取全量财务数据（首次较慢，后续缓存）"""
        self._ensure_loaded()
        for code6 in self._data:
            if code6 not in self._financials:
                self._financials[code6] = self._build_financial(code6)
        return self._financials

    def get_financial_summary(self, code6: str) -> str:
        """生成格式化的财务摘要文本（给Agent用）

        返回 Markdown 格式，结构清晰，关键数据突出
        """
        fin = self.get_financial(code6)
        if fin is None or not fin.is_valid():
            return f"⚠️ 未找到 {code6} 的财务数据"

        lines = [
            f"## 📊 {fin.code} 财务数据摘要",
            f"**财报更新日期**: {fin.update_date}",
            "",
            "### 股本结构（万股）",
            f"- 总股本: {fin.total_shares:,.2f}",
            f"- 流通A股: {fin.circulating_a:,.2f}",
            f"- B股: {fin.b_shares:,.2f}" if fin.b_shares else "",
            f"- H股: {fin.h_shares:,.2f}" if fin.h_shares else "",
            "",
            "### 资产负债表（万元）",
            f"- **总资产**: {fin.total_assets:,.2f}",
            f"- 流动资产: {fin.current_assets:,.2f}",
            f"- 固定资产: {fin.fixed_assets:,.2f}",
            f"- 无形资产: {fin.intangible_assets:,.2f}",
            f"- 长期投资: {fin.long_term_invest:,.2f}",
            f"- **净资产**: {fin.net_assets:,.2f}",
            f"- 流动负债: {fin.current_liabilities:,.2f}",
            f"- 长期负债: {fin.long_term_liabilities:,.2f}",
            f"- **资产负债率**: {fin.debt_ratio:.2f}%",
            f"- **流动比率**: {fin.current_ratio:.2f}",
            "",
            "### 利润表（万元）",
            f"- **主营业务收入**: {fin.revenue:,.2f}",
            f"- 主营业务利润: {fin.main_profit:,.2f}",
            f"- **营业利润**: {fin.operating_profit:,.2f}",
            f"- 投资收益: {fin.invest_income:,.2f}",
            f"- 补贴收入: {fin.subsidy:,.2f}",
            f"- 营业外收支: {fin.non_operating:,.2f}",
            f"- **净利润**: {fin.net_profit:,.2f}",
            f"- 未分配利润: {fin.undistributed:,.2f}",
            "",
            "### 关键指标",
            f"- **ROE（净资产收益率）**: {fin.roe:.2f}%",
            f"- **每股收益（近似）**: {fin.eps_approx:.4f} 元",
            f"- **净利率**: {fin.net_profit_margin:.2f}%",
            f"- **每股营收**: {fin.revenue_per_share:.4f} 元",
            "",
            f"### 其他",
            f"- 行业代码: {fin.industry_code}",
            f"- 上市日期: {fin.list_date}",
        ]

        # 过滤空行
        return "\n".join(line for line in lines if line is not None and line != "")

    def get_industry_code(self, code6: str) -> str:
        """获取股票的行业代码"""
        self._ensure_loaded()
        raw = self._data.get(code6, {})
        return str(raw.get("HY", "")).strip()

    def get_stocks_by_industry(self, industry_code: str) -> list[str]:
        """获取同行业所有股票代码"""
        self._ensure_loaded()
        return [
            code for code, raw in self._data.items()
            if str(raw.get("HY", "")).strip() == industry_code
        ]


# ============================================================
# 全局单例
# ============================================================

_reader_instance: Optional[BaseDbfReader] = None

def get_dbf_reader(dbf_path: str = BASE_DBF_PATH) -> BaseDbfReader:
    """获取全局BaseDbfReader单例"""
    global _reader_instance
    if _reader_instance is None:
        _reader_instance = BaseDbfReader(dbf_path)
    return _reader_instance
