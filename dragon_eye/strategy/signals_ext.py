"""
dragon_eye.strategy.signals_ext — 扩展信号库

基于 dragon_eye.signals 的辅助信号函数，为策略引擎服务。
"""
from __future__ import annotations

from typing import Optional

from ..data_models import Kline
from ..signals import ma, atr, Signal


# ============================================================
# MA拐头检测
# ============================================================

def check_ma_turning(klines: list[Kline], period: int = 10, lookback: int = 3) -> Signal:
    """MA拐头检测：近lookback日内MA从下降转为上升

    Args:
        klines: K线数据
        period: MA周期
        lookback: 回看天数

    Returns:
        Signal
    """
    if len(klines) < period + lookback:
        return Signal(name="ma_turning", triggered=False)

    closes = [k.close for k in klines]
    ma_vals = ma(closes, period)

    # 取最近 lookback+1 个MA值
    end_idx = len(klines) - 1
    start_idx = end_idx - lookback

    # 确保所有值有效
    recent_ma = []
    for i in range(start_idx, end_idx + 1):
        if ma_vals[i] is None:
            return Signal(name="ma_turning", triggered=False)
        recent_ma.append(ma_vals[i])

    # 检查是否先下降后上升
    # 前半段下降，后半段上升
    mid = len(recent_ma) // 2
    first_half = recent_ma[:mid + 1]
    second_half = recent_ma[mid:]

    # 前半段至少有一个下降
    declining = any(first_half[i] > first_half[i + 1] for i in range(len(first_half) - 1))
    # 后半段至少有一个上升
    rising = any(second_half[i] < second_half[i + 1] for i in range(len(second_half) - 1))

    # 更简单：最后一个MA值 > 前一个MA值 且 之前有下降段
    if ma_vals[end_idx] > ma_vals[end_idx - 1] and declining:
        # 计算拐头强度
        change_pct = (ma_vals[end_idx] - ma_vals[end_idx - 1]) / ma_vals[end_idx - 1] * 100
        strength = min(100, 50 + change_pct * 100)
        return Signal(
            name="ma_turning",
            triggered=True,
            strength=round(strength, 1),
            direction="bull",
            details={
                "period": period,
                "ma_value": round(ma_vals[end_idx], 2),
                "change_pct": round(change_pct, 3),
            },
        )

    return Signal(name="ma_turning", triggered=False)


# ============================================================
# 回调至MA附近检测
# ============================================================

def check_pullback_to_ma(klines: list[Kline], ma_period: int = 10,
                         deviation: float = 0.02) -> Signal:
    """回调至MA附近检测

    当前收盘价与MA偏差 < deviation 视为回踩MA

    Args:
        klines: K线数据
        ma_period: MA周期
        deviation: 偏差阈值（如0.02表示2%）

    Returns:
        Signal
    """
    if len(klines) < ma_period:
        return Signal(name="pullback_to_ma", triggered=False)

    closes = [k.close for k in klines]
    ma_vals = ma(closes, ma_period)
    cur_ma = ma_vals[-1]

    if cur_ma is None or cur_ma <= 0:
        return Signal(name="pullback_to_ma", triggered=False)

    cur_close = closes[-1]
    deviation_pct = abs(cur_close - cur_ma) / cur_ma

    if deviation_pct <= deviation:
        above = cur_close >= cur_ma
        return Signal(
            name="pullback_to_ma",
            triggered=True,
            strength=round(min(100, 60 + (1 - deviation_pct / deviation) * 40), 1),
            direction="bull" if above else "bear",
            details={
                "ma_period": ma_period,
                "ma_value": round(cur_ma, 2),
                "price": round(cur_close, 2),
                "deviation_pct": round(deviation_pct * 100, 2),
                "above_ma": above,
            },
        )

    return Signal(name="pullback_to_ma", triggered=False)


# ============================================================
# 波段高低点
# ============================================================

def find_swing_high(klines: list[Kline], lookback: int = 20) -> Optional[float]:
    """找出近N日的波段高点（最高价）"""
    if not klines or len(klines) < 2:
        return None
    window = klines[-lookback:] if len(klines) >= lookback else klines
    return max(k.high for k in window)


def find_swing_low(klines: list[Kline], lookback: int = 20) -> Optional[float]:
    """找出近N日的波段低点（最低价）"""
    if not klines or len(klines) < 2:
        return None
    window = klines[-lookback:] if len(klines) >= lookback else klines
    return min(k.low for k in window)


# ============================================================
# 风险收益比
# ============================================================

def calc_risk_reward(entry: float, stop: float, target: float) -> float:
    """计算风险收益比

    Returns:
        收益/风险，>2为较好，>3为优秀
    """
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


# ============================================================
# 低点附近判断
# ============================================================

def is_near_low(klines: list[Kline], period: int = 60, range_pct: float = 0.10) -> bool:
    """判断当前价格是否在近N日低点附近

    当前收盘价在 [low * (1 - range_pct), low * (1 + range_pct)] 区间内
    """
    if len(klines) < period:
        period = len(klines)
    if period < 2:
        return False

    window = klines[-period:]
    low_price = min(k.low for k in window)
    cur_close = klines[-1].close

    lower_bound = low_price * (1 - range_pct)
    upper_bound = low_price * (1 + range_pct)

    return lower_bound <= cur_close <= upper_bound


# ============================================================
# 近N日涨幅
# ============================================================

def recent_gain(klines: list[Kline], days: int = 3) -> float:
    """近N日涨幅%

    Args:
        klines: K线数据
        days: 天数

    Returns:
        涨幅百分比，如 5.5 表示涨5.5%
    """
    if len(klines) < days + 1:
        return 0.0

    start_close = klines[-(days + 1)].close
    end_close = klines[-1].close

    if start_close <= 0:
        return 0.0

    return round((end_close - start_close) / start_close * 100, 2)
