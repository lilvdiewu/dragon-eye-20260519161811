"""
dragon_eye.strategy.bottom_breakout — 底部潜伏选股策略

核心逻辑: 卖盘枯竭 + 波动收缩 + 还没启动
区别于"底部起爆"(追涨)，这是在起爆前找到潜伏点

触发条件:
  1. 价格在60日低点附近（±5%，比原来±10%更紧）
  2. 近10日成交量萎缩至20日均量的50%以下（地量 = 卖盘枯竭）
  3. 近5日振幅收窄（波动收缩，弹簧越压越紧）
  4. 近3日涨幅 < 5%（排除已起爆的，这是"潜伏"不是"追涨"）
  5. 偶有放量阳线痕迹（主力吸筹，近20日有1天以上量比>2的阳线）

加分条件:
  - MA5/MA10/MA20 三线粘合（趋势即将选择方向）
  - 近5日地量日数越多越好
"""
from __future__ import annotations

from dataclasses import dataclass

from ..data_models import Kline
from ..signals import ma, atr, check_volume
from .base_strategy import BaseStrategy, StrategyResult
from .signals_ext import (
    calc_risk_reward,
    find_swing_low,
)


class BottomBreakout(BaseStrategy):
    """底部潜伏选股策略：地量+波动收缩+接近低点+未启动"""

    name = "bottom_breakout"
    description = "底部潜伏：地量+波动收缩+接近低点+未启动"

    def __init__(self,
                 lookback: int = 60,
                 low_range: float = 0.05,
                 volume_shrink: float = 0.50,
                 atr_shrink: float = 0.70,
                 max_recent_gain: float = 5.0,
                 min_volume_spike_days: int = 1):
        self.lookback = lookback              # 回看周期
        self.low_range = low_range            # 低点附近范围（5%）
        self.volume_shrink = volume_shrink    # 地量阈值（50%均量）
        self.atr_shrink = atr_shrink          # ATR收缩阈值（70%）
        self.max_recent_gain = max_recent_gain # 近3日最大涨幅（>此值=已启动）
        self.min_volume_spike_days = min_volume_spike_days  # 最少放量阳线天数

    def scan(self, klines: list[Kline], **kwargs) -> StrategyResult:
        code = kwargs.get("code", "")
        name = kwargs.get("name", "")

        result = StrategyResult(
            code=code,
            name=name,
            signal_type=self.name,
        )

        # ---- 基本数据检查 ----
        if len(klines) < self.lookback:
            return result

        closes = [k.close for k in klines]
        volumes = [k.volume for k in klines]
        cur_close = closes[-1]

        # ---- 条件1: 价格在60日低点±5% ----
        window = klines[-self.lookback:]
        low_60 = min(k.low for k in window)
        distance_from_low = (cur_close - low_60) / low_60

        if distance_from_low > self.low_range:
            return result

        # ---- 条件2: 地量 — 近10日成交量萎缩 ----
        if len(klines) < 31:
            return result

        # 近10日均量 vs 近20日均量
        vol_20d = sum(volumes[-21:-1]) / 20
        if vol_20d <= 0:
            return result

        vol_10d = sum(volumes[-11:-1]) / 10
        vol_ratio_10d = vol_10d / vol_20d  # 近10日均量 / 20日均量，<1说明缩量

        # 近5日地量天数：当日量 < 20日均量 * 50%
        ground_vol_days = 0
        for i in range(1, 6):
            if len(klines) > i:
                day_vol = volumes[-i]
                if day_vol < vol_20d * self.volume_shrink:
                    ground_vol_days += 1

        # 至少2天地量 OR 近10日均量萎缩到20日均量的70%以下
        shrink_ok = ground_vol_days >= 2 or vol_ratio_10d < 0.70
        if not shrink_ok:
            return result

        # ---- 条件3: 波动收缩（ATR收窄）----
        atr_vals = atr(klines, 14)
        if not atr_vals or atr_vals[-1] is None:
            return result

        cur_atr = atr_vals[-1]
        # 10日前的ATR
        if len(atr_vals) < 11 or atr_vals[-11] is None:
            return result
        atr_10d_ago = atr_vals[-11]

        # ATR收缩率 < 70% 说明波动在收窄
        atr_contraction = cur_atr / atr_10d_ago if atr_10d_ago > 0 else 1.0
        if atr_contraction > self.atr_shrink:
            # ATR没收缩，可能还在大幅波动
            # 但如果ATR本身很小（低价股），给个宽容度
            if cur_atr / cur_close > 0.03:  # 日均波动>3%还是太大
                return result

        # ---- 条件4: 近3日涨幅 < 5%（排除已启动）----
        # 同时排除近3日暴跌 > 8% 的（急跌不是潜伏）
        if len(klines) >= 4:
            gain_3d = (closes[-1] - closes[-4]) / closes[-4] * 100
            if gain_3d > self.max_recent_gain:
                return result
            # 近1日涨幅也不能太大（排除涨停板）
            gain_1d = (closes[-1] - closes[-2]) / closes[-2] * 100
            if gain_1d > 7:
                return result
            # 近3日暴跌 > 8% 说明还在急跌，不是潜伏
            if gain_3d < -8:
                return result

        # ---- 条件5: 主力吸筹痕迹 — 近20日有放量阳线 ----
        spike_days = 0
        for i in range(1, min(21, len(klines))):
            idx = len(klines) - i
            day_vol = volumes[idx]
            day_close = closes[idx]
            day_open = klines[idx].open
            # 放量阳线：量 > 2倍20日均量，且收阳
            if day_vol > vol_20d * 2.0 and day_close > day_open:
                spike_days += 1

        if spike_days < self.min_volume_spike_days:
            return result

        # ============================================================
        # 所有条件满足，计算信号
        # ============================================================

        # 止损价: 60日低点-2%
        stop_loss = round(low_60 * 0.98, 2)

        # 目标价: 基于1.5倍ATR（潜伏空间大）
        ma20_vals = ma(closes, 20)
        ma20_val = ma20_vals[-1] if ma20_vals and ma20_vals[-1] is not None else 0

        if cur_atr > 0:
            target_atr = cur_close + cur_atr * 2.0  # 潜伏目标给大点
        else:
            target_atr = cur_close * 1.15

        target_price = max(target_atr, ma20_val) if ma20_val > 0 else target_atr
        target_price = round(target_price, 2)

        risk_reward = calc_risk_reward(cur_close, stop_loss, target_price)

        # ---- 信号强度评分 ----
        score = {}
        total_strength = 0.0

        # 1. 低点位置评分 (权重20)
        # 离低点越近越好，但太近（<1%）可能是正在破位
        if distance_from_low < 0.01:
            low_score = 60  # 正在创新低，不太好
        elif distance_from_low < 0.02:
            low_score = 95  # 几乎在低点
        elif distance_from_low < 0.03:
            low_score = 85
        else:
            low_score = max(40, 100 - distance_from_low * 1000)
        score["low_position"] = round(low_score, 1)
        total_strength += low_score * 0.20

        # 2. 地量评分 (权重30) — 越枯竭越好
        if ground_vol_days >= 4:
            vol_score = 95
        elif ground_vol_days >= 3:
            vol_score = 85
        elif ground_vol_days >= 2:
            vol_score = 70
        elif vol_ratio_10d < 0.60:
            vol_score = 75
        elif vol_ratio_10d < 0.70:
            vol_score = 60
        else:
            vol_score = 40
        score["ground_volume"] = round(vol_score, 1)
        total_strength += vol_score * 0.30

        # 3. 波动收缩评分 (权重25)
        if atr_contraction < 0.50:
            atr_score = 95  # 极度收缩
        elif atr_contraction < 0.60:
            atr_score = 80
        elif atr_contraction < 0.70:
            atr_score = 65
        else:
            atr_score = 40
        score["atr_contraction"] = round(atr_score, 1)
        total_strength += atr_score * 0.25

        # 4. 吸筹痕迹评分 (权重25)
        if spike_days >= 3:
            acc_score = 90
        elif spike_days >= 2:
            acc_score = 75
        else:
            acc_score = 50
        score["accumulation"] = round(acc_score, 1)
        total_strength += acc_score * 0.25

        # 均线粘合加分
        ma5_vals = ma(closes, 5)
        ma10_vals = ma(closes, 10)
        if ma5_vals[-1] and ma10_vals[-1] and ma20_val:
            # 三线间距 < 2% 视为粘合
            ma_spread = (max(ma5_vals[-1], ma10_vals[-1], ma20_val) -
                        min(ma5_vals[-1], ma10_vals[-1], ma20_val)) / ma20_val
            if ma_spread < 0.02:
                total_strength += 10  # 加分
                score["ma_converge"] = True
            else:
                score["ma_converge"] = False

        strength = round(min(100, total_strength), 1)

        result.triggered = True
        result.strength = strength
        result.entry_price = round(cur_close, 2)
        result.stop_loss = stop_loss
        result.target_price = target_price
        result.risk_reward = risk_reward
        result.score = score
        result.details = {
            "low_60": round(low_60, 2),
            "distance_from_low_pct": round(distance_from_low * 100, 2),
            "vol_ratio_10d": round(vol_ratio_10d, 2),
            "ground_vol_days": ground_vol_days,
            "atr_contraction": round(atr_contraction, 2),
            "spike_days": spike_days,
            "atr14": round(cur_atr, 2),
            "gain_3d": round((closes[-1] - closes[-4]) / closes[-4] * 100, 2) if len(closes) >= 4 else 0,
            "strategy_version": "v2_潜伏",
        }

        return result
