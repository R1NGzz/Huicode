"""事件的持久化与序号分配。

三条不变量，都由数据库而不是调用方保证：

1. **`sequence` 在单个会话内单调且唯一。** 分配方式是先 `SELECT ... FOR UPDATE`
   锁住父 `sessions` 行，再取 `MAX(sequence) + 1`。锁父行而不是锁事件行，是因为
   要防的是"两个并发追加同时看到同一个 MAX"——不存在的行锁不住。
   `uq_session_events_session_id_sequence` 是兜底：万一锁失效，写入会失败而不是
   产生重复序号（重复序号会让 SSE 补偿静默丢事件）。
2. **同一个 event_id 重复写入是幂等的。** `SessionEvent.id` 就是事件 id，重复
   append 返回已有行，不新增也不改序号。重试和至少一次投递都依赖这一点。
3. **`workspace_id` 取自父会话行，不取自调用方。** 让事件的工作区归属跟着会话走，
   调用方无法把事件写进别人的工作区。

`append` **复用调用方的事务**，不自己提交——这样"创建 Run + 写排队事件"才能是
一个原子操作（plan.md 的 Starting a run 数据流）。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from huicode.server.db.models import Session as SessionModel
from huicode.server.db.models import SessionEvent
from huicode.server.events.errors import EventStoreError
from huicode.server.events.types import RuntimeEvent
from huicode.server.runtime.scrubbing import get_scrubber

DEFAULT_BATCH = 200
MAX_BATCH = 1000


async def _lock_session(session: AsyncSession, session_id: UUID) -> SessionModel:
    """锁住会话行并返回它。并发追加到同一会话时会在这里排队。

    SQLite 方言会忽略 ``FOR UPDATE``（它靠整库写锁串行化），所以这段代码在
    SQLite 和 PostgreSQL 上都能跑，但**只有 PostgreSQL 上才是真正的行锁**。
    """
    row = await session.scalar(
        select(SessionModel).where(SessionModel.id == session_id).with_for_update()
    )
    if row is None:
        raise EventStoreError("session_not_found", "会话不存在")
    return row


async def _next_sequence(session: AsyncSession, session_id: UUID) -> int:
    current = await session.scalar(
        select(func.max(SessionEvent.sequence)).where(SessionEvent.session_id == session_id)
    )
    return (current or 0) + 1


def _to_row(event: RuntimeEvent, *, workspace_id: UUID, sequence: int) -> SessionEvent:
    return SessionEvent(
        id=event.event_id,
        workspace_id=workspace_id,
        session_id=event.session_id,
        run_id=event.run_id,
        sequence=sequence,
        event_type=event.type,
        # 落库前脱敏（C56/C57）。放在这里是刻意的：只要还有人用 append 写入，
        # 就不可能绕过脱敏；如果放在调用方，漏一处就是密钥进库。
        payload=get_scrubber().scrub_payload(event.payload),
        visibility=event.visibility,
    )


async def append(session: AsyncSession, event: RuntimeEvent) -> SessionEvent:
    """事务内追加一条事件；返回落库的行。

    幂等：同一 `event_id` 再次调用返回已有行。注意**不会**因为重复而推进序号——
    否则重试会让序号出现空洞，补偿查询就得处理"序号跳号但事件不存在"。
    """
    existing = await session.get(SessionEvent, event.event_id)
    if existing is not None:
        return existing

    locked = await _lock_session(session, event.session_id)
    sequence = await _next_sequence(session, event.session_id)
    row = _to_row(event, workspace_id=locked.workspace_id, sequence=sequence)

    try:
        # SAVEPOINT 包住写入：唯一约束被触发时只回滚这一段，外层事务仍可用。
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        # 并发下另一个请求先占了这个序号，或者同一 event_id 被同时写入。
        existing = await session.get(SessionEvent, event.event_id)
        if existing is not None:
            return existing
        raise EventStoreError("sequence_conflict", "事件序号冲突") from None

    # 追加事件会改变会话的更新时间，会话列表按它排序（C7）。
    locked.updated_at = row.created_at
    return row


async def list_after(
    session: AsyncSession,
    session_id: UUID,
    after_sequence: int = 0,
    *,
    limit: int = DEFAULT_BATCH,
) -> list[SessionEvent]:
    """按序号取缺失的事件，升序。这是断线补偿的唯一入口。"""
    if not isinstance(after_sequence, int) or after_sequence < 0:
        raise EventStoreError("invalid_sequence", "after_sequence 必须是非负整数")
    bounded = max(1, min(int(limit), MAX_BATCH))
    rows = await session.scalars(
        select(SessionEvent)
        .where(
            SessionEvent.session_id == session_id,
            SessionEvent.sequence > after_sequence,
        )
        .order_by(SessionEvent.sequence)
        .limit(bounded)
    )
    return list(rows.all())


async def latest_sequence(session: AsyncSession, session_id: UUID) -> int:
    """会话当前的最大序号；空会话返回 0。"""
    current = await session.scalar(
        select(func.max(SessionEvent.sequence)).where(SessionEvent.session_id == session_id)
    )
    return current or 0
