"""CRM leads with an activity timeline; Kylas sync (outbox, poll cursors, company settings,
users.kylas_user_id); leads.view / leads.edit (sales: own; office_admin and super_admin: all).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kylas_cursors",
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_kylas_cursors")),
    )
    op.create_table(
        "lead_sequences",
        sa.Column("year", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("year", name=op.f("pk_lead_sequences")),
    )
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("contact_name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("lead_source", sa.String(length=12), server_default="other", nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("requirement", sa.Text(), nullable=True),
        sa.Column("system_id", sa.Integer(), nullable=True),
        sa.Column("work_category_id", sa.Integer(), nullable=True),
        sa.Column("est_area_sqm", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("est_value", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="new", nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("next_follow_up", sa.Date(), nullable=True),
        sa.Column("tender_id", sa.Integer(), nullable=True),
        sa.Column("kylas_lead_id", sa.BigInteger(), nullable=True),
        sa.Column("kylas_owner_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "kylas_sync_status", sa.String(length=10), server_default="disabled", nullable=False
        ),
        sa.Column("kylas_last_error", sa.Text(), nullable=True),
        sa.Column("kylas_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kylas_forecasting", sa.String(length=30), nullable=True),
        sa.Column("kylas_converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kylas_deal_id", sa.BigInteger(), nullable=True),
        sa.Column("kylas_won_at", sa.DateTime(timezone=True), nullable=True),
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
            "kylas_sync_status IN ('disabled', 'pending', 'synced', 'failed')",
            name=op.f("ck_leads_sync_status_valid"),
        ),
        sa.CheckConstraint(
            "lead_source IN ('website', 'call', 'referral', 'channel', 'walk_in', "
            "'exhibition', 'other')",
            name=op.f("ck_leads_source_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('new', 'contacted', 'site_visit', 'quoted', 'won', 'lost', 'junk')",
            name=op.f("ck_leads_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channels.id"],
            name=op.f("fk_leads_channel_id_channels"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_leads_client_id_clients"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_leads_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_leads_owner_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_leads_system_id_systems"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_leads_tender_id_tenders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["work_category_id"],
            ["categories.id"],
            name=op.f("fk_leads_work_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
        sa.UniqueConstraint("code", name=op.f("uq_leads_code")),
        sa.UniqueConstraint("kylas_lead_id", name=op.f("uq_leads_kylas_lead_id")),
    )
    op.create_index(op.f("ix_leads_channel_id"), "leads", ["channel_id"], unique=False)
    op.create_index(op.f("ix_leads_client_id"), "leads", ["client_id"], unique=False)
    op.create_index(op.f("ix_leads_next_follow_up"), "leads", ["next_follow_up"], unique=False)
    op.create_index(op.f("ix_leads_owner_id"), "leads", ["owner_id"], unique=False)
    op.create_index(op.f("ix_leads_phone"), "leads", ["phone"], unique=False)
    op.create_index(op.f("ix_leads_status"), "leads", ["status"], unique=False)
    op.create_index(op.f("ix_leads_tender_id"), "leads", ["tender_id"], unique=False)
    op.create_table(
        "kylas_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('pending', 'unknown', 'done', 'failed')",
            name=op.f("ck_kylas_outbox_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_kylas_outbox_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kylas_outbox")),
    )
    op.create_index(op.f("ix_kylas_outbox_lead_id"), "kylas_outbox", ["lead_id"], unique=True)
    op.create_index(
        op.f("ix_kylas_outbox_next_attempt_at"), "kylas_outbox", ["next_attempt_at"], unique=False
    )
    op.create_index(op.f("ix_kylas_outbox_status"), "kylas_outbox", ["status"], unique=False)
    op.create_table(
        "lead_activities",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=15), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "type IN ('note', 'call', 'visit', 'status_change', 'kylas')",
            name=op.f("ck_lead_activities_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["by"], ["users.id"], name=op.f("fk_lead_activities_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_lead_activities_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_activities")),
    )
    op.create_index(
        op.f("ix_lead_activities_lead_id"), "lead_activities", ["lead_id"], unique=False
    )
    op.add_column("company_profile", sa.Column("kylas_source_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "company_profile",
        sa.Column(
            "kylas_owner_rule", sa.String(length=20), server_default="creator", nullable=False
        ),
    )
    op.add_column(
        "company_profile", sa.Column("kylas_default_owner_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "company_profile", sa.Column("kylas_deal_pipeline_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "company_profile", sa.Column("kylas_won_stage_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "company_profile",
        sa.Column(
            "kylas_lead_code_field",
            sa.String(length=60),
            server_default="cfInquiryType",
            nullable=False,
        ),
    )
    op.add_column(
        "company_profile",
        sa.Column(
            "kylas_category_field",
            sa.String(length=60),
            server_default="cfCustomerCategrory",
            nullable=False,
        ),
    )
    op.add_column(
        "company_profile",
        sa.Column(
            "kylas_junk_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='["Wrong number", "False enquiry", "Duplicate"]',
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("kylas_user_id", sa.BigInteger(), nullable=True))

    op.execute(
        "INSERT INTO permissions (code, module, description) VALUES "
        "('leads.view', 'crm', 'View CRM leads'), "
        "('leads.edit', 'crm', 'Create and edit CRM leads')"
    )
    for role, scope in (("super_admin", "all"), ("office_admin", "all"), ("sales", "own")):
        op.execute(
            "INSERT INTO role_permissions (role_id, permission_code, scope) "
            f"SELECT roles.id, p.code, '{scope}' FROM roles, "
            "(VALUES ('leads.view'), ('leads.edit')) "
            f"AS p(code) WHERE roles.code = '{role}' ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE code IN ('leads.view', 'leads.edit')")
    op.drop_column("users", "kylas_user_id")
    op.drop_column("company_profile", "kylas_junk_reasons")
    op.drop_column("company_profile", "kylas_category_field")
    op.drop_column("company_profile", "kylas_lead_code_field")
    op.drop_column("company_profile", "kylas_won_stage_id")
    op.drop_column("company_profile", "kylas_deal_pipeline_id")
    op.drop_column("company_profile", "kylas_default_owner_id")
    op.drop_column("company_profile", "kylas_owner_rule")
    op.drop_column("company_profile", "kylas_source_id")
    op.drop_index(op.f("ix_lead_activities_lead_id"), table_name="lead_activities")
    op.drop_table("lead_activities")
    op.drop_index(op.f("ix_kylas_outbox_status"), table_name="kylas_outbox")
    op.drop_index(op.f("ix_kylas_outbox_next_attempt_at"), table_name="kylas_outbox")
    op.drop_index(op.f("ix_kylas_outbox_lead_id"), table_name="kylas_outbox")
    op.drop_table("kylas_outbox")
    op.drop_index(op.f("ix_leads_tender_id"), table_name="leads")
    op.drop_index(op.f("ix_leads_status"), table_name="leads")
    op.drop_index(op.f("ix_leads_phone"), table_name="leads")
    op.drop_index(op.f("ix_leads_owner_id"), table_name="leads")
    op.drop_index(op.f("ix_leads_next_follow_up"), table_name="leads")
    op.drop_index(op.f("ix_leads_client_id"), table_name="leads")
    op.drop_index(op.f("ix_leads_channel_id"), table_name="leads")
    op.drop_table("leads")
    op.drop_table("lead_sequences")
    op.drop_table("kylas_cursors")
