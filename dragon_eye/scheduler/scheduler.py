"""
dragon_eye.scheduler.scheduler — 定时调度器

基于APScheduler，每日收盘后自动扫描+推送。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from ..push.config import PushConfig, load_push_config
from ..push.manager import PushManager
from ..strategy.base_strategy import StrategyResult
from ..strategy.screener import Screener
from .config import SchedulerConfig, load_scheduler_config

logger = logging.getLogger(__name__)


class DragonEyeScheduler:
    """龙瞳Pro定时调度器

    用法:
        sched = DragonEyeScheduler()
        sched.start()          # 启动后台调度
        results = sched.run_scan_now()  # 手动触发
        sched.stop()           # 停止
    """

    def __init__(
        self,
        scheduler_config: Optional[SchedulerConfig] = None,
        push_config: Optional[PushConfig] = None,
    ):
        self.sched_config = scheduler_config or load_scheduler_config()
        self.push_config = push_config or load_push_config()
        self.push_mgr = PushManager(self.push_config)
        self.screener = Screener()
        self._scheduler: Optional[BackgroundScheduler] = None
        self._last_scan_results: list[StrategyResult] = []

    def start(self) -> None:
        """启动调度器"""
        if not self.sched_config.enabled:
            logger.info("调度器未启用，跳过启动")
            return

        if self._scheduler and self._scheduler.running:
            logger.warning("调度器已在运行")
            return

        self._scheduler = BackgroundScheduler(daemon=True)

        # 每日收盘后扫描
        self._scheduler.add_job(
            self._job_daily_scan,
            "cron",
            hour=int(self.sched_config.scan_time.split(":")[0]),
            minute=int(self.sched_config.scan_time.split(":")[1]),
            id="daily_scan",
            replace_existing=True,
        )

        # 每日汇总推送
        self._scheduler.add_job(
            self._job_daily_summary,
            "cron",
            hour=int(self.sched_config.summary_time.split(":")[0]),
            minute=int(self.sched_config.summary_time.split(":")[1]),
            id="daily_summary",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            "调度器已启动: 扫描=%s, 汇总=%s",
            self.sched_config.scan_time,
            self.sched_config.summary_time,
        )

    def stop(self) -> None:
        """停止调度器"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("调度器已停止")

    def _job_daily_scan(self) -> None:
        """每日收盘后扫描"""
        logger.info("=== 定时扫描开始 ===")
        try:
            results = self._do_scan()
            self._last_scan_results = results

            # 高强度信号立即推送
            stats = self.push_mgr.push_batch(results)
            logger.info("定时扫描推送: %s", stats)

        except Exception as e:
            logger.error("定时扫描失败: %s", e, exc_info=True)
            self.push_mgr.push_custom(
                "龙瞳Pro扫描异常",
                f"定时扫描失败: {e}",
            )

    def _job_daily_summary(self) -> None:
        """每日汇总推送"""
        logger.info("=== 定时汇总推送 ===")
        if not self._last_scan_results:
            logger.info("无扫描结果，跳过汇总")
            return

        self.push_mgr.push_scan_summary(self._last_scan_results)

    def _do_scan(self) -> list[StrategyResult]:
        """执行扫描"""
        watchlist = self.sched_config.watchlist

        if watchlist:
            # 自选股扫描
            results = self.screener.scan_watchlist(watchlist)
        else:
            # 全市场扫描
            results = self.screener.scan_all()

            # 按最低强度过滤
            if self.sched_config.min_strength > 0:
                results = [
                    r for r in results
                    if r.strength >= self.sched_config.min_strength
                ]

        return results

    def run_scan_now(self) -> list[StrategyResult]:
        """手动触发扫描（不经过调度器）"""
        logger.info("手动触发扫描")
        results = self._do_scan()
        self._last_scan_results = results
        return results

    def get_next_run_time(self) -> str | None:
        """获取下次执行时间"""
        if not self._scheduler or not self._scheduler.running:
            return None
        job = self._scheduler.get_job("daily_scan")
        if job and job.next_run_time:
            return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
        return None

    @property
    def is_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running
