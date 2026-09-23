"""审计记录写入。

只负责追加一行，不提交——提交由请求级事务决定（见 db/session.py 的 transaction）。
调用方拿到 session，写完继续做别的事，最后一次提交。

`request_id` 由 API 层从请求上下文取，domain 不认识 Request 对象。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from huicode.server.db.models import AuditLog
from huicode.server.runtime.scrubbing import get_scrubber


async def record(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    action: str,
    resource_type: str,
    request_id: str,
    actor_user_id: UUID | None = None,
    resource_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        # 属性名是 audit_metadata，列名保留 metadata；见 db/models.py 的说明。
        # 落库前脱敏（C57）：审计记录是长期保存的，密钥留在这里最危险。
        audit_metadata=get_scrubber().scrub_payload(metadata),
    )
    session.add(entry)
    return entry
