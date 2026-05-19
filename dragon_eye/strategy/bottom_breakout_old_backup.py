"""
dragon_eye.strategy.bottom_breakout — 底部起爆选股策略

策略逻辑:
  1. 股价在近60日低点±10%区间
  2. 近5日量比>1.5（放量信号）
  3. MA5上穿MA10 或 MA10拐头向上
  4. 近3日涨幅>3%（起爆确认）
"""
from __future__ import annotations

from dataclasses import dataclass

from ..data_models import Kline
from ..signals import ma, atr, check_ma_cross, check_volume, score_technical
from .base_strategy import BaseStrategy, StrategyResult
from .signals_ext import (
    is_near_low,
    recent_gain,
    calc_risk_reward,
    find_swing_low,
)


class BottomBreakout(BaseStrategy):
    """底部起爆选股策略：60日低点+放量+MA金叉+3日确认"""

    name = "bottom_breakout"
    description = "底部起爆选股策略：60日低点+放量+MA金叉+3日确认"

    def __init__(self,
                 lookback: int = 60,
                 low_range: float = 0.10,
                 volume_ratio: float = 1.5,
                 gain_days: int = 3,
                 min_gain: float = 3.0):
        self.lookback = lookback
        self.low_range = low_range
        self.volume_ratio = volume_ratio
        self.gain_days = gain_days
        self.min_gain = min_gain

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
        cur_close = closes[-1]

        # ---- 条件1: 近60日低点±10% ----
        if not is_near_low(klines, self.lookback, self.low_range):
            return result

        # 找出60日最低价
        window = klines[-self.lookback:]
        low_60 = min(k.low for k in window)

        # ---- 条件2: 近5日量比>1.5 ----
        vol_sig = check_volume(klines, period=20, ratio_threshold=self.volume_ratio)
        vol_ok = vol_sig.is_expand or vol_sig.volume_ratio >= self.volume_ratio
        # 近5日平均量比
        vol_ratios_5d = []
        if len(klines) >= 25:
            for offset in range(5):
                sub = klines[:len(klines) - offset] if offset > 0 else klines
                if len(sub) >= 21:
                    vols = [k.volume for k in sub[-21:]]
                    avg_vol = sum(vols[:-1]) / 20
                    if avg_vol > 0:
                        vol_ratios_5d.append(vols[-1] / avg_vol)
        avg_vol_ratio_5d = sum(vol_ratios_5d) / len(vol_ratios_5d) if vol_ratios_5d else 0
        vol_ok_5d = avg_vol_ratio_5d >= self.volume_ratio

        if not (vol_ok or vol_ok_5d):
            return result

        # ---- 条件3: MA5上穿MA10 或 MA10拐头向上 ----
        ma_cross_sig = check_ma_cross(klines, short=5, long=10)
        ma_cross_ok = ma_cross_sig.cross_type == "golden"

        # MA10拐头：当前MA10 > 前一日MA10 且 之前有下降段
        ma10_vals = ma(closes, 10)
        ma10_turning = False
        if len(klines) >= 15:
            cur_ma10 = ma10_vals[-1]
            prev_ma10 = ma10_vals[-2]
            prev2_ma10 = ma10_vals[-3] if len(klines) >= 16 else None
            if cur_ma10 and prev_ma10:
                ma10_rising = cur_ma10 > prev_ma10
                ma10_was_declining = prev2_ma10 is not None and prev_ma10 < prev2_ma10
                ma10_turning = ma10_rising

        ma_ok = ma_cross_ok or ma10_turning
        if not ma_ok:
            return result

        # ---- 条件4: 近3日涨幅>3% ----
        gain = recent_gain(klines, self.gain_days)
        if gain < self.min_gain:
            return result

        # ---- 所有条件满足，计算信号 ----
        # 止损价: 近60日低点-2%
        stop_loss = round(low_60 * 0.98, 2)

        # 目标价: 1.5倍ATR 或 MA20
        atr_vals = atr(klines, 14)
        cur_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0
        ma20_vals = ma(closes, 20)
        ma20_val = ma20_vals[-1] if ma20_vals and ma20_vals[-1] is not None else 0

        if cur_atr > 0:
            target_atr = cur_close + cur_atr * 1.5
        else:
            target_atr = cur_close * 1.10

        target_price = max(target_atr, ma20_val) if ma20_val > 0 else target_atr
        target_price = round(target_price, 2)

        risk_reward = calc_risk_reward(cur_close, stop_loss, target_price)

        # ---- 信号强度评分（各条件加权）----
        score = {}
        total_strength = 0.0

        # 1. 低点位置评分 (权重25)
        distance_from_low = (cur_close - low_60) / low_60 * 100
        low_score = max(0, 100 - distance_from_low * 5)  # 越接近低点分越高
        score["low_position"] = round(low_score, 1)
        total_strength += low_score * 0.25

        # 2. 量能评分 (权重25)
        vol_score = min(100, 40 + avg_vol_ratio_5d * 20)
        score["volume"] = round(vol_score, 1)
        total_strength += vol_score * 0.25

        # 3. MA信号评分 (权重25)
        if ma_cross_ok:
            ma_score = 80 + min(20, ma_cross_sig.strength * 0.2)
        elif ma10_turning:
            ma_score = 60
        else:
            ma_score = 0
        score["ma_signal"] = round(ma_score, 1)
        total_strength += ma_score * 0.25

        # 4. 涨幅确认评分 (权重25)
        gain_score = min(100, 50 + gain * 5)
        score["gain_confirm"] = round(gain_score, 1)
        total_strength += gain_score * 0.25

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
            "distance_from_low_pct": round(distance_from_low, 2),
            "vol_ratio_5d": round(avg_vol_ratio_5d, 2),
            "ma_cross": ma_cross_sig.cross_type,
            "ma10_turning": ma10_turning,
            "recent_gain_pct": gain,
            "atr14": round(cur_atr, 2),
            "ma20": round(ma20_val, 2),
        }

        return result
