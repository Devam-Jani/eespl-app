# ruff: noqa: E501
"""The issue log book (issues, issue_events, helper_answers) and its permissions: issuelog.view and
issuelog.edit for the director, the office admin and the super admin.

Revision ID: 0048
Revises: 0047
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMS = (("issuelog.view", "See the issue log book"), ("issuelog.edit", "Mark issues in the log book: cause, fix, pull request, status"))


def upgrade() -> None:
    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="new", nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("page", sa.String(length=200), nullable=True),
        sa.Column("roles", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("found_by", sa.String(length=20), server_default="user", nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("cause", sa.Text(), nullable=True),
        sa.Column("fix", sa.Text(), nullable=True),
        sa.Column("pr_url", sa.String(length=300), nullable=True),
        sa.Column("commit", sa.String(length=40), nullable=True),
        sa.Column("fixed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_role", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issues")),
        sa.UniqueConstraint("fingerprint", name=op.f("uq_issues_fingerprint")),
    )
    op.create_index(op.f("ix_issues_status"), "issues", ["status"], unique=False)
    op.create_index(op.f("ix_issues_last_seen"), "issues", ["last_seen"], unique=False)
    op.create_table(
        "issue_events",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=True),
        sa.Column("client", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("page", sa.String(length=300), nullable=True),
        sa.Column("action", sa.String(length=300), nullable=True),
        sa.Column("request_id", sa.String(length=40), nullable=True),
        sa.Column("browser", sa.String(length=200), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("words", sa.Text(), nullable=True),
        sa.Column("values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("found_by", sa.String(length=20), server_default="user", nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], name=op.f("fk_issue_events_issue_id_issues"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_issue_events_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_events")),
    )
    op.create_index(op.f("ix_issue_events_issue_id"), "issue_events", ["issue_id"], unique=False)
    op.create_index(op.f("ix_issue_events_user_id"), "issue_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_issue_events_request_id"), "issue_events", ["request_id"], unique=False)
    op.create_table(
        "helper_answers",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], name=op.f("fk_helper_answers_issue_id_issues"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_helper_answers_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_helper_answers")),
    )
    op.create_index(op.f("ix_helper_answers_issue_id"), "helper_answers", ["issue_id"], unique=False)
    for code, desc in PERMS:
        op.execute(f"INSERT INTO permissions (code, module, description) VALUES ('{code}', 'admin', '{desc}')")
        for role in ("director", "office_admin", "super_admin"):
            op.execute(f"INSERT INTO role_permissions (role_id, permission_code, scope) SELECT id, '{code}', 'all' FROM roles WHERE code = '{role}'")


def downgrade() -> None:
    for code, _ in PERMS:
        op.execute(f"DELETE FROM role_permissions WHERE permission_code = '{code}'")
        op.execute(f"DELETE FROM permissions WHERE code = '{code}'")
    op.drop_table("helper_answers")
    op.drop_table("issue_events")
    op.drop_index(op.f("ix_issues_last_seen"), table_name="issues")
    op.drop_index(op.f("ix_issues_status"), table_name="issues")
    op.drop_table("issues")
