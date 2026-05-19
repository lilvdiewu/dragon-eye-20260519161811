"""
同花顺板块扫描器 — 按 radiant-cascade-turing.md 计划实施
==========================================================
6个模块:
  1. TdxSectorMapper    — 复用 ths_sector.py (已修复)
  2. ThsSectorFetcher   — AKShare同花顺实时数据
  3. SectorRanker       — 板块强度排名+轮动检测
  4. Ma120SectorFilter  — MA120信号标注板块信息
  5. SectorConsole      — 红涨绿跌控制台输出
  6. main()             — 协调器+CLI

CLI:
  python ths_sector_scanner.py                  # 完整运行
  python ths_sector_scanner.py --no-rotation    # 跳过轮动
  python ths_sector_scanner.py --sector-only    # 仅排名
  python ths_sector_scanner.py --csv            # 导出CSV
  python ths_sector_scanner.py --hot-filter any # 热门板块MA120
"""
import os, sys, time, argparse, json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

import pandas as pd
import numpy as np

# 项目根
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# TDX本地板块数据（零网络、秒级）
_tdx_reader = None
_TDX_AVAILABLE = False
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        'tdx_sector_reader',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tdx_sector_reader.py')
    )
    if _spec and _spec.loader:
        _tdx_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_tdx_mod)
        TdxSectorReader = _tdx_mod.TdxSectorReader
        _TDX_AVAILABLE = True
except Exception as e:
    print(f"[WARN] TDX reader加载失败: {e}，回退到AKShare")

# ── 颜色常量 ────────────────────────────────────────────
class C:
    R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; B = '\033[94m'
    M = '\033[95m'; C = '\033[96m'; W = '\033[97m'
    BOLD = '\033[1m'; DIM = '\033[2m'
    END = '\033[0m'
    @staticmethod
    def red(s): return f"{C.R}{s}{C.END}"
    @staticmethod
    def green(s): return f"{C.G}{s}{C.END}"
    @staticmethod
    def yellow(s): return f"{C.Y}{s}{C.END}"
    @staticmethod
    def cyan(s): return f"{C.C}{s}{C.END}"
    @staticmethod
    def bold(s): return f"{C.BOLD}{s}{C.END}"
    @staticmethod
    def dim(s): return f"{C.DIM}{s}{C.END}"


# ══════════════════════════════════════════════════════════
# Module 2: ThsSectorFetcher
# ══════════════════════════════════════════════════════════
class ThsSectorFetcher:
    """通过AKShare获取同花顺行业/概念板块实时数据"""

    def __init__(self):
        self._industries = None
        self._concepts = None
        self._industry_history = {}
        self._fetched = False
        self._tdx = None
        if _TDX_AVAILABLE:
            self._tdx = TdxSectorReader()
            self._tdx.load_sector_map()

    def fetch_all(self) -> bool:
        """获取行业和概念板块数据（含历史动量）
        
        优先级: AKShare实时 → TDX本地离线
        """
        online_ok = False
        
        # ── 尝试 AKShare 在线数据 ──
        try:
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                os.environ.pop(k, None)
            import akshare as ak

            print("[ThsSectorFetcher] 获取板块数据(AKShare)...")

            t0 = time.time()
            self._industries = ak.stock_board_industry_summary_ths()
            print(f"  行业汇总: {len(self._industries)} 个 ({time.time()-t0:.1f}s)")

            # 概念板块全部用本地 infoharbor_block.dat (718个,含成分股数)
            self._concepts = pd.DataFrame()  # 本地数据在mapper中
            print(f"  概念板块: 使用本地718个")

            online_ok = True
        except Exception as e:
            print(f"[ThsSectorFetcher] AKShare获取失败: {e}")
        
        # ── TDX 本地数据 ──
        if self._tdx is not None:
            print(f"[ThsSectorFetcher] 使用TDX本地数据(动量)...")
            t0 = time.time()
            
            if online_ok and self._industries is not None:
                # AKShare成功: 模糊匹配映射动量
                akshare_names = [
                    str(row.get("板块", "")) for _, row in self._industries.iterrows()
                ]
                tdx_names = list(self._tdx._name_to_code.keys())
                
                # Known AKShare→TDX name mapping (同花顺 vs 通达信差异)
                KNOWN_NAME_MAP = {
                    # === 名称差异映射 ===
                    "IT服务": "软件服务",
                    "油气开采服务": "油服工程",
                    "房地产服务": "房产服务",
                    "文化传媒": "传媒",
                    "旅游及酒店": "旅游",
                    "建筑材料": "建材",
                    "港口航运": "港口",
                    "化学纤维": "化纤",
                    "种植业与林业": "种植业",
                    "饮料乳品": "饮料",
                    "家电": "家用电器",
                    "环保装备": "环保",
                    "汽车服务": "汽车服务",
                    # === 以下同名或TDX已有精确匹配，仅确保回退 ===
                    "小金属": "小金属",
                    "电池": "电池",
                    "风电设备": "风电设备",
                    "光伏设备": "光伏设备",
                    "军工电子": "军工电子",
                    "航空装备": "航空装备",
                    "航天装备": "航天装备",
                    "航海装备": "航海装备",
                    "医疗器械": "医疗器械",
                    "医疗服务": "医疗服务",
                    "医药商业": "医药商业",
                    "中药": "中药",
                    "生物制品": "生物制品",
                    "化学制药": "化学制药",
                    "白酒": "白酒",
                    "调味品": "调味品",
                    "休闲食品": "休闲食品",
                    "养殖业": "养殖业",
                    "饲料": "饲料",
                    "渔业": "渔业",
                    "半导体": "半导体",
                    "元器件": "元器件",
                    "消费电子": "消费电子",
                    "光学光电": "光学光电",
                    "通信设备": "通信设备",
                    "通信服务": "通信服务",
                    "银行": "银行",
                    "证券": "证券",
                    "保险": "保险",
                    "煤炭开采": "煤炭开采",
                    "焦炭加工": "焦炭加工",
                    "石油开采": "石油开采",
                    "石油加工": "石油加工",
                    "普钢": "普钢",
                    "特种钢": "特种钢",
                    "工业金属": "工业金属",
                    "贵金属": "贵金属",
                    "能源金属": "能源金属",
                    # === 新增：TDX模糊匹配确认 ===
                    "专用设备": "专用设备",
                    "公路铁路运输": "公路铁路",
                    "元件": "元器件",
                    "化学制药": "化学制药",
                    "化学原料": "化学原料",
                    "化学制品": "化学制品",
                    "包装印刷": "包装印刷",
                    "厨房电器": "家用电器",
                    "家居用品": "家居用品",
                    "小家电": "小家电",
                    "工程机械": "工程机械",
                    "影视院线": "影视院线",
                    "房地产开发": "房地产",
                    "服装家纺": "服装家纺",
                    "橡胶制品": "橡胶制品",
                    "汽车零部件": "汽车零部件",
                    "汽车整车": "汽车整车",
                    "游戏": "游戏",
                    "煤炭开采加工": "煤炭开采",
                    "燃气": "燃气",
                    "物流": "物流",
                    "环保设备": "环保设备",
                    "环境治理": "环境治理",
                    "电力": "电力",
                    "电子化学品": "电子化学品",
                    "电网设备": "电网设备",
                    "白色家电": "白色家电",
                    "石油加工贸易": "石油加工",
                    "纺织制造": "纺织制造",
                    "综合": "综合",
                    "自动化设备": "自动化设备",
                    "贸易": "贸易",
                    "轨交设备": "轨交设备",
                    "造纸": "造纸",
                    "金属新材料": "金属新材料",
                    "钢铁": "钢铁",
                    "非金属材料": "非金属材料",
                    "食品加工制造": "食品加工",
                    "黑色家电": "黑色家电",
                }
                
                # Character overlap for fuzzy matching
                def _char_overlap(a: str, b: str) -> float:
                    sa, sb = set(a.replace(' ', '')), set(b.replace(' ', ''))
                    if not sa or not sb:
                        return 0
                    return len(sa & sb) / len(sa | sb)
                
                name_map = {}
                for aname in akshare_names:
                    if not aname:
                        continue
                    # Exact match
                    if aname in self._tdx._name_to_code:
                        name_map[aname] = aname
                        continue
                    # Known mapping
                    if aname in KNOWN_NAME_MAP:
                        mapped = KNOWN_NAME_MAP[aname]
                        if mapped in self._tdx._name_to_code:
                            name_map[aname] = mapped
                            continue
                    # Substring match
                    matched = None
                    for tname in tdx_names:
                        if aname in tname or tname in aname:
                            matched = tname
                            break
                    # Character overlap fallback
                    if not matched:
                        best_score = 0.35
                        for tname in tdx_names:
                            score = _char_overlap(aname, tname)
                            if score > best_score:
                                best_score = score
                                matched = tname
                    if matched:
                        name_map[aname] = matched
                
                tdx_df = self._tdx.get_all_sectors()
                if not tdx_df.empty:
                    tdx_mom = {}
                    for _, row in tdx_df.iterrows():
                        tdx_mom[row['name']] = {
                            'momentum_3d': row.get('momentum_3d', 0),
                            'momentum_5d': row.get('momentum_5d', 0),
                            'volume_ratio': row.get('volume_ratio', 0),
                        }
                    
                    for aname, tname in name_map.items():
                        if tname in tdx_mom:
                            self._industry_history[aname] = tdx_mom[tname]
                    
                    # 同时按TDX原名存储(概念板块关联用)
                    for tname, mom_data in tdx_mom.items():
                        if tname not in self._industry_history:
                            self._industry_history[tname] = mom_data
                    
                    print(f"  TDX动量: {len(self._industry_history)}/{len(akshare_names)} "
                          f"({time.time()-t0:.1f}s)")
            else:
                # AKShare失败: 直接用TDX排名
                tdx_df = self._tdx.get_all_sectors()
                if not tdx_df.empty:
                    self._build_tdx_industries(tdx_df)
                    print(f"  TDX离线排名: {len(self._industries)} 板块 ({time.time()-t0:.1f}s)")
        
        elif not online_ok:
            print("[ThsSectorFetcher] 无可用的数据源(AKShare+TDX均失败)")
            return False
        
        # ── AKShare 回退动量(无TDX时) ──
        if not self._tdx and online_ok and self._industries is not None:
            print(f"[ThsSectorFetcher] 拉取行业历史(动量, top20)...")
            t0 = time.time()
            top_indices = sorted(
                range(len(self._industries)),
                key=lambda i: abs(self._safe_float_row(
                    self._industries.iloc[i], "涨跌幅")),
                reverse=True
            )[:20]
            for count, i in enumerate(top_indices):
                row = self._industries.iloc[i]
                name = str(row.get("板块", ""))
                if not name:
                    continue
                try:
                    hist = ak.stock_board_industry_index_ths(symbol=name)
                    if hist is not None and not hist.empty:
                        self._industry_history[name] = hist
                except Exception:
                    pass
                if (count + 1) % 5 == 0:
                    print(f"  行业历史: {count+1}/20 ({time.time()-t0:.1f}s)")
                time.sleep(0.12)
            print(f"  行业历史完成: {len(self._industry_history)}/20 "
                  f"({time.time()-t0:.1f}s)")

        self._fetched = True
        return True if (online_ok or self._industries is not None) else False
    
    def _build_tdx_industries(self, tdx_df: pd.DataFrame):
        """用TDX数据构建AKShare兼容的行业汇总DataFrame"""
        rows = []
        df_sorted = tdx_df.sort_values("change_pct", ascending=False)
        for rank, (_, row) in enumerate(df_sorted.iterrows(), 1):
            rows.append({
                "序号": rank,
                "板块": row["name"],
                "涨跌幅": row["change_pct"],
                "净流入": None,
                "上涨家数": None,
                "下跌家数": None,
                "领涨股": "",
                "领涨股-涨跌幅": None,
            })
            # Also store momentum directly
            if row["name"] not in self._industry_history:
                self._industry_history[row["name"]] = {
                    'momentum_3d': row.get('momentum_3d', 0),
                    'momentum_5d': row.get('momentum_5d', 0),
                    'volume_ratio': row.get('volume_ratio', 0),
                }
        self._industries = pd.DataFrame(rows)
        self._concepts = pd.DataFrame()  # TDX不区分行业/概念时留空

    @property
    def industries(self) -> pd.DataFrame:
        return self._industries

    @property
    def concepts(self) -> pd.DataFrame:
        return self._concepts

    @staticmethod
    def _safe_float_row(row, *keys, default=0.0):
        for key in keys:
            val = row.get(key)
            if val is not None and str(val) not in ("", "nan", "None"):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        return default

    def get_sector_data(self, name: str, kind: str = "industry") -> Optional[Dict]:
        """获取单个板块的详细信息（含成分股涨跌比）"""
        try:
            import akshare as ak
            if kind == "industry":
                df = ak.stock_board_industry_info_ths(symbol=name)
            else:
                df = ak.stock_board_concept_info_ths(symbol=name)
            if df is None or df.empty:
                return None
            # 转换成dict
            result = {}
            for _, row in df.iterrows():
                k = str(row.iloc[0])
                v = str(row.iloc[1])
                result[k] = v
            return result
        except Exception:
            return None


# ══════════════════════════════════════════════════════════
# Module 3: SectorRanker
# ══════════════════════════════════════════════════════════
@dataclass
class SectorScore:
    name: str
    code: str
    kind: str  # industry / concept
    change_pct: float = 0.0      # 涨跌幅
    net_inflow: float = 0.0      # 净流入(亿)
    up_ratio: float = 0.0        # 上涨家数占比
    turnover: float = 0.0        # 换手率
    momentum_3d: float = 0.0     # 3日动量
    momentum_5d: float = 0.0     # 5日动量
    total_score: float = 0.0
    grade: str = ""
    up_stocks: int = 0
    down_stocks: int = 0
    leading_stock: str = ""
    leading_change: float = 0.0
    # 轮动字段
    momentum_accel: float = 0.0  # 动量加速度(3d-5d)
    rotation_signal: str = ""    # 加速上攻/持续强势/触底反弹/弱势下行

    def grade_label(self) -> str:
        g = self.grade
        if g == "S": return C.bold(C.red(f"[S]"))
        if g == "A": return C.red(f"[A]")
        if g == "B": return C.yellow(f"[B]")
        return C.dim(f"[C]")


class SectorRanker:
    """板块强度排名 + 轮动检测

    评分公式: 涨跌幅30% + 净流入20% + 上涨家数占比15% +
              换手10% + 3日动量15% + 5日动量10%
    S(>=80) | A(>=60) | B(>=40) | C(<40)
    """

    WEIGHTS = {
        "change_pct": 0.30,
        "net_inflow": 0.20,
        "up_ratio": 0.15,
        "turnover": 0.10,
        "momentum_3d": 0.15,
        "momentum_5d": 0.10,
    }

    def __init__(self, fetcher: ThsSectorFetcher, mapper=None):
        self.fetcher = fetcher
        self.mapper = mapper
        self.industry_scores: List[SectorScore] = []
        self.concept_scores: List[SectorScore] = []

    def rank_all(self) -> Tuple[List[SectorScore], List[SectorScore]]:
        """排名所有行业和概念板块

        行业: 使用 stock_board_industry_summary_ths (有实时涨跌数据)
        概念: summary API无涨跌数据，改为列出概念名称+成分股数
        """
        if not self.fetcher._fetched:
            print("[SectorRanker] 数据未获取，请先运行 Fetcher.fetch_all()")
            return [], []

        self.industry_scores = self._rank_industry(self.fetcher.industries)
        self.concept_scores = self._list_concepts(self.fetcher.concepts)
        return self.industry_scores, self.concept_scores

    def _rank_industry(self, df: pd.DataFrame) -> List[SectorScore]:
        """排名行业板块（有完整数据）"""
        return self._rank(df, "industry")

    def _rank(self, df: pd.DataFrame, kind: str) -> List[SectorScore]:
        if df is None or df.empty:
            return []

        scores = []
        # 实际列名: 序号, 板块, 涨跌幅, 总成交量, 总成交额, 净流入,
        #           上涨家数, 下跌家数, 均价, 领涨股, 领涨股-最新价, 领涨股-涨跌幅
        for _, row in df.iterrows():
            try:
                name = str(row.get("板块", ""))
                if not name:
                    continue

                change_pct = self._safe_float(row, "涨跌幅")
                up_stocks = int(self._safe_float(row, "上涨家数"))
                down_stocks = int(self._safe_float(row, "下跌家数"))
                total_s = up_stocks + down_stocks
                up_ratio = up_stocks / total_s if total_s > 0 else 0.5

                net_inflow = self._safe_float(row, "净流入")  # API已返回亿元

                # 换手率: API无此字段，用总成交额/均价估算 或 取中位
                turnover = 0.0
                vol = self._safe_float(row, "总成交量")
                if vol > 0:
                    turnover = vol / 1e6  # 粗略归一化

                # 动量: 从历史指数计算3日/5日涨跌幅
                mom_3d, mom_5d = 0.0, 0.0
                hist = self.fetcher._industry_history.get(name)
                if hist is not None:
                    # TDX格式: dict with momentum_3d/momentum_5d
                    if isinstance(hist, dict):
                        mom_3d = hist.get('momentum_3d', 0.0)
                        mom_5d = hist.get('momentum_5d', 0.0)
                    # AKShare格式: DataFrame with close column
                    elif hasattr(hist, 'empty') and not hist.empty:
                        try:
                            close_col = None
                            for c in ["收盘", "收盘价", "close"]:
                                if c in hist.columns:
                                    close_col = c
                                    break
                            if close_col:
                                closes = [float(v) for v in hist[close_col].values if v]
                            else:
                                closes = [float(v) for v in hist.iloc[:, 2].values if v]
                            if len(closes) >= 6:
                                mom_3d = round((closes[-1] / closes[-4] - 1) * 100, 2)
                                mom_5d = round((closes[-1] / closes[-6] - 1) * 100, 2)
                            elif len(closes) >= 4:
                                mom_3d = round((closes[-1] / closes[-4] - 1) * 100, 2)
                        except Exception:
                            pass

                # 领涨股
                leading = str(row.get("领涨股", ""))
                lead_chg = self._safe_float(row, "领涨股-涨跌幅")

                # 评分: 缺失字段给中位分0.5
                scores_norm = {
                    "change_pct": self._norm(change_pct, -10, 10),
                    "net_inflow": self._norm(net_inflow, -5, 20),
                    "up_ratio": up_ratio,
                    "turnover": min(turnover / 20, 1.0) if turnover > 0 else 0.5,
                    "momentum_3d": self._norm(mom_3d, -10, 10),
                    "momentum_5d": self._norm(mom_5d, -10, 10),
                }
                total_score = sum(
                    scores_norm[k] * w * 100 for k, w in self.WEIGHTS.items()
                )

                # 等级
                if total_score >= 80:
                    grade = "S"
                elif total_score >= 60:
                    grade = "A"
                elif total_score >= 40:
                    grade = "B"
                else:
                    grade = "C"

                # 轮动信号
                momentum_accel = mom_3d - mom_5d
                if mom_3d > 0 and momentum_accel > 1:
                    rotation = "加速上攻"
                elif mom_3d > 0:
                    rotation = "持续强势"
                elif mom_5d < 0 and mom_3d > 0:
                    rotation = "触底反弹"
                elif mom_3d < 0:
                    rotation = "弱势下行"
                else:
                    rotation = "持续强势"

                scores.append(SectorScore(
                    name=name, code="", kind=kind,
                    change_pct=change_pct, net_inflow=net_inflow,
                    up_ratio=up_ratio, turnover=turnover,
                    momentum_3d=mom_3d, momentum_5d=mom_5d,
                    total_score=round(total_score, 1), grade=grade,
                    up_stocks=up_stocks, down_stocks=down_stocks,
                    leading_stock=leading, leading_change=lead_chg or 0,
                    momentum_accel=round(momentum_accel, 2),
                    rotation_signal=rotation,
                ))
            except Exception:
                continue

        scores.sort(key=lambda x: x.total_score, reverse=True)
        return scores

    def _list_concepts(self, df: pd.DataFrame) -> List[SectorScore]:
        """概念板块：本地 infoharbor_block.dat + TDX行业动量关联"""
        scores = []
        seen_names = set()
        
        # 从 mapper 取本地概念→成分股映射
        concept_map = {}
        if self.mapper:
            concept_map = getattr(self.mapper, '_concept_map', {}) or {}
        
        # 按成分股数降序
        sorted_concepts = sorted(concept_map.items(), key=lambda x: len(x[1]), reverse=True)
        
        for cname, stocks in sorted_concepts:
            if cname in seen_names:
                continue
            seen_names.add(cname)
            count = len(set(stocks))  # 去重
            
            # 关联TDX行业动量
            mom_3d, mom_5d = 0.0, 0.0
            tdx_name = self._concept_to_tdx_industry(cname)
            if tdx_name and self.fetcher._tdx:
                hist = self.fetcher._industry_history.get(tdx_name, {})
                if isinstance(hist, dict):
                    mom_3d = hist.get('momentum_3d', 0.0)
                    mom_5d = hist.get('momentum_5d', 0.0)
            
            scores.append(SectorScore(
                name=cname, code="", kind="concept",
                total_score=count,
                grade="",
                up_stocks=count, down_stocks=0,
                momentum_3d=mom_3d, momentum_5d=mom_5d,
                rotation_signal=tdx_name or "",
            ))
        
        # 补充AKShare概念列表(不在infoharbor中的)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = str(row.get("概念名称", row.get("name", "")))
                if not name or name in seen_names:
                    continue
                scores.append(SectorScore(
                    name=name, code="", kind="concept",
                    total_score=0, grade="-",
                    rotation_signal="",
                ))
        
        return scores
    
    def _concept_to_tdx_industry(self, concept_name: str) -> str:
        """概念名 → 最接近的TDX行业名 (用于关联动量)
        
        基于TDX实际板块名称(1070个)做关键词精确匹配。
        优先匹配最具体的板块(排在前面)。
        """
        if not self.fetcher._tdx:
            return ""
        tdx_names = self.fetcher._tdx._name_to_code
        
        # 关键词→TDX行业名(按具体度排序, 第一个匹配的优先)
        KEYWORD_MAP = [
            # 半导体/芯片
            ("半导体", ["半导体", "功率半导体", "半导体制造", "半导体封测"]),
            ("芯片", ["芯片", "MCU芯片", "存储芯片", "汽车芯片"]),
            
            # AI/智能
            ("人工智能", ["AIGC概念", "AI智能体"]),
            ("智能", ["机器人", "AIGC概念", "AI智能体"]),
            ("AI", ["AIGC概念", "AI智能体", "AI手机PC", "AI医疗概念"]),
            ("大模型", ["AIGC概念"]),
            ("DeepSeek", ["AIGC概念"]),
            ("软件", ["国产软件", "工业软件", "云软件服务", "基础软件"]),
            ("计算机", ["IT设备", "其他IT设备"]),
            ("IT", ["IT设备"]),
            ("数据", ["数据中心", "数据确权", "数据要素", "大数据"]),
            
            # 通信/5G
            ("通信", ["通信", "光通信", "通信工程", "其他通信设备"]),
            ("5G", ["光通信", "通信"]),
            
            # 新能源
            ("光伏", ["光伏", "光伏加工设备", "光伏发电", "光伏电池组件"]),
            ("电池", ["BC电池", "HJT电池"]),
            ("锂电", ["BC电池"]),
            ("储能", ["BC电池"]),
            
            # 汽车
            ("新能源车", ["汽车", "其他汽车零部件", "华为汽车"]),
            ("汽车", ["汽车", "其他汽车零部件"]),
            
            # 电力/能源
            ("电网", ["电力设备", "新型电力"]),
            ("电力", ["电力", "绿色电力"]),
            ("风电", ["新型电力"]),
            ("煤炭", ["煤炭开采"]),
            
            # 金融
            ("银行", ["全国性银行", "国有大型银行", "中小银行", "地方性银行"]),
            ("证券", ["证券"]),
            ("券商", ["证券"]),
            ("金融", ["全国性银行", "证券"]),
            
            # 消费
            ("白酒", ["白酒"]),
            ("食品", ["食品", "食品加工"]),
            ("饮料", ["白酒"]),
            ("零售", ["百货", "超市连锁", "一般零售"]),
            ("消费", ["消费电子"]),
            
            # 军工
            ("军工", ["国防军工", "军工电子", "军工信息化"]),
            ("航天", ["国防军工"]),
            
            # 医药
            ("医药", ["医药", "医药医疗", "医药流通"]),
            ("医疗", ["医药医疗", "医疗保健"]),
            ("创新药", ["医药"]),
            
            # 传媒/游戏
            ("传媒", ["传媒", "传媒娱乐"]),
            ("游戏", ["传媒娱乐"]),
            ("影视", ["传媒娱乐"]),
            
            # 其他
            ("机器人", ["机器人"]),
            ("人形", ["机器人"]),
            ("地产", ["全国地产", "区域地产", "园区地产"]),
            ("教育", ["教育培训"]),
            ("旅游", ["旅游"]),
            ("农业", ["种植业"]),
            ("养殖", ["养殖业"]),
        ]
        
        for kw, tdx_candidates in KEYWORD_MAP:
            if kw in concept_name:
                for tdx_name in tdx_candidates:
                    if tdx_name in tdx_names:
                        return tdx_name
                return ""  # 匹配了关键词但TDX里没有对应板块
        
        return ""

    def _safe_float(self, row, *keys, default=0.0, divide_by=1.0):
        for key in keys:
            val = row.get(key)
            if val is not None and str(val) not in ("", "nan", "None"):
                try:
                    return float(val) / divide_by
                except (ValueError, TypeError):
                    continue
        return default

    def _norm(self, val, vmin, vmax):
        """归一化到 [0, 1]"""
        if val is None:
            return 0.5
        return max(0, min(1, (val - vmin) / (vmax - vmin)))

    def get_hot_sectors(self, min_grade="B", top_n=15) -> List[SectorScore]:
        """获取热门板块"""
        grade_order = {"S": 0, "A": 1, "B": 2, "C": 3}
        threshold = grade_order.get(min_grade, 2)
        all_s = self.industry_scores + self.concept_scores
        hot = [s for s in all_s if grade_order.get(s.grade, 3) <= threshold]
        hot.sort(key=lambda x: x.total_score, reverse=True)
        return hot[:top_n]

    def get_rotation_signals(self) -> List[SectorScore]:
        """获取轮动信号板块（触底反弹+加速上攻）"""
        all_s = self.industry_scores + self.concept_scores
        seen = set()
        signals = []
        for s in all_s:
            if s.rotation_signal in ("触底反弹", "加速上攻") and s.name not in seen:
                seen.add(s.name)
                signals.append(s)
        signals.sort(key=lambda x: x.total_score, reverse=True)
        return signals


# ══════════════════════════════════════════════════════════
# Module 4: Ma120SectorFilter
# ══════════════════════════════════════════════════════════
class Ma120SectorFilter:
    """MA120信号标注板块信息（加分制，非硬过滤）

    - 热门行业: +15分
    - 热门概念: +10分
    - 双热门: 额外+5分
    """

    def __init__(self, sector_mapper, ranker: SectorRanker):
        self.sector_mapper = sector_mapper  # TdxSectorMapper
        self.ranker = ranker

    def annotate_signals(self, ma120_results: List[Dict]) -> List[Dict]:
        """给MA120扫描结果标注板块信息和加分"""
        if not ma120_results:
            print("[Ma120SectorFilter] 无MA120结果")
            return []

        # 获取热门板块名集合
        hot_industries = set()
        hot_concepts = set()
        for s in self.ranker.get_hot_sectors("B", top_n=30):
            if s.kind == "industry":
                hot_industries.add(s.name)
            else:
                hot_concepts.add(s.name)

        annotated = []
        for r in ma120_results:
            code = str(r.get("code", "")).zfill(6)
            result = dict(r)  # copy

            # 获取板块信息
            industry = self.sector_mapper.get_industry(code)
            concepts = self.sector_mapper.get_concepts(code)
            result["industry"] = industry or ""
            result["concepts"] = concepts

            # 加分
            bonus = 0
            reasons = []

            if industry and industry in hot_industries:
                bonus += 15
                reasons.append(f"热门行业({industry})+15")

            hot_con_list = [c for c in concepts if c in hot_concepts]
            if hot_con_list:
                bonus += 10 * min(len(hot_con_list), 2)  # 最多+20
                reasons.append(f"热门概念({','.join(hot_con_list[:2])})+{10*min(len(hot_con_list),2)}")

            if industry in hot_industries and hot_con_list:
                bonus += 5
                reasons.append("双热门+5")

            result["sector_bonus"] = bonus
            result["sector_reasons"] = reasons
            result["total_with_sector"] = float(result.get("score", 0)) + bonus

            annotated.append(result)

        # 按总分排序
        annotated.sort(key=lambda x: x["total_with_sector"], reverse=True)
        return annotated

    def filter_hot_only(self, annotated_results: List[Dict]) -> List[Dict]:
        """仅返回有板块加分的MA120信号"""
        return [r for r in annotated_results if r.get("sector_bonus", 0) > 0]


# ══════════════════════════════════════════════════════════
# Module 5: SectorConsole
# ══════════════════════════════════════════════════════════
class SectorConsole:
    """红涨绿跌控制台输出"""

    @staticmethod
    def _color_change(val: float) -> str:
        if val > 0:
            return C.red(f"+{val:.2f}%")
        elif val < 0:
            return C.green(f"{val:.2f}%")
        return f"{val:.2f}%"

    @staticmethod
    def _color_score(val: float) -> str:
        if val >= 80: return C.bold(C.red(f"{val:.0f}"))
        if val >= 60: return C.red(f"{val:.0f}")
        if val >= 40: return C.yellow(f"{val:.0f}")
        return C.dim(f"{val:.0f}")

    def print_header(self, title: str):
        print(f"\n{C.bold('─' * 60)}")
        print(f"  {C.bold(title)}")
        print(f"{C.bold('─' * 60)}")

    def print_sector_table(self, scores: List[SectorScore], max_rows=20,
                           rotation_only=False):
        """打印板块排名表"""
        rows = scores
        if rotation_only:
            rows = [s for s in scores if s.rotation_signal in
                    ("触底反弹", "加速上攻")]

        if not rows:
            print("  (无数据)")
            return

        header = (f"{'排名':<4} {'板块':<10} {'评分':<5} {'等级':<4} "
                  f"{'涨跌':<9} {'净流入':<9} {'上涨比':<6} {'换手':<6} "
                  f"{'3日':<8} {'5日':<8} {'轮动':<10} {'领涨':<8}")
        print(f"\n{C.dim(header)}")
        print(C.dim("-" * 95))

        for i, s in enumerate(rows[:max_rows], 1):
            rot_color = (lambda x: C.cyan(x) if x in ("触底反弹","加速上攻")
                         else (C.green(x) if x == "弱势下行" else C.yellow(x)))
            line = (f"{i:<4} {s.name:<10} "
                    f"{self._color_score(s.total_score):<5} "
                    f"{s.grade_label():<5} "
                    f"{self._color_change(s.change_pct):<9} "
                    f"{s.net_inflow:+.1f}".ljust(10) + " "
                    f"{s.up_ratio:.0%}".ljust(7) + " "
                    f"{s.turnover:.1f}".ljust(7) + " "
                    f"{self._color_change(s.momentum_3d):<8} "
                    f"{self._color_change(s.momentum_5d):<8} "
                    f"{rot_color(s.rotation_signal):<10} "
                    f"{s.leading_stock:<8}")
            print(line)

    def print_ma120_with_sector(self, annotated: List[Dict], max_rows=15):
        """打印标注了板块的MA120信号"""
        if not annotated:
            print("  (无信号)")
            return

        header = (f"{'代码':<8} {'名称':<8} {'评分':<6} {'板块加分':<8} "
                  f"{'总分':<6} {'行业':<14} {'热门概念':<20}")
        print(f"\n{C.dim(header)}")
        print(C.dim("-" * 75))

        for r in annotated[:max_rows]:
            code = r.get("code", "?")
            name = r.get("name", "?")
            score = r.get("score", 0)
            bonus = r.get("sector_bonus", 0)
            total = r.get("total_with_sector", score)
            industry = r.get("industry", "-")[:12]
            hot_cons = ",".join(r.get("concepts", [])[:2])[:18]

            bonus_str = C.red(f"+{bonus}") if bonus > 0 else C.dim("0")
            line = (f"{code:<8} {name:<8} {score:<6.0f} {bonus_str:<10} "
                    f"{self._color_score(total):<6} {industry:<14} {hot_cons:<20}")
            print(line)

    def print_rotation_summary(self, ranker: SectorRanker):
        """打印轮动摘要"""
        signals = ranker.get_rotation_signals()
        self.print_header("轮动信号 (触底反弹 + 加速上攻)")
        # 分类
        bounce = [s for s in signals if s.rotation_signal == "触底反弹"]
        surge = [s for s in signals if s.rotation_signal == "加速上攻"]

        if bounce:
            print(f"\n  {C.green('[触底反弹]')} (最适合MA120抄底):")
            for s in bounce:
                print(f"    {s.name:<14} 评分{C.red(f'{s.total_score:.0f}')} "
                      f"5日{C.green(f'{s.momentum_5d:+.2f}%')} "
                      f"→ 3日{C.red(f'{s.momentum_3d:+.2f}%')}")

        if surge:
            print(f"\n  {C.red('[加速上攻]')} (最强，适合追入):")
            for s in surge:
                print(f"    {s.name:<14} 评分{C.red(f'{s.total_score:.0f}')} "
                      f"3日{C.red(f'{s.momentum_3d:+.2f}%')} "
                      f"加速度{C.red(f'{s.momentum_accel:+.2f}')}")


# ══════════════════════════════════════════════════════════
# Module 6: main()
# ══════════════════════════════════════════════════════════
def main():
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description="同花顺板块数据扫描器")
    parser.add_argument("--no-rotation", action="store_true",
                        help="跳过轮动检测(快)")
    parser.add_argument("--sector-only", action="store_true",
                        help="仅看板块排名")
    parser.add_argument("--csv", type=str, nargs="?", const="sector_scan",
                        help="导出CSV(可选文件名)")
    parser.add_argument("--hot-filter", choices=["any", "industry", "concept"],
                        help="仅显示热门板块中的MA120信号")
    parser.add_argument("--top", type=int, default=15,
                        help="显示前N个板块")
    args = parser.parse_args()

    # Windows: 启用ANSI转义
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

    console = SectorConsole()
    t_start = time.time()

    # ── Step 1: 加载TDX本地映射 ──
    console.print_header("同花顺板块数据扫描器")
    t0 = time.time()
    # 绕过 __init__.py 的相对导入问题，直接load ths_sector模块
    import importlib.util
    mod_path = os.path.join(os.path.dirname(__file__), "ths_sector.py")
    spec = importlib.util.spec_from_file_location("ths_sector_mod", mod_path)
    ths_mod = importlib.util.module_from_spec(spec)
    sys.modules["ths_sector_mod"] = ths_mod  # 注册到sys.modules
    spec.loader.exec_module(ths_mod)
    TdxSectorMapper = ths_mod.TdxSectorMapper
    mapper = TdxSectorMapper()
    mapper.load_all()
    print(f"  TDX映射加载: {time.time()-t0:.1f}s | "
          f"行业={len(mapper.industry_map)} | 概念={len(mapper.concept_map)}")

    # ── Step 2: 获取AKShare实时数据 ──
    t0 = time.time()
    fetcher = ThsSectorFetcher()
    if not fetcher.fetch_all():
        print("[ERROR] 无法获取在线数据，仅显示本地映射信息")
        return
    print(f"  在线数据获取: {time.time()-t0:.1f}s")

    # ── Step 3: 排名 ──
    t0 = time.time()
    ranker = SectorRanker(fetcher, mapper)
    ind_scores, con_scores = ranker.rank_all()
    print(f"  排名完成: {time.time()-t0:.1f}s")

    # ── Step 4: 输出 ──
    console.print_header(f"行业板块排名 (Top {args.top})")
    console.print_sector_table(ind_scores, max_rows=args.top)

    # 概念板块：成分股数排名+关联行业动量
    console.print_header(f"概念板块 (热度排名, Top {min(args.top, 20)})")
    if con_scores:
        # Sort by total_score (stock count = hotness)
        con_sorted = sorted(con_scores, key=lambda s: s.total_score, reverse=True)[:min(args.top, 20)]
        print(f"  {'概念':<18} {'成分股':>5} {'关联行业':<14} {'3日动量':>8} {'5日动量':>8} {'龙头/事件'}")
        print(f"  {'-'*18} {'-'*5} {'-'*14} {'-'*8} {'-'*8} {'-'*20}")
        for s in con_sorted:
            # Get associated industry name
            tdx_name = ranker._concept_to_tdx_industry(s.name) or "-"
            print(f"  {s.name:<18} {s.up_stocks:>5} "
                  f"{tdx_name:<14} "
                  f"{console._color_change(s.momentum_3d):>8} "
                  f"{console._color_change(s.momentum_5d):>8} "
                  f"{s.rotation_signal[:30] if s.rotation_signal else '-'}")
    else:
        # Fallback: show local concept data
        print(f"  {C.cyan(str(len(mapper.concept_map)))} 个概念板块, "
              f"{C.cyan(str(len(mapper._stock_concepts)))} 只股票覆盖")
        sample_cons = list(mapper._concept_map.keys())[:10]
        shown = [f"{c}({len(mapper._concept_map[c])})" for c in sample_cons]
        print(f"  示例: {', '.join(shown)}")

    # ── Step 5: 轮动检测 ──
    if not args.no_rotation:
        t0 = time.time()
        console.print_rotation_summary(ranker)
        print(f"\n  轮动检测耗时: {time.time()-t0:.1f}s")

    # CSV导出（无论模式都做，如有）
    if args.csv:
        _export_csv(args.csv, ind_scores, con_scores, [])

    if args.sector_only:
        _print_summary(time.time() - t_start)
        return

    # ── Step 6: MA120扫描 ──
    console.print_header("MA120扫描 + 板块加成")
    t0 = time.time()
    try:
        ma120_filter = Ma120SectorFilter(mapper, ranker)
        ma120_results = _run_ma120_scan()
        annotated = ma120_filter.annotate_signals(ma120_results)
        print(f"  MA120扫描: {time.time()-t0:.1f}s | 原始信号={len(ma120_results)}")
    except Exception as e:
        print(f"  [WARN] MA120扫描失败: {e}")
        annotated = []

    if args.hot_filter:
        annotated = ma120_filter.filter_hot_only(annotated)
        console.print_header(f"热门板块MA120信号 (filter={args.hot_filter})")

    if annotated:
        console.print_ma120_with_sector(annotated)
    else:
        print("  (无MA120信号)")

    # ── CSV导出 ──
    if args.csv:
        _export_csv(args.csv, ind_scores, con_scores, annotated)

    _print_summary(time.time() - t_start)


def _run_ma120_scan() -> List[Dict]:
    """尝试运行MA120扫描，返回信号列表"""
    try:
        import importlib.util
        mod_path = os.path.join(os.path.dirname(__file__), "..", "strategy", "ma120_reversal.py")
        spec = importlib.util.spec_from_file_location("ma120_reversal_mod", mod_path)
        ma120_mod = importlib.util.module_from_spec(spec)
        sys.modules["ma120_reversal_mod"] = ma120_mod
        spec.loader.exec_module(ma120_mod)
        MA120Reversal = ma120_mod.MA120Reversal
        scanner = MA120Reversal()
        results = scanner.scan()
        if results is None:
            return []
        # 转换为dict列表
        if isinstance(results, list):
            out = []
            for r in results:
                if hasattr(r, '_asdict'):
                    out.append(r._asdict())
                elif isinstance(r, dict):
                    out.append(r)
                else:
                    out.append({"code": str(r), "score": 0})
            return out
        return []
    except Exception as e:
        print(f"  MA120 import failed: {e}, returning empty")
        return []


def _export_csv(prefix, ind_scores, con_scores, annotated):
    """导出CSV"""
    import csv
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 板块排名
    fn1 = f"{prefix}_ranking_{ts}.csv"
    with open(fn1, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["类型", "排名", "板块", "评分", "等级", "涨跌幅",
                     "净流入(亿)", "上涨比", "3日动量", "轮动信号", "领涨股"])
        for i, s in enumerate(ind_scores + con_scores, 1):
            w.writerow([s.kind, i, s.name, s.total_score, s.grade,
                        s.change_pct, s.net_inflow, f"{s.up_ratio:.0%}",
                        s.momentum_3d, s.rotation_signal, s.leading_stock])
    print(f"\n  板块排名导出: {fn1}")

    if annotated:
        fn2 = f"{prefix}_ma120_{ts}.csv"
        with open(fn2, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["代码", "名称", "评分", "板块加分", "总分",
                         "行业", "概念", "加分原因"])
            for r in annotated:
                w.writerow([
                    r.get("code"), r.get("name"), r.get("score"),
                    r.get("sector_bonus"), r.get("total_with_sector"),
                    r.get("industry", ""), ",".join(r.get("concepts", [])[:3]),
                    ";".join(r.get("sector_reasons", []))
                ])
        print(f"  MA120导出: {fn2}")


def _print_summary(elapsed):
    print(f"\n{C.bold('─' * 60)}")
    print(f"  总耗时: {elapsed:.1f}s")
    print(f"{C.bold('─' * 60)}")


if __name__ == "__main__":
    main()
