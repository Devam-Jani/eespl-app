# ruff: noqa: E501
"""Account emails in the outbox (Prompt 39, Part 5): the invite when a user is created, its resend,
and the forgotten-password link. A row is for a person (user_id, kind) instead of a notification;
the link itself is never stored: the worker makes a fresh single-use link when it sends.

Revision ID: 0057m
Revises: 0056e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057m"
down_revision: str | None = "0056e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("notification_outbox", "notification_id", nullable=True, existing_type=sa.Integer())
    op.add_column("notification_outbox", sa.Column("kind", sa.String(10)))
    op.add_column("notification_outbox", sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True))
    op.add_column("notification_outbox", sa.Column("by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("notification_outbox", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_check_constraint(op.f("ck_notification_outbox_kind_valid"), "notification_outbox", "kind IS NULL OR kind IN ('invite', 'reset')")
    op.create_check_constraint(
        op.f("ck_notification_outbox_for_someone"), "notification_outbox", "notification_id IS NOT NULL OR (kind IS NOT NULL AND user_id IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notification_outbox WHERE notification_id IS NULL")
    op.drop_constraint(op.f("ck_notification_outbox_for_someone"), "notification_outbox", type_="check")
    op.drop_constraint(op.f("ck_notification_outbox_kind_valid"), "notification_outbox", type_="check")
    for col in ("created_at", "by_user_id", "user_id", "kind"):
        op.drop_column("notification_outbox", col)
    op.alter_column("notification_outbox", "notification_id", nullable=False, existing_type=sa.Integer())
