"""数据库提交后把事件通知发到 Redis。

**发的是通知，不是事件本体。** 载荷只有会话 id 和序号，订阅者据此去数据库补齐。

这么设计有三个好处：

1. 数据库是唯一事实来源。丢一条通知只损失一次延迟，不损失正确性
   （plan.md："不依赖 Redis 消息永不丢失"）。
2. 不存在"Redis 里的载荷与数据库不一致"这种状态。
3. 通知体很小，不会因为一次工具输出把 Redis 打满。

**发布失败不抛异常。** 事件此时已经提交，把发布失败当成请求失败是错的——
调用方会以为事件没写进去。返回 False，由订阅者的数据库补偿路径兜住。
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

logger = logging.getLogger("huicode.server.events")


class EventPublisher:
    def __init__(self, redis=None):
        self.redis = redis

    @staticmethod
    def channel(session_id: UUID) -> str:
        return f"huicode:session:{session_id}:events"

    async def publish(self, session_id: UUID, sequence: int) -> bool:
        """发布一条"有新事件"的通知；返回是否成功。"""
        if self.redis is None:
            return False
        try:
            payload = json.dumps({"session_id": str(session_id), "sequence": int(sequence)})
            await self.redis.publish(self.channel(session_id), payload)
            return True
        except Exception:
            # 只记录发生了什么，不记录连接串或载荷。
            logger.warning(json.dumps({
                "event": "event_publish_failed",
                "session_id": str(session_id),
                "sequence": int(sequence),
            }))
            return False
