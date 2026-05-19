"""
dragon_eye.strategy.ma120_reversal — MA120踩穿反转选股策略

核心逻辑: 均线斜率>0 + 价格跌破MA120<1% + 量比<0.8 + 90天内<=1次踩穿

这是天哥的核心策略，寻找在MA120上方运行、短暂跌破后企稳的股票。

触发条件:
  1. MA120斜率>0（均线向上，大趋势看多）
  2. 当前价格跌破MA120但距离<1%（踩穿而非远离）
  3. 近5日量比<0.8（缩量踩穿，恐慌盘出尽）
  4. 90天内此前<=1次踩穿（首次或第二次踩穿最有效）

加分条件:
  - 所在行业/概念为热门板块（板块加分）
  - 近3日跌幅收窄（企稳迹象）
  - 下影线较长（支撑确认）
"""
from __future__ import annotations

from dataclasses import dataclass

from ..data_models import Kline
from ..signals import ma, atr, check_volume
from .base_strategy import BaseStrategy, StrategyResult
from .signals_ext import calc_risk_reward, find_swing_low


class MA120Reversal(BaseStrategy):
    """MA120踩穿反转策略"""

    name = "ma120_reversal"
    description = "MA120踩穿反转：均线向上+缩量跌破+首次踩穿"

    def __init__(self,
                 ma_period: int = 120,
                 slope_threshold: float = 0.0,
                 break_pct: float = 1.0,
                 volume_ratio_max: float = 0.8,
                 max_puncture_90d: int = 1,
                 lookback: int = 90):
        self.ma_period = ma_period
        self.slope_threshold = slope_threshold    # 均线斜率阈值（>0表示向上）
        self.break_pct = break_pct               # 跌破MA120的最大距离(%)
        self.volume_ratio_max = volume_ratio_max  # 量比上限
        self.max_puncture_90d = max_puncture_90d  # 90天内最大踩穿次数
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
        if len(klines) < self.ma_period + 10:
            return result

        closes = [k.close for k in klines]
        volumes = [k.volume for k in klines]
        cur_close = closes[-1]

        # ---- 计算MA120 ----
        ma120_vals = ma(closes, self.ma_period)
        if ma120_vals[-1] is None:
            return result

        ma120_now = ma120_vals[-1]
        if ma120_now <= 0:
            return result

        # ---- 条件1: MA120斜率>0（均线向上）----
        # 用近5日MA120的变化率计算斜率
        if ma120_vals[-6] is None:
            return result

        ma120_5d_ago = ma120_vals[-6]
        slope = (ma120_now - ma120_5d_ago) / ma120_5d_ago * 100  # 5日变化率%

        if slope <= self.slope_threshold:
            return result

        # ---- 条件2: 价格跌破MA120但距离<1% ----
        distance_pct = (cur_close - ma120_now) / ma120_now * 100  # 负数=跌破

        if distance_pct > 0:
            # 还在MA120上方，不算踩穿
            return result

        if distance_pct < -self.break_pct:
            # 跌破太多，不是踩穿而是远离
            return result

        # ---- 条件3: 量比<0.8（缩量）----
        if len(klines) < 25:
            return result

        vol_20d = sum(volumes[-21:-1]) / 20
        if vol_20d <= 0:
            return result

        # 近5日平均量比
        vol_ratios = []
        for i in range(1, 6):
            if len(klines) > i:
                vol_ratios.append(volumes[-i] / vol_20d)

        avg_vol_ratio = sum(vol_ratios) / len(vol_ratios) if vol_ratios else 1.0

        if avg_vol_ratio > self.volume_ratio_max:
            # 量比太大，不是缩量踩穿
            # 宽容度：当日放量但近5日均值仍<1.0
            if avg_vol_ratio > 1.0:
                return result

        # ---- 条件4: 90天内踩穿次数 <=1 ----
        puncture_count = 0
        window_start = max(0, len(klines) - self.lookback)

        for i in range(window_start, len(klines)):
            if ma120_vals[i] is not None and ma120_vals[i] > 0:
                if closes[i] < ma120_vals[i]:
                    # 连续跌破只算一次
                    if i == window_start or (i > 0 and closes[i-1] >= ma120_vals[i-1]):
                        puncture_count += 1

        if puncture_count > self.max_puncture_90d:
            return result

        # ============================================================
        # 所有条件满足，计算信号
        # ============================================================

        # 止损价: MA120下方2% 或 近20日低点
        stop_ma120 = ma120_now * 0.98
        stop_swing = find_swing_low(klines, 20)
        stop_loss = min(stop_ma120, stop_swing) if stop_swing else stop_ma120
        stop_loss = round(stop_loss, 2)

        # 目标价: MA20位置 或 MA120上方3%
        ma20_vals = ma(closes, 20)
        ma20_val = ma20_vals[-1] if ma20_vals and ma20_vals[-1] else 0
        target_ma120 = ma120_now * 1.03
        target_price = max(target_ma120, ma20_val) if ma20_val > 0 else target_ma120
        target_price = round(target_price, 2)

        risk_reward = calc_risk_reward(cur_close, stop_loss, target_price)

        # ---- 信号强度评分 ----
        score = {}
        total_strength = 0.0

        # 1. 均线斜率评分 (权重25) — 斜率越陡越好（但不能太陡）
        if slope > 2.0:
            slope_score = 60  # 太陡可能不稳定
        elif slope > 1.0:
            slope_score = 90  # 1-2%最健康
        elif slope > 0.5:
            slope_score = 80
        elif slope > 0:
            slope_score = 65  # 微弱向上
        else:
            slope_score = 30
        score["ma120_slope"] = round(slope, 3)
        score["slope_score"] = slope_score
        total_strength += slope_score * 0.25

        # 2. 跌破距离评分 (权重25) — 越贴近MA120越好
        abs_dist = abs(distance_pct)
        if abs_dist < 0.2:
            dist_score = 95  # 几乎在MA120上
        elif abs_dist < 0.5:
            dist_score = 85
        elif abs_dist < 0.8:
            dist_score = 70
        else:
            dist_score = 50
        score["distance_pct"] = round(distance_pct, 3)
        score["distance_score"] = dist_score
        total_strength += dist_score * 0.25

        # 3. 缩量评分 (权重25) — 量比越小越好（但不能完全没有量）
        if avg_vol_ratio < 0.3:
            vol_score = 95  # 极度缩量
        elif avg_vol_ratio < 0.5:
            vol_score = 85
        elif avg_vol_ratio < 0.7:
            vol_score = 70
        else:
            vol_score = 50
        score["avg_vol_ratio"] = round(avg_vol_ratio, 2)
        score["volume_score"] = vol_score
        total_strength += vol_score * 0.25

        # 4. 踩穿次数评分 (权重25) — 首次踩穿最好
        if puncture_count == 1:
            puncture_score = 90
        elif puncture_count == 2:
            puncture_score = 70
        else:
            puncture_score = 50
        score["puncture_count"] = puncture_count
        score["puncture_score"] = puncture_score
        total_strength += puncture_score * 0.25

        # 加分：近3日跌幅收窄（企稳）
        if len(closes) >= 4:
            decline_3d = (closes[-1] - closes[-4]) / closes[-4] * 100
            decline_2d = (closes[-1] - closes[-3]) / closes[-3] * 100 if len(closes) >= 3 else 0
            if decline_3d < 0 and decline_2d > decline_3d:
                total_strength += 8  # 跌幅收窄加分
                score["stabilizing"] = True

        # 加分：下影线较长（支撑确认）
        last_k = klines[-1]
        body = abs(last_k.close - last_k.open)
        total_range = last_k.high - last_k.low
        if total_range > 0:
            lower_shadow = min(last_k.open, last_k.close) - last_k.low
            if lower_shadow / total_range > 0.5:
                total_strength += 5
                score["long_lower_shadow"] = True

        strength = round(min(100, total_strength), 1)

        result.triggered = True
        result.strength = strength
        result.entry_price = round(cur_close, 2)
        result.stop_loss = stop_loss
        result.target_price = target_price
        result.risk_reward = risk_reward
        result.score = score
        result.details = {
            "ma120_value": round(ma120_now, 2),
            "ma120_slope_5d": round(slope, 3),
            "distance_from_ma120_pct": round(distance_pct, 3),
            "avg_vol_ratio_5d": round(avg_vol_ratio, 2),
            "puncture_count_90d": puncture_count,
            "strategy_version": "v1_踩穿反转",
        }

        return result
