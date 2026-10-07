"""channels master; the rate library's folders become channels (not clients); tenders get a
channel and an optional client; PDF import fields on BOQ lines.

Data moves:
- every distinct library_lines.client_folder becomes a channel (type "other"), and the column
  is renamed to `channel` with `channel_id` pointing at the master;
- library_items.latest_client is renamed latest_channel;
- the rate policies "client_last" / "client_median" become "channel_last" / "channel_median"
  (company setting and stored candidate details).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_RENAMES = (("client_last", "channel_last"), ("client_median", "channel_median"))


def _rename_policies(pairs) -> None:
    for old, new in pairs:
        op.execute(f"UPDATE company_profile SET rate_policy = '{new}' WHERE rate_policy = '{old}'")
        for key in ("policy", "used"):
            op.execute(
                f"UPDATE boq_line_candidates SET details = jsonb_set(details, '{{{key}}}', "
                f"'\"{new}\"') WHERE details->>'{key}' = '{old}'"
            )


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=20), server_default="other", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "type IN ('salesperson', 'partner', 'manufacturer', 'other')",
            name=op.f("ck_channels_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_channels_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channels")),
        sa.UniqueConstraint("name", name=op.f("uq_channels_name")),
    )

    # the library: folder -> channel
    op.alter_column("library_lines", "client_folder", new_column_name="channel")
    op.alter_column("library_items", "latest_client", new_column_name="latest_channel")
    op.add_column("library_lines", sa.Column("channel_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_library_lines_channel_id"), "library_lines", ["channel_id"])
    op.create_foreign_key(
        op.f("fk_library_lines_channel_id_channels"),
        "library_lines",
        "channels",
        ["channel_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "INSERT INTO channels (name) SELECT DISTINCT channel FROM library_lines "
        "WHERE channel IS NOT NULL AND btrim(channel) <> '' ON CONFLICT (name) DO NOTHING"
    )
    op.execute(
        "UPDATE library_lines l SET channel_id = c.id FROM channels c WHERE c.name = l.channel"
    )

    # tenders: an end client and/or a channel
    op.add_column("tenders", sa.Column("channel_id", sa.Integer(), nullable=True))
    op.alter_column("tenders", "client_id", existing_type=sa.INTEGER(), nullable=True)
    op.create_index(op.f("ix_tenders_channel_id"), "tenders", ["channel_id"])
    op.create_foreign_key(
        op.f("fk_tenders_channel_id_channels"),
        "tenders",
        "channels",
        ["channel_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # rate policy names
    op.alter_column("company_profile", "rate_policy", server_default="channel_median")
    _rename_policies(POLICY_RENAMES)
    op.execute(
        "UPDATE boq_line_candidates SET details = (details - 'client_last_rate') || "
        "jsonb_build_object('channel_last_rate', details->'client_last_rate') "
        "WHERE details ? 'client_last_rate'"
    )

    # PDF imports
    op.add_column("boq_lines", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("boq_lines", sa.Column("source_page_to", sa.Integer(), nullable=True))
    op.add_column("boq_lines", sa.Column("client_material_rate", sa.Numeric(14, 2), nullable=True))
    op.add_column(
        "boq_lines", sa.Column("client_application_rate", sa.Numeric(14, 2), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("boq_lines", "client_application_rate")
    op.drop_column("boq_lines", "client_material_rate")
    op.drop_column("boq_lines", "source_page_to")
    op.drop_column("boq_lines", "source_page")
    op.execute(
        "UPDATE boq_line_candidates SET details = (details - 'channel_last_rate') || "
        "jsonb_build_object('client_last_rate', details->'channel_last_rate') "
        "WHERE details ? 'channel_last_rate'"
    )
    _rename_policies((new, old) for old, new in POLICY_RENAMES)
    op.alter_column("company_profile", "rate_policy", server_default="client_median")
    op.drop_constraint(op.f("fk_tenders_channel_id_channels"), "tenders", type_="foreignkey")
    op.drop_index(op.f("ix_tenders_channel_id"), table_name="tenders")
    missing = op.get_bind().scalar(sa.text("SELECT count(*) FROM tenders WHERE client_id IS NULL"))
    if missing:
        raise RuntimeError(
            f"{missing} tenders have a channel but no client; give them a client before "
            "downgrading (nothing is deleted)"
        )
    op.alter_column("tenders", "client_id", existing_type=sa.INTEGER(), nullable=False)
    op.drop_column("tenders", "channel_id")
    op.drop_constraint(
        op.f("fk_library_lines_channel_id_channels"), "library_lines", type_="foreignkey"
    )
    op.drop_index(op.f("ix_library_lines_channel_id"), table_name="library_lines")
    op.drop_column("library_lines", "channel_id")
    op.alter_column("library_items", "latest_channel", new_column_name="latest_client")
    op.alter_column("library_lines", "channel", new_column_name="client_folder")
    op.drop_table("channels")
