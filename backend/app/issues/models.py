# ruff: noqa: E501
"""The issue log book: every problem once (repeats of the same error grouped), each time it
happened, and what was done about it.

  issues         one row per problem: its kind (error, mistake, report, nightly), status (new,
                 guided, bug, fixing, fixed, wont_fix), where, the roles it happened to (never a
                 name in the summary), first and last seen, how often, the error, the cause and the
                 fix, the pull request and commit, when it was fixed and when that was released
  issue_events   each time: the role, the page, what the user was doing, the request id, the
                 browser, the stack (trimmed), the user's words; what they typed only when they
                 agreed; the user's id (an admin can open the user)
  helper_answers what the helper's AI said about it, kept with the issue"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

STATUSES = ("new", "guided", "bug", "fixing", "fixed", "wont_fix")
KINDS = ("error", "mistake", "report", "nightly")


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), server_default="new", index=True)
    title: Mapped[str] = mapped_column(String(300))
    page: Mapped[str | None] = mapped_column(String(200))
    roles: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    error: Mapped[str | None] = mapped_column(Text)
    stack: Mapped[str | None] = mapped_column(Text)  # the latest, trimmed
    status_code: Mapped[int | None] = mapped_column(Integer)
    found_by: Mapped[str] = mapped_column(String(20), server_default="user")  # user, server, nightly check
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    count: Mapped[int] = mapped_column(Integer, server_default="1")
    cause: Mapped[str | None] = mapped_column(Text)
    fix: Mapped[str | None] = mapped_column(Text)
    pr_url: Mapped[str | None] = mapped_column(String(300))
    commit: Mapped[str | None] = mapped_column(String(40))
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by_role: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IssueEvent(Base):
    __tablename__ = "issue_events"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    role: Mapped[str | None] = mapped_column(String(40))
    client: Mapped[bool] = mapped_column(Boolean, server_default="false")
    page: Mapped[str | None] = mapped_column(String(300))
    action: Mapped[str | None] = mapped_column(String(300))
    request_id: Mapped[str | None] = mapped_column(String(40), index=True)
    browser: Mapped[str | None] = mapped_column(String(200))
    status_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    stack: Mapped[str | None] = mapped_column(Text)
    words: Mapped[str | None] = mapped_column(Text)  # the user's own words ("Report this")
    values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # only when the user agreed
    found_by: Mapped[str] = mapped_column(String(20), server_default="user")


class HelperAnswer(Base):
    __tablename__ = "helper_answers"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    role: Mapped[str | None] = mapped_column(String(40))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(60))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
