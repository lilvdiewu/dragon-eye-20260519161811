"""
dragon_eye.strategy.pullback_buy — 强势股回调买入策略

策略逻辑:
  1. 近20日涨幅>15%（强势股）
  2. 回调至MA10或MA20附近（价格与MA偏差<2%）
  3. 缩量回调（量比<0.7）
  4. 出现止跌信号（下影线/十字星/锤子线）
  5. 板块仍处于强势（板块指数>MA20）—— 可选条件
"""
from __future__ import annotations

from dataclasses import dataclass

from ..data_models import Kline
from ..signals import (
    ma, atr, check_volume, check_stop_drop, check_ma_cross,
    score_technical,
)
from .base_strategy import BaseStrategy, StrategyResult
from .signals_ext import (
    find_swing_high,
    find_swing_low,
    calc_risk_reward,
    check_pullback_to_ma,
    recent_gain,
)


class PullbackBuy(BaseStrategy):
    """强势股波段回调低点买入：20日涨幅>15%+回调至MA+缩量+止跌"""

    name = "pullback_buy"
    description = "强势股波段回调低点买入：20日涨幅>15%+回调至MA+缩量+止跌"

    def __init__(self,
                 strong_gain: float = 15.0,
                 ma_deviation: float = 0.02,
                 shrink_ratio: float = 0.7,
                 lookback: int = 20):
        self.strong_gain = strong_gain
        self.ma_deviation = ma_deviation
        self.shrink_ratio = shrink_ratio
        self.lookback = lookback

    def scan(self, klines: list[Kline], **kwargs) -> StrategyResult:
        code = kwargs.get("code", "")
        name = kwargs.get("name", "")

        result = StrategyResult(
            code=code,
            name=name,
            signal_type=self.name,
        )

        # ---- 基本数据检查 ----
        if len(klines) < self.lookback + 10:
            return result

        closes = [k.close for k in klines]
        cur_close = closes[-1]

        # ---- 条件1: 近20日涨幅>15%（强势股）----
        gain_20d = recent_gain(klines, self.lookback)
        if gain_20d < self.strong_gain:
            return result

        # 找近20日最高点（确认是从高点回调）
        swing_high = find_swing_high(klines, self.lookback)
        swing_low_20 = find_swing_low(klines, self.lookback)
        if swing_high is None:
            return result

        # 当前价应低于近20日最高点（确实在回调）
        pullback_pct = (swing_high - cur_close) / swing_high * 100 if swing_high > 0 else 0
        if pullback_pct <= 0:
            # 没有回调，还在创新高
            return result

        # ---- 条件2: 回调至MA10或MA20附近 ----
        ma10_sig = check_pullback_to_ma(klines, ma_period=10, deviation=self.ma_deviation)
        ma20_sig = check_pullback_to_ma(klines, ma_period=20, deviation=self.ma_deviation)

        near_ma10 = ma10_sig.triggered
        near_ma20 = ma20_sig.triggered

        if not (near_ma10 or near_ma20):
            return result

        # 获取MA值
        ma10_vals = ma(closes, 10)
        ma20_vals = ma(closes, 20)
        ma10_val = ma10_vals[-1] if ma10_vals and ma10_vals[-1] is not None else 0
        ma20_val = ma20_vals[-1] if ma20_vals and ma20_vals[-1] is not None else 0

        # ---- 条件3: 缩量回调（量比<0.7）----
        vol_sig = check_volume(klines, period=20, ratio_threshold=1.5,
                               shrink_threshold=self.shrink_ratio)
        # 检查近3日是否缩量
        shrink_ok = vol_sig.is_shrink
        if not shrink_ok and len(klines) >= 23:
            # 近3日平均量比
            recent_shrink_count = 0
            for i in range(1, 4):
                if i >= len(klines):
                    break
                sub = klines[:len(klines) - i]
                if len(sub) >= 21:
                    vols = [k.volume for k in sub[-21:]]
                    avg_vol = sum(vols[:-1]) / 20
                    if avg_vol > 0 and vols[-1] / avg_vol < self.shrink_ratio:
                        recent_shrink_count += 1
            shrink_ok = recent_shrink_count >= 1

        # 缩量是加分项但不是必要条件，强势回调可以不缩量
        # 但至少不能放量（量比<1.5）
        vol_ok = vol_sig.is_shrink or (not vol_sig.is_expand) or shrink_ok

        # ---- 条件4: 止跌信号 ----
        stop_sig = check_stop_drop(klines)
        stop_ok = stop_sig.is_doji or stop_sig.is_hammer or stop_sig.lower_shadow_ratio > 0.4

        if not stop_ok:
            return result

        # ---- 条件5: 板块强势（可选）----
        # 板块数据可能不可用，跳过

        # ---- 所有条件满足，计算信号 ----
        # 止损: MA20-1ATR 或 回调最低点-1%
        atr_vals = atr(klines, 14)
        cur_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0

        # 近5日最低点
        recent_5d_low = min(k.low for k in klines[-5:]) if len(klines) >= 5 else cur_close

        if cur_atr > 0 and ma20_val > 0:
            stop_atr = ma20_val - cur_atr
        else:
            stop_atr = 0

        stop_low = recent_5d_low * 0.99

        # 取两者中较高的作为止损
        stop_loss = max(stop_atr, stop_low) if stop_atr > 0 else stop_low
        stop_loss = round(stop_loss, 2)

        # 目标: 前高 或 入场价+2ATR
        target_high = swing_high
        target_atr = cur_close + cur_atr * 2 if cur_atr > 0 else cur_close * 1.10
        target_price = min(target_high, target_atr)  # 取较低的保守目标
        target_price = round(target_price, 2)

        # 如果前高太远，用2ATR
        if target_high > cur_close * 1.20:
            target_price = round(target_atr, 2)

        risk_reward = calc_risk_reward(cur_close, stop_loss, target_price)

        # ---- 信号强度评分 ----
        score = {}
        total_strength = 0.0

        # 1. 强势评分 (权重25)
        strong_score = min(100, 50 + (gain_20d - self.strong_gain) * 2)
        score["strong_trend"] = round(strong_score, 1)
        total_strength += strong_score * 0.25

        # 2. 回调位置评分 (权重25)
        if near_ma10:
            pullback_score = 80
        elif near_ma20:
            pullback_score = 60
        else:
            pullback_score = 0
        score["pullback_position"] = round(pullback_score, 1)
        total_strength += pullback_score * 0.25

        # 3. 缩量评分 (权重20)
        if vol_sig.is_shrink or shrink_ok:
            vol_score = 80
        elif not vol_sig.is_expand:
            vol_score = 50
        else:
            vol_score = 20
        score["volume"] = round(vol_score, 1)
        total_strength += vol_score * 0.20

        # 4. 止跌信号评分 (权重30)
        if stop_sig.is_hammer:
            stop_score = 90
        elif stop_sig.is_doji:
            stop_score = 70
        elif stop_sig.lower_shadow_ratio > 0.4:
            stop_score = 60
        else:
            stop_score = 30
        score["stop_drop"] = round(stop_score, 1)
        total_strength += stop_score * 0.30

        strength = round(min(100, total_strength), 1)

        result.triggered = True
        result.strength = strength
        result.entry_price = round(cur_close, 2)
        result.stop_loss = stop_loss
        result.target_price = target_price
        result.risk_reward = risk_reward
        result.score = score
        result.details = {
            "gain_20d_pct": round(gain_20d, 2),
            "swing_high": round(swing_high, 2),
            "pullback_pct": round(pullback_pct, 2),
            "near_ma10": near_ma10,
            "near_ma20": near_ma20,
            "ma10": round(ma10_val, 2),
            "ma20": round(ma20_val, 2),
            "is_shrink": vol_sig.is_shrink or shrink_ok,
            "volume_ratio": vol_sig.volume_ratio,
            "stop_signal": "hammer" if stop_sig.is_hammer else
                           "doji" if stop_sig.is_doji else "lower_shadow",
            "lower_shadow_ratio": stop_sig.lower_shadow_ratio,
            "atr14": round(cur_atr, 2),
            "recent_5d_low": round(recent_5d_low, 2),
        }

        return result
