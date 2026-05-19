"""
dragon_eye.push.toast — Windows桌面Toast通知

通过PowerShell BalloonTip实现。
"""
from __future__ import annotations

import logging
import subprocess
import platform

logger = logging.getLogger(__name__)


class WindowsToast:
    """Windows桌面Toast通知"""

    @staticmethod
    def send(title: str, content: str, duration: int = 5000) -> bool:
        """发送Windows Toast通知

        Args:
            title: 通知标题
            content: 通知内容
            duration: 显示时长(ms)，默认5秒

        Returns:
            是否发送成功
        """
        if platform.system() != "Windows":
            logger.debug("非Windows系统，跳过Toast通知")
            return False

        # 转义PowerShell特殊字符
        safe_title = title.replace("'", "''").replace("`", "``")
        safe_content = content.replace("'", "''").replace("`", "``")[:200]  # 截断过长内容

        ps_cmd = f"""
[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip({duration}, '{safe_title}', '{safe_content}', 'Info')
Start-Sleep -Seconds 6
$n.Dispose()
"""
        try:
            subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            logger.info("Toast通知已发送: %s", title)
            return True
        except Exception as e:
            logger.warning("Toast通知发送失败: %s → %s", title, e)
            return False
