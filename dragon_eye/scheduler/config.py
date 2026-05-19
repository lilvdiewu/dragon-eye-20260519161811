"""
dragon_eye.scheduler.config — 调度器配置
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SchedulerConfig:
    """调度器配置"""
    enabled: bool = True
    scan_time: str = "15:30"           # 每日收盘后扫描时间
    summary_time: str = "16:00"        # 每日汇总推送时间
    strategies: list[str] = field(
        default_factory=lambda: ["bottom_breakout", "pullback_buy"]
    )
    min_strength: int = 50             # 最低信号强度
    watchlist: list[str] = field(default_factory=list)  # 自选股列表

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "scan_time": self.scan_time,
            "summary_time": self.summary_time,
            "strategies": self.strategies,
            "min_strength": self.min_strength,
            "watchlist": self.watchlist,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SchedulerConfig:
        return cls(
            enabled=d.get("enabled", True),
            scan_time=d.get("scan_time", "15:30"),
            summary_time=d.get("summary_time", "16:00"),
            strategies=d.get("strategies", ["bottom_breakout", "pullback_buy"]),
            min_strength=d.get("min_strength", 50),
            watchlist=d.get("watchlist", []),
        )


def load_scheduler_config(yaml_path: str | None = None) -> SchedulerConfig:
    """从YAML文件加载调度器配置"""
    if yaml_path is None:
        yaml_path = str(
            Path(__file__).parent.parent / "config" / "dragon_eye.yaml"
        )

    path = Path(yaml_path)
    if not path.exists():
        return SchedulerConfig()

    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        sched_data = data.get("scheduler", {})
        return SchedulerConfig.from_dict(sched_data)
    except Exception:
        return SchedulerConfig()


def save_scheduler_config(
    config: SchedulerConfig, yaml_path: str | None = None
) -> None:
    """保存调度器配置到YAML文件"""
    if yaml_path is None:
        yaml_path = str(
            Path(__file__).parent.parent / "config" / "dragon_eye.yaml"
        )

    path = Path(yaml_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    if path.exists():
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}

    data["scheduler"] = config.to_dict()

    try:
        import yaml
        path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
    except ImportError:
        import json
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
