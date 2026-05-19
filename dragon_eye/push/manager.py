"""
dragon_eye.push.manager — 推送管理器（统一入口）

集成级别过滤 + 去重 + 格式化 + 双通道推送。
"""
from __future__ import annotations

import logging
from typing import Optional

from .config import PushConfig, PushLevel, strength_to_level
from .dedup import DedupStore
from .formatter import MessageFormatter
from .pushplus import PushPlusSender
from .toast import WindowsToast
from ..strategy.base_strategy import StrategyResult

logger = logging.getLogger(__name__)


class PushManager:
    """推送管理器 — 统一入口

    用法:
        pm = PushManager()
        pm.push_signal(result)           # 单条策略信号
        pm.push_scan_summary(results)    # 扫描汇总
        pm.push_batch(results)           # 批量推送
    """

    def __init__(self, config: Optional[PushConfig] = None):
        if config is None:
            # Auto-load from dragon_eye.yaml
            try:
                from .config import load_push_config
                config = load_push_config()
            except Exception:
                config = PushConfig()
        self.config = config
        self.dedup = DedupStore()
        self.pushplus = PushPlusSender(self.config.pushplus_token)
        self.toast = WindowsToast()

    def push_signal(
        self,
        result: StrategyResult,
        level: Optional[PushLevel] = None,
    ) -> bool:
        """推送单条策略信号

        流程:
        1. 计算推送级别（默认按信号强度映射）
        2. 检查级别是否 >= min_level
        3. 检查去重
        4. 格式化 + 发送
        5. 标记已推送

        Returns:
            是否推送成功
        """
        if level is None:
            level = strength_to_level(result.strength)

        # 级别过滤
        if level < self.config.min_level:
            logger.debug(
                "级别不足，跳过: %s %s level=%s < min=%s",
                result.code, result.name, level, self.config.min_level,
            )
            return False

        # 去重
        if self.dedup.is_dup(result.code, hours=self.config.dedup_hours):
            logger.debug("去重跳过: %s %s", result.code, result.name)
            return False

        # 格式化
        title, content = MessageFormatter.format_signal(result)

        # 发送
        success = self._send(title, content)

        if success:
            self.dedup.mark_pushed(result.code)

        return success

    def push_scan_summary(self, results: list[StrategyResult]) -> bool:
        """推送扫描汇总报告（无去重，LOW级别）"""
        if not results:
            logger.info("无扫描结果，跳过汇总推送")
            return False

        title, content = MessageFormatter.format_scan_summary(results)
        return self._send(title, content)

    def push_analysis_report(self, report) -> bool:
        """推送个股分析报告"""
        title, content = MessageFormatter.format_analysis_report(report)
        return self._send(title, content)

    def push_batch(self, results: list[StrategyResult]) -> dict:
        """批量推送策略信号（逐条去重）

        Returns:
            {"pushed": N, "skipped_dup": N, "skipped_level": N}
        """
        stats = {"pushed": 0, "skipped_dup": 0, "skipped_level": 0}

        for r in results:
            if not r.triggered:
                continue

            level = strength_to_level(r.strength)

            # 级别过滤
            if level < self.config.min_level:
                stats["skipped_level"] += 1
                continue

            # 去重
            if self.dedup.is_dup(r.code, hours=self.config.dedup_hours):
                stats["skipped_dup"] += 1
                continue

            title, content = MessageFormatter.format_signal(r)
            if self._send(title, content):
                self.dedup.mark_pushed(r.code)
                stats["pushed"] += 1

        logger.info(
            "批量推送完成: pushed=%d, skipped_dup=%d, skipped_level=%d",
            stats["pushed"], stats["skipped_dup"], stats["skipped_level"],
        )
        return stats

    def push_custom(
        self,
        title: str,
        content: str,
        level: PushLevel = PushLevel.MEDIUM,
    ) -> bool:
        """自定义消息推送"""
        if level < self.config.min_level:
            return False
        return self._send(title, content)

    def _send(self, title: str, content: str) -> bool:
        """双通道发送（PushPlus + Toast）"""
        ok = True
        if self.config.pushplus_enabled:
            result = self.pushplus.send(title, content)
            if result.get("code") != 200:
                ok = False

        if self.config.toast_enabled:
            self.toast.send(title, content)

        return ok

    def clear_dedup(self) -> None:
        """清空去重记录"""
        self.dedup.clear()

    def cleanup_dedup(self, max_age_days: int = 7) -> int:
        """清理过期去重记录"""
        return self.dedup.cleanup(max_age_days)
