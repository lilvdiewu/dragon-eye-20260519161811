"""
dragon_eye.push.formatter — 推送消息格式化

4种模板: 策略信号 / 扫描汇总 / 个股分析 / 通用文本
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..strategy.base_strategy import StrategyResult


def _signal_type_cn(signal_type: str) -> str:
    """信号类型中文名"""
    return {"bottom_breakout": "底部起爆", "pullback_buy": "强势回调"}.get(
        signal_type, signal_type
    )


def _fmt_price(price: float) -> str:
    """格式化价格"""
    if price <= 0:
        return "-"
    return f"{price:.2f}"


class MessageFormatter:
    """推送消息格式化器"""

    @staticmethod
    def format_signal(result: StrategyResult) -> tuple[str, str]:
        """格式化单条策略信号

        Returns:
            (title, content)
        """
        sig_cn = _signal_type_cn(result.signal_type)
        title = f"[{sig_cn}] {result.name} {result.code}"

        lines = [
            f"强度:{result.strength:.0f} | 买入:{_fmt_price(result.entry_price)} | 止损:{_fmt_price(result.stop_loss)} | 目标:{_fmt_price(result.target_price)}",
        ]

        if result.risk_reward > 0:
            lines.append(f"风险收益比:{result.risk_reward:.2f}")

        # 补充details中的关键信息
        d = result.details
        extra_parts = []
        if "volume_ratio_5d" in d and d["volume_ratio_5d"] > 0:
            extra_parts.append(f"量比5日:{d['volume_ratio_5d']:.1f}")
        if "ma_cross" in d and d["ma_cross"]:
            extra_parts.append("MA金叉")
        if "change_3d" in d:
            extra_parts.append(f"近3日涨{d['change_3d']:.1f}%")
        if "change_20d" in d:
            extra_parts.append(f"20日涨{d['change_20d']:.1f}%")
        if "pullback_to_ma" in d:
            extra_parts.append(f"回调至{d['pullback_to_ma']}")

        if extra_parts:
            lines.append(" | ".join(extra_parts))

        content = "\n".join(lines)
        return title, content

    @staticmethod
    def format_scan_summary(results: list[StrategyResult]) -> tuple[str, str]:
        """格式化扫描汇总报告

        Returns:
            (title, content)
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"龙瞳Pro全市场扫描 {now}"

        # 按策略分组
        groups: dict[str, list[StrategyResult]] = {}
        for r in results:
            groups.setdefault(r.signal_type, []).append(r)

        lines = []
        for sig_type, group in groups.items():
            sig_cn = _signal_type_cn(sig_type)
            lines.append(f"{sig_cn}: {len(group)}只")

        lines.append("")

        # TOP5
        for sig_type, group in groups.items():
            sig_cn = _signal_type_cn(sig_type)
            top5 = group[:5]
            lines.append(f"--- TOP5 {sig_cn} ---")
            for i, r in enumerate(top5, 1):
                entry = _fmt_price(r.entry_price)
                lines.append(f"{i}. {r.name} {r.code} 强度{r.strength:.0f} 买入{entry}")
            lines.append("")

        content = "\n".join(lines)
        return title, content

    @staticmethod
    def format_analysis_report(report) -> tuple[str, str]:
        """格式化个股分析报告

        Args:
            report: AnalysisReport 实例

        Returns:
            (title, content)
        """
        title = f"[个股分析] {report.name} {report.code}"

        lines = [
            f"趋势:{report.trend or '-'} | 量价:{report.volume_status or '-'} | 估值:{report.valuation_level or '-'}",
            f"评分:{report.total_score:.0f} | 建议:{report.recommendation or '-'}",
        ]

        # 策略信号
        if report.signals:
            sig_names = [
                f"{_signal_type_cn(s.signal_type)}({s.strength:.0f})"
                for s in report.signals
                if s.triggered
            ]
            if sig_names:
                lines.append(f"信号:{' | '.join(sig_names)}")

        # TradingAgents评级
        if report.ta_result and report.ta_result.rating:
            ta = report.ta_result
            lines.append("")
            lines.append(f"10-Agent评级:{ta.rating_cn} | 目标价:{_fmt_price(ta.price_target)}")
            if ta.executive_summary:
                # 截取摘要前100字
                summary = ta.executive_summary[:100].replace("\n", " ")
                lines.append(f"摘要:{summary}")

        content = "\n".join(lines)
        return title, content

    @staticmethod
    def format_text(content: str, title: str = "龙瞳Pro") -> tuple[str, str]:
        """纯文本格式化（通用）"""
        return title, content
