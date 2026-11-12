"""
SQLAlchemy declarative base and shared column mixins for PlantOps.

Every database table inherits from `Base`, and tables that track creation/update
times inherit from `TimestampMixin`.
"""

from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return current UTC timestamp (naive UTC for MySQL DATETIME compatibility)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models in PlantOps."""


class TimestampMixin:
    """Adds automatic created_at and updated_at audit timestamps to models."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False,
        comment="Timestamp when the record was created (UTC).",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        comment="Timestamp when the record was last updated (UTC).",
    )

