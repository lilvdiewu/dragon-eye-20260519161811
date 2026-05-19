"""
Longyan Pro — Multi-factor Stock Recommendation Engine

Factor system:
  1. Strength (change_pct) — today's performance
  2. Activity (turnover + volume_ratio) — market interest
  3. Fund Flow (flow_net / flow_pct) — institutional attitude
  4. Sector Momentum — sector rotation boost
  5. Relative Strength — stock vs sector
  6. Trend (chg_20d / chg_60d) — medium-term trend
  7. Valuation (PE) — filter extremes
  8. Market Cap (MV) — sweet spot 20-500B

Output: ranked recommendations + sector TOP + entry conditions
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Optional

from dragon_eye.analysis.tdx_stat_reader import TdxStatReader, TdxStockStat, TdxStockStat2
from dragon_eye.sector.ths_sector import TdxSectorMapper
from dragon_eye.sector.tdx_sector_reader import TdxSectorReader


# ============================================================
# Factor Weights (sum = 1.0)
# ============================================================

FACTOR_WEIGHTS = {
    "strength": 0.18,
    "activity": 0.12,
    "fund_flow": 0.12,
    "sector_momentum": 0.12,
    "relative_strength": 0.08,
    "trend": 0.08,
    "limit_up_gene": 0.10,
    "valuation": 0.08,
    "market_cap": 0.07,
    "leader_bonus": 0.05,
}


# ============================================================
# Recommendation Result Dataclass
# ============================================================

@dataclass
class StockRecommendation:
    code: str
    name: str
    composite: float          # 0-100
    grade: str                # S/A/B/C

    score_strength: float = 0
    score_activity: float = 0
    score_fund_flow: float = 0
    score_sector_momentum: float = 0
    score_relative: float = 0
    score_trend: float = 0
    score_valuation: float = 0
    score_market_cap: float = 0

    change_pct: float = 0
    turnover: float = 0
    volume_ratio: float = 0
    net_flow_yi: float = 0
    flow_pct: float = 0
    pe: float = 0
    mv_yi: float = 0
    chg_20d: float = 0
    chg_60d: float = 0
    sector: str = ""
    sector_momentum_3d: float = 0
    sector_momentum_5d: float = 0

    is_limit_up: bool = False
    is_sector_leader: bool = False
    limit_up_5d: int = 0
    limit_up_20d: int = 0
    position_pct: float = 0
    action: str = ""
    entry_range: str = ""
    stop_loss: str = ""
    reasons: list[str] = field(default_factory=list)


# ============================================================
# Scoring Functions
# ============================================================

def _score_strength(chg: float) -> float:
    """Today's strength 0-100"""
    if chg >= 9.8:
        return 100
    elif chg >= 5:
        return 80 + (chg - 5) / 4.8 * 15
    elif chg >= 1:
        return 50 + (chg - 1) / 4 * 30
    elif chg >= -1:
        return 30 + (chg + 1) / 2 * 20
    elif chg >= -5:
        return 10 + (chg + 5) / 4 * 20
    else:
        return max(0, 10 + chg)


def _score_activity(turnover: float, volume_ratio: float) -> float:
    """Activity score from turnover + volume ratio 0-100"""
    turn_score = min(turnover / 15 * 70, 70)
    vol_score = min((volume_ratio - 0.5) / 2.5 * 30, 30)
    return round(max(0, turn_score + max(0, vol_score)), 1)


def _score_fund_flow(flow_pct: float) -> float:
    """Fund flow score 0-100"""
    if flow_pct > 5:
        return min(100, 85 + flow_pct)
    elif flow_pct > 1:
        return 55 + (flow_pct - 1) / 4 * 30
    elif flow_pct > 0:
        return 50 + flow_pct * 5
    elif flow_pct > -1:
        return 30 + (flow_pct + 1) * 20
    else:
        return max(0, 30 + flow_pct * 3)


def _score_sector_momentum(mom_3d: float, mom_5d: float) -> float:
    """Sector momentum score 0-100"""
    if mom_3d == 0 and mom_5d == 0:
        return 40
    combo = mom_3d * 0.6 + mom_5d * 0.4
    if combo > 5:
        return min(100, 75 + combo * 3)
    elif combo > 2:
        return 60 + (combo - 2) / 3 * 15
    elif combo > 0:
        return 50 + combo * 5
    elif combo > -2:
        return 40 + (combo + 2) * 5
    else:
        return max(10, 40 + combo * 2)


def _score_relative(stock_chg: float, sector_chg: float) -> float:
    """Relative strength vs sector 0-100"""
    if sector_chg == 0:
        return 50
    diff = stock_chg - sector_chg
    if diff > 5:
        return min(100, 80 + diff * 2)
    elif diff > 2:
        return 60 + (diff - 2) / 3 * 20
    elif diff > 0:
        return 50 + diff * 5
    elif diff > -2:
        return 40 + (diff + 2) * 5
    else:
        return max(10, 40 + diff * 2)


def _score_trend(chg_20d: float, chg_60d: float) -> float:
    """Medium-term trend score 0-100"""
    trend = (chg_20d or 0) * 0.6 + (chg_60d or 0) * 0.4
    if trend > 20:
        return min(100, 75 + trend * 0.5)
    elif trend > 5:
        return 55 + (trend - 5) / 15 * 20
    elif trend > 0:
        return 50 + trend
    elif trend > -10:
        return 35 + (trend + 10) * 1.5
    else:
        return max(5, 30 + trend * 0.3)


def _score_valuation(pe: float) -> float:
    """PE score 0-100, 10-30 is sweet spot"""
    if 10 <= pe <= 30:
        return 65 + (30 - pe) / 20 * 15
    elif 0 < pe < 10:
        return 50 + pe
    elif 30 < pe <= 60:
        return 50 + (60 - pe) / 30 * 10
    elif pe > 60:
        return max(10, 60 - (pe - 60) * 0.3)
    elif pe <= 0:
        return 15
    return 30


def _score_market_cap(total_mv: float) -> float:
    """Market cap score 0-100, 20-500B optimal"""
    if total_mv <= 0:
        return 30
    mv_yi = total_mv / 10000
    if 20 <= mv_yi <= 500:
        return 70 + min(30, (mv_yi - 20) / 480 * 30)
    elif mv_yi < 20:
        return max(10, mv_yi / 20 * 70)
    elif mv_yi <= 2000:
        return 40 + (2000 - mv_yi) / 1500 * 30
    else:
        return max(10, 40 - (mv_yi - 2000) / 5000 * 30)


def _score_limit_up_gene(lu_5d: int, lu_20d: int) -> float:
    """Limit-up gene score 0-100"""
    if lu_5d == 0 and lu_20d == 0:
        return 30
    score_5d = min(lu_5d * 25, 60)
    score_20d = min(lu_20d * 8, 40)
    total = score_5d + score_20d
    if lu_5d >= 4:
        total = max(40, total - 15)
    return min(100, total)


def _score_leader_bonus(is_leader: bool, sector_rank: int) -> float:
    """Sector leader bonus 0-100"""
    if not is_leader:
        return 0
    if sector_rank == 1:
        return 100
    elif sector_rank == 2:
        return 85
    elif sector_rank == 3:
        return 70
    return 0


def _generate_action(chg: float, turnover: float, vol_ratio: float, composite: float, sector_mom: float) -> tuple[str, str, str]:
    """Generate buy action, entry range, stop loss"""
    if chg >= 9.8:
        return ("竞价博弈", "竞价高开2-5%介入，低开>3%不参与", "开盘价-3%或分时均线破位")
    elif chg >= 5:
        if turnover > 10:
            return ("分歧低吸", "回调到日内均价附近或开0-2%", "今日最低价-2%")
        else:
            return ("强势突破", "开盘+0-2%介入，高开>5%追2仓", "昨日收盘价-3%")
    elif chg >= 2:
        if sector_mom > 3:
            return ("板块共振", "开0-1%或盘中回踩均线", "昨日收盘价-3%")
        else:
            return ("温和关注", "不急入场，等放量确认", "5日线止损")
    elif chg >= 0:
        return ("潜伏观察", "等板块异动或放量信号", "20日线止损")
    else:
        if sector_mom > 2 and chg > -5:
            return ("超跌博弈", "放量止跌后首阳介入", "今日最低价-2%")
        return ("暂不参与", "", "")


def _grade(composite: float) -> str:
    if composite >= 75:
        return "S"
    elif composite >= 60:
        return "A"
    elif composite >= 45:
        return "B"
    else:
        return "C"


# ============================================================
# Main Recommender
# ============================================================

class StockRecommender:
    """Multi-factor stock recommendation engine"""

    def __init__(self):
        self._stats: Optional[TdxStatReader] = None
        self._mapper: Optional[TdxSectorMapper] = None
        self._tdx_sectors: Optional[TdxSectorReader] = None
        self._sector_momentum: dict[str, dict] = {}
        self._names: dict[str, str] = {}
        self._loaded = False
        self._tdx_data_dir = self._find_tdx_data_dir()
        self._limit_up_cache: dict[str, tuple[int, int]] = {}

    def _find_tdx_data_dir(self) -> str:
        candidates = [r"D:\new_tdx_test", r"D:\new_tdx", r"C:\new_tdx", r"D:\tdx"]
        for c in candidates:
            if os.path.isdir(os.path.join(c, "vipdoc")):
                return c
        return ""

    def load_data(self) -> None:
        if self._loaded:
            return

        self._stats = TdxStatReader()
        self._stats.load()

        self._mapper = TdxSectorMapper()
        self._mapper.load_infoharbor()

        from dragon_eye.analysis.tdx_industry import TdxIndustryReader
        self._ind_reader = TdxIndustryReader()
        self._ind_reader._ensure_loaded()

        self._tdx_sectors = TdxSectorReader()
        self._tdx_sectors.load_sector_map()
        all_mom = self._tdx_sectors.get_all_sectors()
        if not all_mom.empty:
            for _, row in all_mom.iterrows():
                self._sector_momentum[row['name']] = {
                    'momentum_3d': row.get('momentum_3d', 0),
                    'momentum_5d': row.get('momentum_5d', 0),
                    'change_pct': row.get('change_pct', 0),
                }

        self._names = self._load_names()
        self._loaded = True

    def _load_names(self) -> dict[str, str]:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "_cache", "stock_names.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _day_file_path(self, code: str) -> str:
        if not self._tdx_data_dir:
            return ""
        code = code.strip()
        market = "sh" if (code.startswith("6") or code.startswith("9")) else "sz"
        return os.path.join(self._tdx_data_dir, "vipdoc", market, "lday", f"{market}{code}.day")

    def _read_day_changes(self, code: str, max_bars: int = 30) -> list[float]:
        """Read recent daily change% from TDX .day file"""
        path = self._day_file_path(code)
        if not path or not os.path.exists(path):
            return []
        try:
            with open(path, "rb") as f:
                data = f.read()
            import struct
            rec_size = 32
            total = len(data) // rec_size
            if total < 2:
                return []
            start = max(0, total - max_bars - 1)
            changes = []
            prev = None
            for i in range(start, total):
                off = i * rec_size
                if off + 28 > len(data):
                    break
                close = struct.unpack_from('<f', data, off + 16)[0]
                if prev and prev > 0:
                    changes.append((close - prev) / prev * 100)
                prev = close
            return changes
        except Exception:
            return []

    def _count_limit_ups(self, code: str) -> tuple[int, int]:
        if code in self._limit_up_cache:
            return self._limit_up_cache[code]
        changes = self._read_day_changes(code, 25)
        if not changes:
            self._limit_up_cache[code] = (0, 0)
            return (0, 0)
        lu_5d = sum(1 for c in changes[-5:] if c >= 9.8)
        lu_20d = sum(1 for c in changes[-20:] if c >= 9.8)
        self._limit_up_cache[code] = (lu_5d, lu_20d)
        return (lu_5d, lu_20d)

    def recommend(self, top_n: int = 20, min_score: float = 40, max_per_sector: int = 3) -> list[StockRecommendation]:
        """Two-pass multi-factor scoring with correlation filter and position sizing."""
        if not self._loaded:
            self.load_data()

        # === PASS 1: Fast scoring (all stocks, no .day read) ===
        candidates: list[dict] = []
        
        for code, stat in self._stats._stats.items():
            if stat.turnover <= 0 and stat.change_pct == 0:
                continue
            
            stat2 = self._stats.get_stat2(code)
            flow_pct_val = stat2.flow_pct if stat2 else 0
            industry = self._ind_reader.get_industry(code) or ""
            mom_data = self._sector_momentum.get(industry, {})
            s_mom_3d = mom_data.get('momentum_3d', 0)
            s_mom_5d = mom_data.get('momentum_5d', 0)
            s_chg = mom_data.get('change_pct', 0)

            s0 = _score_strength(stat.change_pct)
            s1 = _score_activity(stat.turnover, stat.volume_ratio)
            s2 = _score_fund_flow(flow_pct_val)
            s3 = _score_sector_momentum(s_mom_3d, s_mom_5d)
            s4 = _score_relative(stat.change_pct, s_chg)
            s5 = _score_trend(stat.chg_20d, stat.chg_60d)
            s6 = _score_valuation(stat.pe)
            s7 = _score_market_cap(stat.total_mv)

            fast = (s0 * 0.28 + s1 * FACTOR_WEIGHTS["activity"] +
                    s2 * FACTOR_WEIGHTS["fund_flow"] + s3 * FACTOR_WEIGHTS["sector_momentum"] +
                    s4 * FACTOR_WEIGHTS["relative_strength"] + s5 * FACTOR_WEIGHTS["trend"] +
                    s6 * FACTOR_WEIGHTS["valuation"] + s7 * FACTOR_WEIGHTS["market_cap"])
            
            if fast < 25:
                continue

            candidates.append({"code": code, "stat": stat, "stat2": stat2, "industry": industry,
                              "s0": s0, "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5,
                              "s6": s6, "s7": s7, "fast": fast, "s_mom_3d": s_mom_3d,
                              "s_mom_5d": s_mom_5d, "s_chg": s_chg, "flow_pct": flow_pct_val})

        candidates.sort(key=lambda x: -x["fast"])
        top200 = candidates[:200]

        # Leader detection
        sector_rankings: dict[str, list[str]] = {}
        for c in sorted(top200, key=lambda x: -x["fast"]):
            ind = c["industry"]
            if not ind:
                continue
            if ind not in sector_rankings:
                sector_rankings[ind] = []
            sector_rankings[ind].append(c["code"])
        leader_map: dict[str, int] = {}
        for ind, codes in sector_rankings.items():
            for rank, code in enumerate(codes[:10], 1):
                leader_map[code] = rank

        # === PASS 2: Deep scoring (top 200, read .day history) ===
        results: list[StockRecommendation] = []
        name_map = self._names

        for c in top200:
            code = c["code"]
            stat = c["stat"]
            stat2 = c["stat2"]
            industry = c["industry"]
            name = name_map.get(code, code)

            lu_5d, lu_20d = self._count_limit_ups(code)
            s_lu = _score_limit_up_gene(lu_5d, lu_20d)
            sr = leader_map.get(code, 999)
            is_leader = sr <= 3
            s_ld = _score_leader_bonus(is_leader, sr)

            composite = (c["s0"] * FACTOR_WEIGHTS["strength"] + c["s1"] * FACTOR_WEIGHTS["activity"] +
                         c["s2"] * FACTOR_WEIGHTS["fund_flow"] + c["s3"] * FACTOR_WEIGHTS["sector_momentum"] +
                         c["s4"] * FACTOR_WEIGHTS["relative_strength"] + c["s5"] * FACTOR_WEIGHTS["trend"] +
                         s_lu * FACTOR_WEIGHTS["limit_up_gene"] + c["s6"] * FACTOR_WEIGHTS["valuation"] +
                         c["s7"] * FACTOR_WEIGHTS["market_cap"] + s_ld * FACTOR_WEIGHTS["leader_bonus"])

            if composite < min_score:
                continue

            grade = _grade(composite)
            sm_combo = c["s_mom_3d"] * 0.6 + c["s_mom_5d"] * 0.4
            action, entry_range, stop_loss = _generate_action(
                stat.change_pct, stat.turnover, stat.volume_ratio, composite, sm_combo)

            # Position sizing
            pos = 15 if grade == "S" else (10 if grade == "A" else (5 if grade == "B" else 3))
            if stat.change_pct >= 9.8:
                pos *= 0.7

            # Reasons
            reasons = []
            if c["s0"] >= 80: reasons.append(f"涨幅强劲(+{stat.change_pct:.1f}%)")
            if c["s1"] >= 70: reasons.append(f"交投活跃(换手{stat.turnover:.1f}% 量比{stat.volume_ratio:.1f})")
            if c["s2"] >= 70: reasons.append(f"主力净流入占比{c['flow_pct']:.1f}%")
            if c["s3"] >= 70: reasons.append(f"板块强势(3日{c['s_mom_3d']:+.1f}%)")
            if s_lu >= 60: reasons.append(f"涨停基因(5日{lu_5d}板/20日{lu_20d}板)")
            if is_leader: reasons.append(f"行业龙头(#{sr})")

            mv_yi = stat.total_mv / 10000 if stat.total_mv > 0 else 0
            results.append(StockRecommendation(
                code=code, name=name, composite=round(composite, 1), grade=grade,
                score_strength=round(c["s0"], 1), score_activity=round(c["s1"], 1),
                score_fund_flow=round(c["s2"], 1), score_sector_momentum=round(c["s3"], 1),
                score_relative=round(c["s4"], 1), score_trend=round(c["s5"], 1),
                score_valuation=round(c["s6"], 1), score_market_cap=round(c["s7"], 1),
                change_pct=stat.change_pct, turnover=stat.turnover, volume_ratio=stat.volume_ratio,
                net_flow_yi=round((stat2.flow_net / 10000) if stat2 else 0, 2),
                flow_pct=round(c["flow_pct"], 2), pe=stat.pe, mv_yi=round(mv_yi, 1),
                chg_20d=stat.chg_20d, chg_60d=stat.chg_60d, sector=industry,
                sector_momentum_3d=round(c["s_mom_3d"], 2), sector_momentum_5d=round(c["s_mom_5d"], 2),
                is_limit_up=stat.change_pct >= 9.8, is_sector_leader=is_leader,
                limit_up_5d=lu_5d, limit_up_20d=lu_20d, position_pct=round(pos, 1),
                action=action, entry_range=entry_range, stop_loss=stop_loss, reasons=reasons))

        results.sort(key=lambda x: (-x.composite, -x.change_pct))

        # === Correlation filter (max per sector) ===
        filtered: list[StockRecommendation] = []
        sector_counts: dict[str, int] = {}
        for r in results:
            sec = r.sector
            if sector_counts.get(sec, 0) >= max_per_sector and sec:
                continue
            filtered.append(r)
            if sec:
                sector_counts[sec] = sector_counts.get(sec, 0) + 1

        return filtered[:top_n]

    def recommend_by_sector(self, sector_name: str, top_n: int = 5) -> list[StockRecommendation]:
        all_recs = self.recommend(top_n=9999, min_score=0)
        sector_recs = [r for r in all_recs if r.sector == sector_name]
        sector_recs.sort(key=lambda x: (-x.composite, -x.change_pct))
        return sector_recs[:top_n]

    def top_sectors(self, top_n: int = 5) -> list[dict]:
        """Top sectors by average constituent score"""
        all_recs = self.recommend(top_n=9999, min_score=30)
        sector_scores: dict[str, list[float]] = {}
        for r in all_recs:
            if r.sector:
                if r.sector not in sector_scores:
                    sector_scores[r.sector] = []
                sector_scores[r.sector].append(r.composite)

        avg_scores = []
        for sector, scores in sector_scores.items():
            if len(scores) >= 3:
                avg = sum(scores) / len(scores)
                mom = self._sector_momentum.get(sector, {})
                avg_scores.append({
                    "name": sector,
                    "avg_score": round(avg, 1),
                    "top_score": round(max(scores), 1),
                    "stock_count": len(scores),
                    "momentum_3d": round(mom.get('momentum_3d', 0), 2),
                    "momentum_5d": round(mom.get('momentum_5d', 0), 2),
                })

        avg_scores.sort(key=lambda x: (-x["avg_score"], -x["stock_count"]))
        return avg_scores[:top_n]


# ============================================================
# Convenience
# ============================================================

_global_recommender: Optional[StockRecommender] = None


def get_recommender() -> StockRecommender:
    global _global_recommender
    if _global_recommender is None:
        _global_recommender = StockRecommender()
    return _global_recommender
