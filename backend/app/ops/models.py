# ruff: noqa: E501
"""What the background jobs report about themselves: the worker's heartbeat, the last backup (its
time, archive, size, where it was copied) and the training company's last reset. One row per key,
written by the job, read by the health page and the admin's backup page."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class HelpText(Base):
    """The "?" on a page: a short how-to (3 to 6 steps) for the page, for everyone ("") or one
    role; the office admin edits them (Settings > Help)."""

    __tablename__ = "help_texts"
    __table_args__ = (UniqueConstraint("page", "role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page: Mapped[str] = mapped_column(String(80))  # the route, e.g. /bills or /sites/:id
    role: Mapped[str] = mapped_column(String(40), server_default="")  # a role code, "" for all
    title: Mapped[str] = mapped_column(String(200))
    steps: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    updated_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SystemStatus(Base):
    __tablename__ = "system_status"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)  # worker, backup, training
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
