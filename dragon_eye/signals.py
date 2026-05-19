"""
dragon_eye.signals — 技术信号检测库

纯函数式设计，输入K线列表，输出信号结果。
不依赖任何外部数据源，可独立运行和测试。

信号类型:
  - MA金叉/死叉
  - 放量/缩量
  - 止跌信号（下影线/十字星）
  - 突破信号
  - 均线多头排列
  - 量价背离
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .data_models import Kline


# ============================================================
# 信号结果数据类
# ============================================================

@dataclass
class Signal:
    """信号结果"""
    name: str = ""                 # 信号名称
    triggered: bool = False        # 是否触发
    strength: float = 0.0          # 信号强度 0-100
    direction: str = ""            # 方向: bull/bear/neutral
    details: dict = field(default_factory=dict)  # 详细参数


@dataclass
class MASignal(Signal):
    """MA信号"""
    name: str = "ma_cross"
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    cross_type: str = ""           # golden/dead/none


@dataclass
class VolumeSignal(Signal):
    """量能信号"""
    name: str = "volume"
    volume_ratio: float = 0.0     # 量比
    is_shrink: bool = False        # 缩量
    is_expand: bool = False        # 放量


@dataclass
class StopDropSignal(Signal):
    """止跌信号"""
    name: str = "stop_drop"
    lower_shadow_ratio: float = 0.0   # 下影线占比
    is_doji: bool = False             # 十字星
    is_hammer: bool = False           # 锤子线


@dataclass
class BreakoutSignal(Signal):
    """突破信号"""
    name: str = "breakout"
    breakout_price: float = 0.0    # 突破价位
    breakout_type: str = ""         # up/down
    volume_confirm: bool = False   # 量能确认


# ============================================================
# 基础指标计算
# ============================================================

def ma(values: list[float], period: int) -> list[Optional[float]]:
    """简单移动平均"""
    result: list[Optional[float]] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def ema(values: list[float], period: int) -> list[Optional[float]]:
    """指数移动平均"""
    if not values:
        return []
    result: list[Optional[float]] = [None] * len(values)
    k = 2 / (period + 1)

    # 第一个有效值用SMA
    first_valid = period - 1
    if first_valid >= len(values):
        return result

    result[first_valid] = sum(values[:period]) / period
    for i in range(first_valid + 1, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)

    return result


def atr(klines: list[Kline], period: int = 14) -> list[Optional[float]]:
    """平均真实波幅"""
    if len(klines) < 2:
        return [None] * len(klines)

    tr_list = []
    for i in range(len(klines)):
        if i == 0:
            tr_list.append(klines[i].high - klines[i].low)
        else:
            tr = max(
                klines[i].high - klines[i].low,
                abs(klines[i].high - klines[i - 1].close),
                abs(klines[i].low - klines[i - 1].close),
            )
            tr_list.append(tr)

    return ma(tr_list, period)


# ============================================================
# 信号检测函数
# ============================================================

def check_ma_cross(klines: list[Kline], short: int = 5, long: int = 10) -> MASignal:
    """MA金叉/死叉检测

    金叉: 短期MA从下方穿越长期MA → 看多
    死叉: 短期MA从上方穿越长期MA → 看空
    """
    if len(klines) < long + 1:
        return MASignal(triggered=False)

    closes = [k.close for k in klines]
    short_ma = ma(closes, short)
    long_ma = ma(closes, long)

    idx = len(klines) - 1
    idx_prev = idx - 1

    s_now, s_prev = short_ma[idx], short_ma[idx_prev]
    l_now, l_prev = long_ma[idx], long_ma[idx_prev]

    if any(v is None for v in [s_now, s_prev, l_now, l_prev]):
        return MASignal(triggered=False)

    signal = MASignal(
        triggered=True,
        ma5=short_ma[-1] if short_ma[-1] else 0,
        ma10=long_ma[-1] if long_ma[-1] else 0,
    )

    # 计算MA20/MA60
    ma20_vals = ma(closes, 20)
    ma60_vals = ma(closes, 60)
    signal.ma20 = ma20_vals[-1] if ma20_vals[-1] else 0
    signal.ma60 = ma60_vals[-1] if ma60_vals[-1] else 0

    # 金叉
    if s_prev <= l_prev and s_now > l_now:
        signal.cross_type = "golden"
        signal.direction = "bull"
        signal.strength = 70 + min(30, abs(s_now - l_now) / l_now * 1000)
    # 死叉
    elif s_prev >= l_prev and s_now < l_now:
        signal.cross_type = "dead"
        signal.direction = "bear"
        signal.strength = 70 + min(30, abs(l_now - s_now) / l_now * 1000)
    else:
        signal.cross_type = "none"
        signal.direction = "neutral"
        signal.strength = 0

    return signal


def check_volume(klines: list[Kline], period: int = 20, ratio_threshold: float = 1.5,
                 shrink_threshold: float = 0.7) -> VolumeSignal:
    """量能信号检测

    放量: 当日量 > 均量 * ratio_threshold
    缩量: 当日量 < 均量 * shrink_threshold
    """
    if len(klines) < period + 1:
        return VolumeSignal(triggered=False)

    volumes = [k.volume for k in klines]
    avg_vol = sum(volumes[-period - 1:-1]) / period
    today_vol = volumes[-1]

    if avg_vol <= 0:
        return VolumeSignal(triggered=False)

    vol_ratio = today_vol / avg_vol

    signal = VolumeSignal(
        triggered=True,
        volume_ratio=round(vol_ratio, 2),
    )

    if vol_ratio >= ratio_threshold:
        signal.is_expand = True
        signal.direction = "bull"
        signal.strength = min(100, 50 + (vol_ratio - ratio_threshold) * 20)
    elif vol_ratio <= shrink_threshold:
        signal.is_shrink = True
        signal.direction = "bear"
        signal.strength = min(100, 50 + (shrink_threshold - vol_ratio) * 30)
    else:
        signal.direction = "neutral"
        signal.strength = 20

    return signal


def check_stop_drop(klines: list[Kline]) -> StopDropSignal:
    """止跌信号检测

    下影线长: 实体的2倍以上
    十字星: 实体很小，上下影线长
    锤子线: 下影线长，上影线短，实体在上方
    """
    if len(klines) < 2:
        return StopDropSignal(triggered=False)

    k = klines[-1]
    body = abs(k.close - k.open)
    total = k.high - k.low

    if total <= 0:
        return StopDropSignal(triggered=False)

    upper_shadow = k.high - max(k.open, k.close)
    lower_shadow = min(k.open, k.close) - k.low

    signal = StopDropSignal(triggered=True)
    signal.lower_shadow_ratio = round(lower_shadow / total, 3)

    # 十字星: 实体很小（< 总长的10%）
    if body / total < 0.1:
        signal.is_doji = True
        signal.direction = "neutral"
        signal.strength = 60

    # 下影线占比 > 60% 且有实体
    elif lower_shadow / total > 0.6 and body > 0:
        signal.is_hammer = True
        signal.direction = "bull"
        signal.strength = min(100, 60 + signal.lower_shadow_ratio * 50)

    # 普通下影线
    elif lower_shadow / total > 0.4:
        signal.direction = "bull"
        signal.strength = 40

    else:
        signal.direction = "neutral"
        signal.strength = 10

    return signal


def check_breakout(klines: list[Kline], period: int = 20) -> BreakoutSignal:
    """突破信号检测

    向上突破: 收盘价突破近N日最高价
    向下突破: 收盘价跌破近N日最低价
    """
    if len(klines) < period + 1:
        return BreakoutSignal(triggered=False)

    recent = klines[-period - 1:-1]
    high_n = max(k.high for k in recent)
    low_n = min(k.low for k in recent)

    today = klines[-1]
    prev_close = klines[-2].close if len(klines) >= 2 else today.close

    signal = BreakoutSignal(triggered=True)

    # 向上突破
    if today.close > high_n and prev_close <= high_n:
        signal.breakout_type = "up"
        signal.breakout_price = high_n
        signal.direction = "bull"
        signal.strength = min(100, 70 + (today.close - high_n) / high_n * 500)
        # 量能确认
        if len(klines) >= 5:
            avg_vol = sum(k.volume for k in klines[-6:-1]) / 5
            signal.volume_confirm = today.volume > avg_vol * 1.2
            if signal.volume_confirm:
                signal.strength = min(100, signal.strength + 10)

    # 向下突破
    elif today.close < low_n and prev_close >= low_n:
        signal.breakout_type = "down"
        signal.breakout_price = low_n
        signal.direction = "bear"
        signal.strength = min(100, 70 + (low_n - today.close) / low_n * 500)

    else:
        signal.direction = "neutral"
        signal.strength = 0

    return signal


def check_ma_alignment(klines: list[Kline]) -> Signal:
    """均线多头排列检测

    MA5 > MA10 > MA20 > MA60 → 强多头
    """
    if len(klines) < 60:
        return Signal(name="ma_alignment", triggered=False)

    closes = [k.close for k in klines]
    ma5_val = ma(closes, 5)[-1]
    ma10_val = ma(closes, 10)[-1]
    ma20_val = ma(closes, 20)[-1]
    ma60_val = ma(closes, 60)[-1]

    if any(v is None for v in [ma5_val, ma10_val, ma20_val, ma60_val]):
        return Signal(name="ma_alignment", triggered=False)

    signal = Signal(name="ma_alignment", triggered=True)

    if ma5_val > ma10_val > ma20_val > ma60_val:
        signal.direction = "bull"
        signal.strength = 90
        signal.details = {"type": "strong_bull"}
    elif ma5_val > ma10_val > ma20_val:
        signal.direction = "bull"
        signal.strength = 70
        signal.details = {"type": "medium_bull"}
    elif ma5_val < ma10_val < ma20_val < ma60_val:
        signal.direction = "bear"
        signal.strength = 90
        signal.details = {"type": "strong_bear"}
    elif ma5_val < ma10_val < ma20_val:
        signal.direction = "bear"
        signal.strength = 70
        signal.details = {"type": "medium_bear"}
    else:
        signal.direction = "neutral"
        signal.strength = 30
        signal.details = {"type": "mixed"}

    return signal


def ma_angle(klines: list[Kline], period: int = 10) -> float:
    """MA均线角度

    返回角度值（度），正数=上升，负数=下降
    15°~40° 通常是最健康的上升角度
    """
    if len(klines) < period + 1:
        return 0.0

    closes = [k.close for k in klines]
    ma_vals = ma(closes, period)

    idx = len(klines) - 1
    idx_prev = idx - 1

    if ma_vals[idx] is None or ma_vals[idx_prev] is None or ma_vals[idx_prev] == 0:
        return 0.0

    ratio = ma_vals[idx] / ma_vals[idx_prev] - 1
    return math.atan(ratio * 100) * 57.296


# ============================================================
# 综合信号评分
# ============================================================

def score_technical(klines: list[Kline]) -> dict:
    """综合技术评分

    返回: {
        "total_score": 0-100,
        "signals": [...],
        "direction": bull/bear/neutral,
        "support": 支撑位,
        "resistance": 压力位,
    }
    """
    if len(klines) < 30:
        return {"total_score": 0, "signals": [], "direction": "neutral"}

    signals = []

    # 1. MA交叉
    ma_sig = check_ma_cross(klines)
    signals.append(ma_sig)

    # 2. 量能
    vol_sig = check_volume(klines)
    signals.append(vol_sig)

    # 3. 突破
    brk_sig = check_breakout(klines)
    signals.append(brk_sig)

    # 4. 均线排列
    align_sig = check_ma_alignment(klines)
    signals.append(align_sig)

    # 5. MA角度
    ang10 = ma_angle(klines, 10)
    ang20 = ma_angle(klines, 20)

    # 综合评分
    bull_score = 0
    bear_score = 0

    for sig in signals:
        if sig.direction == "bull":
            bull_score += sig.strength
        elif sig.direction == "bear":
            bear_score += sig.strength

    # MA角度加分
    if 15 < ang10 < 40 and 15 < ang20 < 40:
        bull_score += 30
    elif ang10 < -15 and ang20 < -15:
        bear_score += 30

    # 方向判断
    if bull_score > bear_score + 30:
        direction = "bull"
        total = min(100, bull_score * 0.5)
    elif bear_score > bull_score + 30:
        direction = "bear"
        total = min(100, bear_score * 0.5)
    else:
        direction = "neutral"
        total = min(100, (bull_score + bear_score) * 0.25)

    # 支撑压力位
    recent = klines[-20:] if len(klines) >= 20 else klines
    closes = [k.close for k in recent]
    highs = [k.high for k in recent]
    lows = [k.low for k in recent]

    closes_ma = ma([k.close for k in klines], 20)
    support = min(lows) if direction == "bull" else (closes_ma[-1] if closes_ma[-1] else min(lows))
    resistance = max(highs)

    return {
        "total_score": round(total, 1),
        "direction": direction,
        "signals": signals,
        "ma_angle_10": round(ang10, 1),
        "ma_angle_20": round(ang20, 1),
        "support": round(support, 2) if support else 0,
        "resistance": round(resistance, 2),
        "bull_score": round(bull_score, 1),
        "bear_score": round(bear_score, 1),
    }
