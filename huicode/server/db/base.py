from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class IdentityMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


def as_utc(value: datetime) -> datetime:
    """把从数据库读出的时间统一成 aware UTC。

    PostgreSQL 的 TIMESTAMPTZ 会带回 tzinfo；SQLite 不保存 tzinfo，读出来是
    naive 的。拿 naive 值和 datetime.now(timezone.utc) 比较会抛
    TypeError: can't compare offset-naive and offset-aware datetimes。

    这个差异只在换数据库时暴露——开发用 SQLite 不报错，部署到 PostgreSQL 也
    不报错，唯独反过来会。所以统一放在这里，而不是散在各个比较点。
    写库时一律写 aware UTC，读库时一律过这个函数。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class CreatedAtMixin:
    """只写一次的行（事件、审计、用量）用它。

    这些表按"只追加"使用，再加 updated_at 会与这个前提矛盾。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )


class TimestampMixin:
    """会被改名或改状态的行（会话、Run）用它。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )
