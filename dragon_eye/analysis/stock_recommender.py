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
    "strength": 0.20,
    "activity": 0.15,
    "fund_flow": 0.15,
    "sector_momentum": 0.15,
    "relative_strength": 0.10,
    "trend": 0.10,
    "valuation": 0.08,
    "market_cap": 0.07,
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

    def load_data(self) -> None:
        if self._loaded:
            return

        self._stats = TdxStatReader()
        self._stats.load()

        self._mapper = TdxSectorMapper()
        self._mapper.load_infoharbor()
        try:
            self._mapper.load_industry()
        except Exception:
            pass

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

    def recommend(self, top_n: int = 20, min_score: float = 40) -> list[StockRecommendation]:
        """Run multi-factor scoring, return ranked recommendations"""
        if not self._loaded:
            self.load_data()

        results: list[StockRecommendation] = []
        all_stats = self._stats._stats

        for code, stat in all_stats.items():
            stat2 = self._stats.get_stat2(code)

            if stat.turnover <= 0 and stat.change_pct == 0:
                continue

            name = self._names.get(code, code)
            industry = self._mapper.get_industry(code) or ""
            sector_mom_data = self._sector_momentum.get(industry, {})
            sector_mom_3d = sector_mom_data.get('momentum_3d', 0)
            sector_mom_5d = sector_mom_data.get('momentum_5d', 0)
            sector_chg = sector_mom_data.get('change_pct', 0)

            flow_pct_val = stat2.flow_pct if stat2 else 0
            flow_net_val = stat2.flow_net if stat2 else 0

            # Calculate factor scores
            s_strength = _score_strength(stat.change_pct)
            s_activity = _score_activity(stat.turnover, stat.volume_ratio)
            s_fund_flow = _score_fund_flow(flow_pct_val)
            s_sector = _score_sector_momentum(sector_mom_3d, sector_mom_5d)
            s_relative = _score_relative(stat.change_pct, sector_chg)
            s_trend = _score_trend(stat.chg_20d, stat.chg_60d)
            s_valuation = _score_valuation(stat.pe)
            s_market_cap = _score_market_cap(stat.total_mv)

            # Weighted composite
            composite = (
                s_strength * FACTOR_WEIGHTS["strength"] +
                s_activity * FACTOR_WEIGHTS["activity"] +
                s_fund_flow * FACTOR_WEIGHTS["fund_flow"] +
                s_sector * FACTOR_WEIGHTS["sector_momentum"] +
                s_relative * FACTOR_WEIGHTS["relative_strength"] +
                s_trend * FACTOR_WEIGHTS["trend"] +
                s_valuation * FACTOR_WEIGHTS["valuation"] +
                s_market_cap * FACTOR_WEIGHTS["market_cap"]
            )

            if composite < min_score:
                continue

            grade = _grade(composite)

            # Generate action
            sector_mom_combo = sector_mom_3d * 0.6 + sector_mom_5d * 0.4
            action, entry_range, stop_loss = _generate_action(
                stat.change_pct, stat.turnover, stat.volume_ratio,
                composite, sector_mom_combo
            )

            # Build reasons
            reasons = []
            if s_strength >= 80:
                reasons.append(f"涨幅强劲(+{stat.change_pct:.1f}%)")
            if s_activity >= 70:
                reasons.append(f"交投活跃(换手{stat.turnover:.1f}% 量比{stat.volume_ratio:.1f})")
            if s_fund_flow >= 70:
                reasons.append(f"主力净流入占比{flow_pct_val:.1f}%")
            if s_sector >= 70:
                reasons.append(f"板块强势(3日{sector_mom_3d:+.1f}%)")
            if s_relative >= 65:
                reasons.append(f"领跑板块(超额{stat.change_pct - sector_chg:+.1f}%)")

            mv_yi = stat.total_mv / 10000 if stat.total_mv > 0 else 0
            results.append(StockRecommendation(
                code=code,
                name=name,
                composite=round(composite, 1),
                grade=grade,
                score_strength=round(s_strength, 1),
                score_activity=round(s_activity, 1),
                score_fund_flow=round(s_fund_flow, 1),
                score_sector_momentum=round(s_sector, 1),
                score_relative=round(s_relative, 1),
                score_trend=round(s_trend, 1),
                score_valuation=round(s_valuation, 1),
                score_market_cap=round(s_market_cap, 1),
                change_pct=stat.change_pct,
                turnover=stat.turnover,
                volume_ratio=stat.volume_ratio,
                net_flow_yi=round(flow_net_val / 10000, 2),
                flow_pct=round(flow_pct_val, 2),
                pe=stat.pe,
                mv_yi=round(mv_yi, 1),
                chg_20d=stat.chg_20d,
                chg_60d=stat.chg_60d,
                sector=industry,
                sector_momentum_3d=round(sector_mom_3d, 2),
                sector_momentum_5d=round(sector_mom_5d, 2),
                is_limit_up=stat.change_pct >= 9.8,
                action=action,
                entry_range=entry_range,
                stop_loss=stop_loss,
                reasons=reasons,
            ))

        results.sort(key=lambda x: (-x.composite, -x.change_pct))
        return results[:top_n]

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
