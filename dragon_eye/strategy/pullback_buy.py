"""
dragon_eye.strategy.pullback_buy — 缩量蓄势选股策略

核心逻辑: 回调到位 + 量能逐级萎缩 + 均线走平 + 还没反弹
区别于"强势回调"（追强势股回调），这是找蓄势等待第二波的潜伏点

触发条件:
  1. 距60日高点回调15%以上（跌够了，不是微调）
  2. 近10日成交量阶梯式萎缩（量能收缩）
  3. 近5日振幅 < 4%（横盘蓄势，不是继续下跌）
  4. MA20走平或拐头向上（下跌趋势结束）
  5. 近3日涨幅 < 5%（还没反弹，这才是蓄势点）

加分条件:
  - 在MA60附近获得支撑（长期趋势线）
  - 近5日地量天数多
  - ATR收缩（波动收敛）
"""
from __future__ import annotations

from dataclasses import dataclass

from ..data_models import Kline
from ..signals import ma, atr, check_volume
from .base_strategy import BaseStrategy, StrategyResult
from .signals_ext import (
    calc_risk_reward,
    find_swing_high,
    find_swing_low,
)


class PullbackBuy(BaseStrategy):
    """缩量蓄势选股策略：回调到位+量能萎缩+均线走平+未反弹"""

    name = "pullback_buy"
    description = "缩量蓄势：回调到位+量能萎缩+均线走平+未反弹"

    def __init__(self,
                 min_pullback: float = 15.0,
                 volume_shrink: float = 0.70,
                 max_range_5d: float = 4.0,
                 max_recent_gain: float = 5.0,
                 lookback: int = 60):
        self.min_pullback = min_pullback          # 最小回调幅度（%）
        self.volume_shrink = volume_shrink        # 量能萎缩阈值
        self.max_range_5d = max_range_5d          # 近5日最大振幅（%）
        self.max_recent_gain = max_recent_gain    # 近3日最大涨幅（排除已反弹）
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
        if len(klines) < self.lookback:
            return result

        closes = [k.close for k in klines]
        volumes = [k.volume for k in klines]
        cur_close = closes[-1]

        # ---- 条件1: 距60日高点回调15%以上 ----
        window = klines[-self.lookback:]
        high_60 = max(k.high for k in window)
        low_60 = min(k.low for k in window)

        pullback_pct = (high_60 - cur_close) / high_60 * 100 if high_60 > 0 else 0
        if pullback_pct < self.min_pullback:
            return result

        # 当前价不能在最低点附近太近（正在急跌的不算蓄势）
        distance_from_low = (cur_close - low_60) / low_60 * 100
        if distance_from_low < 1.0:
            # 正在创新低，不是蓄势
            return result

        # ---- 条件2: 近10日量能阶梯式萎缩 ----
        if len(klines) < 31:
            return result

        vol_20d = sum(volumes[-21:-1]) / 20
        if vol_20d <= 0:
            return result

        vol_10d = sum(volumes[-11:-1]) / 10
        vol_ratio_10d = vol_10d / vol_20d

        # 前5日均量 vs 后5日均量（应该递减）
        vol_first5 = sum(volumes[-11:-6]) / 5
        vol_last5 = sum(volumes[-6:-1]) / 5

        # 量能递减：近5日比前5日缩量
        volume_decreasing = vol_last5 < vol_first5 * 1.1  # 允许10%的误差

        # 近5日地量天数
        ground_vol_days = 0
        for i in range(1, 6):
            if len(klines) > i:
                day_vol = volumes[-i]
                if day_vol < vol_20d * 0.50:
                    ground_vol_days += 1

        # 量能萎缩判定
        shrink_ok = (vol_ratio_10d < self.volume_shrink or
                     ground_vol_days >= 2 or
                     (volume_decreasing and vol_ratio_10d < 0.80))
        if not shrink_ok:
            return result

        # ---- 条件3: 近5日振幅 < 4%（横盘蓄势）----
        if len(klines) < 6:
            return result

        recent_5d = klines[-5:]
        range_5d = (max(k.high for k in recent_5d) -
                   min(k.low for k in recent_5d))
        range_5d_pct = range_5d / cur_close * 100

        if range_5d_pct > self.max_range_5d:
            return result

        # ---- 条件4: MA20走平或拐头向上 ----
        ma20_vals = ma(closes, 20)
        if not ma20_vals or ma20_vals[-1] is None:
            return result

        cur_ma20 = ma20_vals[-1]
        if len(ma20_vals) < 6 or ma20_vals[-6] is None:
            return result

        # MA20近5日变化率
        ma20_5d_ago = ma20_vals[-6]
        ma20_change = (cur_ma20 - ma20_5d_ago) / ma20_5d_ago * 100 if ma20_5d_ago > 0 else 0

        # MA20走平: 近5日变化 < 0.3%（收紧标准，-0.5%不算走平）
        # MA20拐头: 当前MA20 >= 前一日MA20 且 之前在下降
        ma10_vals = ma(closes, 10)
        cur_ma10 = ma10_vals[-1] if ma10_vals and ma10_vals[-1] is not None else 0

        ma20_flat = abs(ma20_change) < 0.3  # 走平（收紧到0.3%）
        ma20_turning_up = False
        if len(ma20_vals) >= 3 and ma20_vals[-2] is not None and ma20_vals[-3] is not None:
            # 之前在下降，现在开始走平/上升
            was_declining = ma20_vals[-3] > ma20_vals[-2]
            now_rising_or_flat = cur_ma20 >= ma20_vals[-2]
            ma20_turning_up = was_declining and now_rising_or_flat

        if not (ma20_flat or ma20_turning_up):
            return result

        # ---- 条件5: 近3日涨幅 < 5%（还没反弹）----
        # 同时排除近3日暴跌 > 8% 的（急跌不是蓄势）
        if len(closes) >= 4:
            gain_3d = (closes[-1] - closes[-4]) / closes[-4] * 100
            if gain_3d > self.max_recent_gain:
                return result
            gain_1d = (closes[-1] - closes[-2]) / closes[-2] * 100
            if gain_1d > 7:
                return result
            # 急跌不是蓄势
            if gain_3d < -8:
                return result

        # ---- 加分: MA60支撑 ----
        ma60_vals = ma(closes, 60)
        cur_ma60 = ma60_vals[-1] if ma60_vals and ma60_vals[-1] is not None else 0
        near_ma60 = False
        if cur_ma60 > 0:
            dev_ma60 = abs(cur_close - cur_ma60) / cur_ma60
            near_ma60 = dev_ma60 < 0.03  # 3%以内

        # ============================================================
        # 所有条件满足，计算信号
        # ============================================================

        # 止损: 60日低点-2% 或 MA60-1ATR
        atr_vals = atr(klines, 14)
        cur_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0

        stop_low = low_60 * 0.98
        if cur_ma60 > 0 and cur_atr > 0:
            stop_ma60 = cur_ma60 - cur_atr
            stop_loss = max(stop_low, stop_ma60)
        else:
            stop_loss = stop_low
        stop_loss = round(stop_loss, 2)

        # 目标: 前高 或 入场价+2ATR（蓄势后空间大）
        if cur_atr > 0:
            target_atr = cur_close + cur_atr * 2.5
        else:
            target_atr = cur_close * 1.15
        target_price = min(high_60, target_atr)  # 不超过前高
        if high_60 > cur_close * 1.30:
            target_price = round(target_atr, 2)  # 前高太远用ATR
        target_price = round(target_price, 2)

        risk_reward = calc_risk_reward(cur_close, stop_loss, target_price)

        # ---- 信号强度评分 ----
        score = {}
        total_strength = 0.0

        # 1. 回调深度评分 (权重20)
        if pullback_pct >= 30:
            pb_score = 90  # 深度回调
        elif pullback_pct >= 20:
            pb_score = 80
        elif pullback_pct >= 15:
            pb_score = 65
        else:
            pb_score = 40
        score["pullback_depth"] = round(pb_score, 1)
        total_strength += pb_score * 0.20

        # 2. 量能萎缩评分 (权重30)
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
        score["volume_shrink"] = round(vol_score, 1)
        total_strength += vol_score * 0.30

        # 3. 横盘蓄势评分 (权重25)
        if range_5d_pct < 2:
            range_score = 95  # 极度收敛
        elif range_5d_pct < 3:
            range_score = 80
        elif range_5d_pct < 4:
            range_score = 60
        else:
            range_score = 40
        score["consolidation"] = round(range_score, 1)
        total_strength += range_score * 0.25

        # 4. 均线走平评分 (权重25)
        if ma20_turning_up:
            ma_score = 90
        elif ma20_flat:
            ma_score = 70
        else:
            ma_score = 30
        score["ma_flat"] = round(ma_score, 1)
        total_strength += ma_score * 0.25

        # MA60支撑加分
        if near_ma60:
            total_strength += 8
            score["ma60_support"] = True
        else:
            score["ma60_support"] = False

        # ATR收缩加分
        if atr_vals and cur_atr > 0 and len(atr_vals) >= 11 and atr_vals[-11] is not None:
            atr_contraction = cur_atr / atr_vals[-11]
            if atr_contraction < 0.60:
                total_strength += 5
                score["atr_contraction"] = round(atr_contraction, 2)

        strength = round(min(100, total_strength), 1)

        result.triggered = True
        result.strength = strength
        result.entry_price = round(cur_close, 2)
        result.stop_loss = stop_loss
        result.target_price = target_price
        result.risk_reward = risk_reward
        result.score = score
        result.details = {
            "pullback_pct": round(pullback_pct, 2),
            "high_60": round(high_60, 2),
            "low_60": round(low_60, 2),
            "distance_from_low_pct": round(distance_from_low, 2),
            "vol_ratio_10d": round(vol_ratio_10d, 2),
            "ground_vol_days": ground_vol_days,
            "range_5d_pct": round(range_5d_pct, 2),
            "ma20_change_5d": round(ma20_change, 2),
            "ma20_turning_up": ma20_turning_up,
            "near_ma60": near_ma60,
            "atr14": round(cur_atr, 2),
            "gain_3d": round((closes[-1] - closes[-4]) / closes[-4] * 100, 2) if len(closes) >= 4 else 0,
            "strategy_version": "v2_蓄势",
        }

        return result
