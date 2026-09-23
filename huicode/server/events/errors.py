"""事件层的错误。

消息只说明原因，不带原始载荷或连接串——它们会进日志。
"""

from __future__ import annotations


class EventStoreError(Exception):
    """事件写入或读取无法完成。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class EventStreamError(Exception):
    """实时订阅无法建立或中断。"""
