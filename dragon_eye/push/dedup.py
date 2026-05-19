"""
dragon_eye.push.dedup — 推送去重

同一只股票在N小时内不重复推送，基于JSON文件存储。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DedupStore:
    """推送去重存储"""

    def __init__(self, store_path: Optional[str] = None):
        if store_path is None:
            store_path = str(
                Path(__file__).parent.parent / "config" / "push_history.json"
            )
        self._path = Path(store_path)
        self._data: dict[str, str] = {}  # {code: last_push_time ISO}
        self._load()

    def _load(self) -> None:
        """从文件加载"""
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("去重记录加载失败: %s，使用空记录", e)
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        """保存到文件"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_dup(self, code: str, hours: int = 4) -> bool:
        """是否是重复推送（N小时内推过同一只股票）"""
        last = self._data.get(code)
        if not last:
            return False
        try:
            last_time = datetime.fromisoformat(last)
            return datetime.now() - last_time < timedelta(hours=hours)
        except ValueError:
            return False

    def mark_pushed(self, code: str) -> None:
        """标记已推送"""
        self._data[code] = datetime.now().isoformat()
        self._save()

    def cleanup(self, max_age_days: int = 7) -> int:
        """清理过期记录，返回清理数量"""
        cutoff = datetime.now() - timedelta(days=max_age_days)
        old_count = len(self._data)
        self._data = {
            k: v
            for k, v in self._data.items()
            if datetime.fromisoformat(v) >= cutoff
        }
        removed = old_count - len(self._data)
        if removed > 0:
            self._save()
            logger.info("清理过期去重记录: %d条", removed)
        return removed

    def clear(self) -> None:
        """清空所有记录"""
        self._data = {}
        self._save()
