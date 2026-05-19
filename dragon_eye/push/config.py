"""
dragon_eye.push.config — 推送配置
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path


class PushLevel(enum.Enum):
    """推送级别"""
    HIGH = "high"        # 猛突信号，立即推送
    MEDIUM = "medium"    # 策略信号
    LOW = "low"          # 每日汇总

    def __ge__(self, other):
        order = {PushLevel.LOW: 0, PushLevel.MEDIUM: 1, PushLevel.HIGH: 2}
        return order[self] >= order[other]

    def __gt__(self, other):
        order = {PushLevel.LOW: 0, PushLevel.MEDIUM: 1, PushLevel.HIGH: 2}
        return order[self] > order[other]

    def __le__(self, other):
        order = {PushLevel.LOW: 0, PushLevel.MEDIUM: 1, PushLevel.HIGH: 2}
        return order[self] <= order[other]

    def __lt__(self, other):
        order = {PushLevel.LOW: 0, PushLevel.MEDIUM: 1, PushLevel.HIGH: 2}
        return order[self] < order[other]


@dataclass
class PushConfig:
    """推送配置"""
    pushplus_token: str = "a84ae607d0f64a8580f223fb17526e33"
    min_level: PushLevel = PushLevel.MEDIUM
    dedup_hours: int = 4
    toast_enabled: bool = True
    pushplus_enabled: bool = True

    # 存储路径
    _config_dir: str = ""

    @property
    def config_dir(self) -> Path:
        if self._config_dir:
            return Path(self._config_dir)
        return Path(__file__).parent.parent / "config"

    def to_dict(self) -> dict:
        return {
            "pushplus_token": self.pushplus_token,
            "min_level": self.min_level.value,
            "dedup_hours": self.dedup_hours,
            "toast_enabled": self.toast_enabled,
            "pushplus_enabled": self.pushplus_enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PushConfig:
        return cls(
            pushplus_token=d.get("pushplus_token", cls.pushplus_token),
            min_level=PushLevel(d.get("min_level", "medium")),
            dedup_hours=d.get("dedup_hours", 4),
            toast_enabled=d.get("toast_enabled", True),
            pushplus_enabled=d.get("pushplus_enabled", True),
        )


def strength_to_level(strength: float) -> PushLevel:
    """信号强度转推送级别"""
    if strength >= 80:
        return PushLevel.HIGH
    if strength >= 60:
        return PushLevel.MEDIUM
    return PushLevel.LOW


def load_push_config(yaml_path: str | None = None) -> PushConfig:
    """从YAML文件加载推送配置"""
    if yaml_path is None:
        yaml_path = str(Path(__file__).parent.parent / "config" / "dragon_eye.yaml")

    path = Path(yaml_path)
    if not path.exists():
        return PushConfig()

    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        push_data = data.get("push", {})
        return PushConfig.from_dict(push_data)
    except ImportError:
        # 没有pyyaml，手动简单解析或用默认值
        return PushConfig()
    except Exception:
        return PushConfig()


def save_push_config(config: PushConfig, yaml_path: str | None = None) -> None:
    """保存推送配置到YAML文件"""
    if yaml_path is None:
        yaml_path = str(Path(__file__).parent.parent / "config" / "dragon_eye.yaml")

    path = Path(yaml_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 读取现有YAML（保留其他section）
    data = {}
    if path.exists():
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}

    data["push"] = config.to_dict()

    try:
        import yaml
        path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    except ImportError:
        # 没有pyyaml，写JSON格式作为fallback
        import json
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
