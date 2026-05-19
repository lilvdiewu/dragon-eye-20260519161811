"""
dragon_eye.push.pushplus — PushPlus微信推送

端点: http://www.pushplus.plus/send
支持txt/html/markdown三种模板。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class PushPlusSender:
    """PushPlus微信推送"""

    API_URL = "http://www.pushplus.plus/send"

    def __init__(self, token: str = "a84ae607d0f64a8580f223fb17526e33"):
        self.token = token

    def send(
        self,
        title: str,
        content: str,
        template: str = "txt",
        topic: str = "",
    ) -> dict:
        """发送推送

        Args:
            title: 消息标题
            content: 消息内容
            template: txt / html / markdown
            topic: 群组推送topic（可选）

        Returns:
            {"code": 200, "msg": "success"} 或错误信息
        """
        payload = {
            "token": self.token,
            "title": title,
            "content": content,
            "template": template,
        }
        if topic:
            payload["topic"] = topic

        # 临时移除代理环境变量，PushPlus不走代理
        old_http = os.environ.pop("http_proxy", None)
        old_https = os.environ.pop("https_proxy", None)
        old_http2 = os.environ.pop("HTTP_PROXY", None)
        old_https2 = os.environ.pop("HTTPS_PROXY", None)

        try:
            session = requests.Session()
            session.trust_env = False  # 确保不走系统代理
            resp = session.post(
                self.API_URL,
                json=payload,
                timeout=10,
            )
            result = resp.json()
            if result.get("code") == 200:
                logger.info("PushPlus推送成功: %s", title)
            else:
                logger.warning("PushPlus推送失败: %s → %s", title, result)
            return result
        except Exception as e:
            logger.error("PushPlus推送异常: %s → %s", title, e)
            return {"code": -1, "msg": str(e)}
        finally:
            # 恢复代理环境变量
            for key, val in [
                ("http_proxy", old_http),
                ("https_proxy", old_https),
                ("HTTP_PROXY", old_http2),
                ("HTTPS_PROXY", old_https2),
            ]:
                if val is not None:
                    os.environ[key] = val

    def send_html(self, title: str, html_content: str) -> dict:
        """发送HTML格式推送"""
        return self.send(title, html_content, template="html")

    def send_markdown(self, title: str, md_content: str) -> dict:
        """发送Markdown格式推送"""
        return self.send(title, md_content, template="markdown")
