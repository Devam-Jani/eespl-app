"""sites: structure tree, members, stage templates (seeded), area scopes, tasks, drawings;
drawings.approve; site permissions for the client role are withdrawn until the portal (M6).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_sequences",
        sa.Column("year", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("year", name=op.f("pk_site_sequences")),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("tender_id", sa.Integer(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("lng", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="planned", nullable=False),
        sa.Column("site_incharge_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=10), server_default="app", nullable=False),
        sa.Column("source_ref", sa.String(length=50), nullable=True),
        sa.Column(
            "progress_percent", sa.Numeric(precision=6, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("source IN ('app', 'powerplay')", name=op.f("ck_sites_source_valid")),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'on_hold', 'completed', 'closed')",
            name=op.f("ck_sites_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channels.id"],
            name=op.f("fk_sites_channel_id_channels"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_sites_client_id_clients"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_sites_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["site_incharge_id"],
            ["users.id"],
            name=op.f("fk_sites_site_incharge_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_sites_tender_id_tenders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sites")),
        sa.UniqueConstraint("code", name=op.f("uq_sites_code")),
        sa.UniqueConstraint("source_ref", name=op.f("uq_sites_source_ref")),
        sa.UniqueConstraint("tender_id", name=op.f("uq_sites_tender_id")),
    )
    op.create_index(op.f("ix_sites_channel_id"), "sites", ["channel_id"], unique=False)
    op.create_index(op.f("ix_sites_client_id"), "sites", ["client_id"], unique=False)
    op.create_index(op.f("ix_sites_site_incharge_id"), "sites", ["site_incharge_id"], unique=False)
    op.create_index(op.f("ix_sites_status"), "sites", ["status"], unique=False)
    op.create_table(
        "stage_templates",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("system_id", sa.Integer(), nullable=True),
        sa.Column("work_category_id", sa.Integer(), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_stage_templates_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_stage_templates_system_id_systems"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["work_category_id"],
            ["categories.id"],
            name=op.f("fk_stage_templates_work_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage_templates")),
        sa.UniqueConstraint("name", name=op.f("uq_stage_templates_name")),
    )
    op.create_table(
        "site_members",
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role_on_site", sa.String(length=12), server_default="viewer", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "role_on_site IN ('incharge', 'supervisor', 'sales', 'office', 'viewer')",
            name=op.f("ck_site_members_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_site_members_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name=op.f("fk_site_members_site_id_sites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_site_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("site_id", "user_id", name=op.f("pk_site_members")),
    )
    op.create_index(op.f("ix_site_members_user_id"), "site_members", ["user_id"], unique=False)
    op.create_table(
        "site_nodes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("level_no", sa.Integer(), nullable=True),
        sa.Column("area_sqm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "progress_percent", sa.Numeric(precision=6, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('tower', 'wing', 'basement', 'floor', 'flat', 'toilet', "
            "'kitchen', 'balcony', 'terrace', 'podium', 'lift_pit', 'ug_tank', "
            "'oh_tank', 'retaining_wall', 'raft', 'stp', 'swimming_pool', 'other')",
            name=op.f("ck_site_nodes_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_site_nodes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["site_nodes.id"],
            name=op.f("fk_site_nodes_parent_id_site_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_site_nodes_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_nodes")),
    )
    op.create_index(
        "ix_site_nodes_site_parent",
        "site_nodes",
        ["site_id", "parent_id", "sort_order"],
        unique=False,
    )
    op.create_table(
        "stage_template_steps",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("weight_percent", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("needs_photo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("needs_inspection", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("hold_point", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("typical_days", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "weight_percent >= 0 AND weight_percent <= 100",
            name=op.f("ck_stage_template_steps_weight_range"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_stage_template_steps_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["stage_templates.id"],
            name=op.f("fk_stage_template_steps_template_id_stage_templates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage_template_steps")),
    )
    op.create_index(
        op.f("ix_stage_template_steps_template_id"),
        "stage_template_steps",
        ["template_id"],
        unique=False,
    )
    op.create_table(
        "area_scopes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("boq_line_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_template_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column(
            "progress_percent", sa.Numeric(precision=6, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["boq_line_id"],
            ["boq_lines.id"],
            name=op.f("fk_area_scopes_boq_line_id_boq_lines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_area_scopes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["site_nodes.id"],
            name=op.f("fk_area_scopes_node_id_site_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_area_scopes_site_id_sites"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stage_template_id"],
            ["stage_templates.id"],
            name=op.f("fk_area_scopes_stage_template_id_stage_templates"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_area_scopes")),
    )
    op.create_index(
        op.f("ix_area_scopes_boq_line_id"), "area_scopes", ["boq_line_id"], unique=False
    )
    op.create_index(op.f("ix_area_scopes_node_id"), "area_scopes", ["node_id"], unique=False)
    op.create_index(op.f("ix_area_scopes_site_id"), "area_scopes", ["site_id"], unique=False)
    op.create_table(
        "drawings",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "discipline", sa.String(length=15), server_default="waterproofing", nullable=False
        ),
        sa.Column("current_revision_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "discipline IN ('architectural', 'structural', 'waterproofing', 'other')",
            name=op.f("ck_drawings_discipline_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_drawings_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["site_nodes.id"],
            name=op.f("fk_drawings_node_id_site_nodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_drawings_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drawings")),
    )
    op.create_index(op.f("ix_drawings_site_id"), "drawings", ["site_id"], unique=False)
    op.create_table(
        "drawing_revisions",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("drawing_id", sa.Integer(), nullable=False),
        sa.Column("rev_no", sa.Integer(), nullable=False),
        sa.Column("stored_path", sa.String(length=400), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="draft", nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected')",
            name=op.f("ck_drawing_revisions_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_drawing_revisions_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_drawing_revisions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["drawing_id"],
            ["drawings.id"],
            name=op.f("fk_drawing_revisions_drawing_id_drawings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_drawing_revisions_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drawing_revisions")),
        sa.UniqueConstraint("drawing_id", "rev_no", name=op.f("uq_drawing_revisions_drawing_id")),
    )
    op.create_foreign_key(
        op.f("fk_drawings_current_revision_id_drawing_revisions"),
        "drawings",
        "drawing_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_drawing_revisions_drawing_id"), "drawing_revisions", ["drawing_id"], unique=False
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("area_scope_id", sa.BigInteger(), nullable=True),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("planned_start", sa.Date(), nullable=True),
        sa.Column("planned_end", sa.Date(), nullable=True),
        sa.Column("actual_start", sa.Date(), nullable=True),
        sa.Column("actual_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="not_started", nullable=False),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column(
            "progress_percent", sa.Numeric(precision=6, scale=2), server_default="0", nullable=False
        ),
        sa.Column("parent_task_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "depends_on", postgresql.ARRAY(sa.BigInteger()), server_default="{}", nullable=False
        ),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("inspection", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("certified_by", sa.UUID(), nullable=True),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "status IN ('not_started', 'in_progress', 'done', 'certified', 'blocked')",
            name=op.f("ck_tasks_status_valid"),
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name=op.f("ck_tasks_progress")
        ),
        sa.ForeignKeyConstraint(
            ["area_scope_id"],
            ["area_scopes.id"],
            name=op.f("fk_tasks_area_scope_id_area_scopes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_tasks_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["certified_by"],
            ["users.id"],
            name=op.f("fk_tasks_certified_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_tasks_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["site_nodes.id"],
            name=op.f("fk_tasks_node_id_site_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_task_id"],
            ["tasks.id"],
            name=op.f("fk_tasks_parent_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_tasks_site_id_sites"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["stage_template_steps.id"],
            name=op.f("fk_tasks_step_id_stage_template_steps"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_area_scope_id"), "tasks", ["area_scope_id"], unique=False)
    op.create_index(op.f("ix_tasks_assignee_id"), "tasks", ["assignee_id"], unique=False)
    op.create_index(op.f("ix_tasks_node_id"), "tasks", ["node_id"], unique=False)
    op.create_index(op.f("ix_tasks_parent_task_id"), "tasks", ["parent_task_id"], unique=False)
    op.create_index(op.f("ix_tasks_site_id"), "tasks", ["site_id"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)
    op.create_index(
        "uq_tasks_scope_step",
        "tasks",
        ["area_scope_id", "step_id"],
        unique=True,
        postgresql_where="parent_task_id IS NULL",
    )
    op.create_table(
        "task_photos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("stored_path", sa.String(length=400), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_task_photos_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_photos_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_photos")),
    )
    op.create_index(op.f("ix_task_photos_task_id"), "task_photos", ["task_id"], unique=False)

    _seed_permissions()
    _seed_templates()


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE code = 'drawings.approve'")
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_code, scope) "
        "SELECT id, 'site.view', 'assigned' FROM roles WHERE code = 'client' "
        "ON CONFLICT DO NOTHING"
    )
    op.drop_constraint(
        op.f("fk_drawings_current_revision_id_drawing_revisions"), "drawings", type_="foreignkey"
    )
    op.drop_index(op.f("ix_task_photos_task_id"), table_name="task_photos")
    op.drop_table("task_photos")
    op.drop_index(
        "uq_tasks_scope_step", table_name="tasks", postgresql_where="parent_task_id IS NULL"
    )
    op.drop_index(op.f("ix_tasks_status"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_site_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_parent_task_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_node_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_assignee_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_area_scope_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_drawing_revisions_drawing_id"), table_name="drawing_revisions")
    op.drop_table("drawing_revisions")
    op.drop_index(op.f("ix_drawings_site_id"), table_name="drawings")
    op.drop_table("drawings")
    op.drop_index(op.f("ix_area_scopes_site_id"), table_name="area_scopes")
    op.drop_index(op.f("ix_area_scopes_node_id"), table_name="area_scopes")
    op.drop_index(op.f("ix_area_scopes_boq_line_id"), table_name="area_scopes")
    op.drop_table("area_scopes")
    op.drop_index(op.f("ix_stage_template_steps_template_id"), table_name="stage_template_steps")
    op.drop_table("stage_template_steps")
    op.drop_index("ix_site_nodes_site_parent", table_name="site_nodes")
    op.drop_table("site_nodes")
    op.drop_index(op.f("ix_site_members_user_id"), table_name="site_members")
    op.drop_table("site_members")
    op.drop_table("stage_templates")
    op.drop_index(op.f("ix_sites_status"), table_name="sites")
    op.drop_index(op.f("ix_sites_site_incharge_id"), table_name="sites")
    op.drop_index(op.f("ix_sites_client_id"), table_name="sites")
    op.drop_index(op.f("ix_sites_channel_id"), table_name="sites")
    op.drop_table("sites")
    op.drop_table("site_sequences")


# --- permissions ---------------------------------------------------------------------------------


def _seed_permissions() -> None:
    op.execute(
        "INSERT INTO permissions (code, module, description) VALUES "
        "('drawings.approve', 'site', 'Approve or reject drawing revisions')"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_code, scope) "
        "SELECT id, 'drawings.approve', 'all' FROM roles WHERE code IN ('super_admin', "
        "'office_admin') ON CONFLICT DO NOTHING"
    )
    # sales sees the sites they are on; the estimator sees all; supervisors view and update
    # their assigned sites (already so since M0, kept explicit here)
    grants = (("sales", "site.view", "assigned"), ("estimator", "site.view", "all"),
              ("site_supervisor", "site.view", "assigned"),
              ("site_supervisor", "site.update", "assigned"))  # fmt: skip
    for role, code, scope in grants:
        op.execute(
            "INSERT INTO role_permissions (role_id, permission_code, scope) "
            f"SELECT id, '{code}', '{scope}' FROM roles WHERE code = '{role}' "
            f"ON CONFLICT (role_id, permission_code) DO UPDATE SET scope = '{scope}'"
        )
    # the client portal comes in M6; until then clients get no site access at all
    op.execute(
        "DELETE FROM role_permissions WHERE permission_code LIKE 'site.%' AND role_id IN "
        "(SELECT id FROM roles WHERE code = 'client')"
    )


# --- stage templates -----------------------------------------------------------------------------

# (name, work category, system name pattern, keywords, steps: (name, weight, flags, days))
# flags: H = hold point (office certifies before the next step), I = inspection checklist
TEMPLATES = [
    ("Toilet / wet area (coating)", "Toilets & wet areas", "%toilet%",
     "toilet wet bath sunk kitchen balcony utility coating cementitious", [
        ("Surface prep & cleaning", 10, "", 1), ("Crack & joint filling, coving", 10, "", 1),
        ("Pipe sleeve packing", 10, "", 1), ("Primer", 5, "", 1), ("Coat 1", 15, "", 1),
        ("Fibre mesh", 10, "", 1), ("Coat 2", 15, "", 1), ("Ponding test 48 h", 15, "HI", 2),
        ("Protection screed / plaster", 10, "", 2)]),
    ("Terrace (APP membrane)", "Terrace", "%APP%",
     "terrace app membrane torch bitumen roof", [
        ("Surface prep", 10, "", 1), ("Coving / fillet", 10, "", 1), ("Primer", 10, "", 1),
        ("Membrane laying by torch", 30, "", 3), ("Ponding test", 15, "HI", 2),
        ("Protection screed", 20, "", 2), ("Handover", 5, "", 1)]),
    ("Terrace / podium (PU coating)", "Terrace", "%PU%",
     "terrace podium pu polyurethane elastomeric liquid applied", [
        ("Surface prep", 10, "", 1), ("Crack filling & coving", 10, "", 1), ("Primer", 10, "", 1),
        ("PU coat 1", 20, "", 1), ("PU coat 2", 20, "", 1), ("DFT check", 5, "I", 1),
        ("Ponding test", 15, "HI", 2), ("Geotextile / protection", 10, "", 1)]),
    ("Podium / terrace garden", "Podium / garden", "%garden%",
     "podium garden planter landscape drain board geotextile", [
        ("Surface prep", 10, "", 1), ("Primer", 5, "", 1), ("Membrane / PU", 25, "", 3),
        ("Flood test", 15, "HI", 2), ("Geotextile", 10, "", 1), ("Drain board", 15, "", 1),
        ("Filter geotextile", 10, "", 1), ("Protection screed", 10, "", 2)]),
    ("Basement raft (crystalline)", "Raft / basement", "%raft%",
     "raft basement pcc crystalline dry shake foundation", [
        ("PCC surface prep", 15, "", 1), ("Crystalline dry-shake / slurry", 35, "", 1),
        ("Construction joint swell bar", 20, "", 1), ("Inspection before casting", 15, "HI", 1),
        ("Curing", 15, "", 7)]),
    ("Retaining wall (crystalline)", "Retaining wall", "%retaining%",
     "retaining wall crystalline slurry tie hole", [
        ("Surface prep & tie-hole plugging", 20, "", 2), ("Slurry coat 1", 25, "", 1),
        ("Slurry coat 2", 25, "", 1), ("Construction joint treatment", 15, "", 1),
        ("Curing & inspection", 15, "I", 3)]),
    ("Water tank (UG / OH)", "Water tanks (UG/OH)", "%tank%",
     "water tank ug oh sump overhead underground hygiene potable", [
        ("Surface prep", 15, "", 1), ("Crystalline / coating coat 1", 20, "", 1),
        ("Coat 2", 20, "", 1), ("Hygiene coat", 15, "", 1), ("Water test 72 h", 20, "HI", 3),
        ("Handover", 10, "", 1)]),
    ("Brick bat coba", None, "%brick bat%",
     "brick bat coba bbc slope", [
        ("Surface prep", 10, "", 1), ("Slope marking", 5, "", 1),
        ("Brick bat laying with mortar", 45, "", 3), ("Top mortar & finishing", 20, "", 2),
        ("Ponding test", 15, "HI", 2), ("Handover", 5, "", 1)]),
    ("Injection grouting", "Injection grouting", "%inject%",
     "injection grouting grout nozzle leakage crack pu injection", [
        ("Drilling", 25, "", 1), ("Nozzle fixing", 20, "", 1), ("Injection", 35, "", 1),
        ("Nozzle cutting & sealing", 10, "", 1), ("Leak check", 10, "I", 1)]),
    ("Expansion joint", "Expansion joints", "%expansion%",
     "expansion joint sealant backer rod profile", [
        ("Cleaning", 15, "", 1), ("Backer rod", 20, "", 1), ("Primer", 10, "", 1),
        ("Sealant / profile fixing", 45, "", 1), ("Inspection", 10, "I", 1)]),
]  # fmt: skip


def _seed_templates() -> None:
    conn = op.get_bind()
    for name, category, system_like, keywords, steps in TEMPLATES:
        assert sum(w for _, w, _, _ in steps) == 100, name
        template_id = conn.execute(
            sa.text(
                "INSERT INTO stage_templates (name, work_category_id, system_id, keywords) "
                "VALUES (:name, (SELECT id FROM categories WHERE kind = 'work' AND name = :cat "
                "LIMIT 1), (SELECT id FROM systems WHERE name ILIKE :sys ORDER BY id LIMIT 1), "
                ":kw) RETURNING id"
            ),
            {"name": name, "cat": category, "sys": system_like, "kw": keywords},
        ).scalar_one()
        for order, (step, weight, flags, days) in enumerate(steps, start=1):
            conn.execute(
                sa.text(
                    "INSERT INTO stage_template_steps (template_id, sort_order, name, "
                    "weight_percent, needs_photo, needs_inspection, hold_point, typical_days) "
                    "VALUES (:t, :o, :n, :w, true, :i, :h, :d)"
                ),
                {"t": template_id, "o": order, "n": step, "w": weight, "i": "I" in flags,
                 "h": "H" in flags, "d": days},
            )  # fmt: skip
