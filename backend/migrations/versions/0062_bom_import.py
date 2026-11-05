# ruff: noqa: E501  (the column lists read better unwrapped)
"""The company BOM (Prompt 38e): a system's brand options (one recipe per brand of the same work
item), each component's option, where its figure came from (the company BOM, with the figure and
unit as the file gave them) and whether the figure already includes wastage (sheets and mesh with
their overlap); the brand option picked by a rate working's main item, an offer line, a quotation
line and an estimate line; a main item worked per rmt; bom.import for the super admin and
planning.

The downgrade drops the options with their components (a system keeps the components that
belonged to no option) and puts every main item back to per sqm.

Revision ID: 0062e
Revises: 0061d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062e"
down_revision: str | None = "0061d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE = "bom.import"
ROLES = ("super_admin", "planning")
PICKS = ("rate_groups", "offer_lines", "quotation_lines", "estimate_lines")


def upgrade() -> None:
    op.create_table(
        "system_options",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("system_id", sa.Integer(), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("source IN ('company_bom', 'manual')", name=op.f("ck_system_options_source_valid")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_system_options_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], name=op.f("fk_system_options_system_id_systems"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_options")),
        sa.UniqueConstraint("system_id", "brand", name=op.f("uq_system_options_system_id")),
    )  # fmt: skip
    op.create_index("ix_system_options_system_id", "system_options", ["system_id"])
    op.create_index(
        "ux_system_options_default", "system_options", ["system_id"], unique=True,
        postgresql_where=sa.text("is_default"),
    )  # fmt: skip

    op.add_column("systems", sa.Column("source", sa.String(length=16), nullable=True))
    op.add_column("system_components", sa.Column("option_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_system_components_option_id_system_options"), "system_components",
        "system_options", ["option_id"], ["id"], ondelete="CASCADE",
    )  # fmt: skip
    op.create_index("ix_system_components_option_id", "system_components", ["option_id"])
    op.add_column("system_components", sa.Column("source", sa.String(length=16), nullable=True))
    op.add_column(
        "system_components",
        sa.Column("wastage_included", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "system_components", sa.Column("original_consumption", sa.Numeric(14, 6), nullable=True)
    )
    op.add_column("system_components", sa.Column("original_unit", sa.String(length=10), nullable=True))
    op.add_column("system_components", sa.Column("original_ref", sa.Text(), nullable=True))

    for table in PICKS:
        op.add_column(table, sa.Column("system_option_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_system_option_id_system_options"), table, "system_options",
            ["system_option_id"], ["id"], ondelete="SET NULL",
        )  # fmt: skip
    op.add_column("rate_groups", sa.Column("unit", sa.String(length=6), server_default="sqm", nullable=False))
    op.create_check_constraint(op.f("ck_rate_groups_unit_valid"), "rate_groups", "unit IN ('sqm', 'rmt')")
    op.add_column(
        "rate_group_products",
        sa.Column("wastage_included", sa.Boolean(), server_default="false", nullable=False),
    )

    op.execute(
        f"INSERT INTO permissions (code, module, description) VALUES ('{CODE}', 'masters', "
        "'Import the company BOM: work items, their brand options and consumption')"
    )
    for role in ROLES:
        op.execute(
            "INSERT INTO role_permissions (role_id, permission_code, scope) "
            f"SELECT id, '{CODE}', 'all' FROM roles WHERE code = '{role}'"
        )


def downgrade() -> None:
    op.execute(f"DELETE FROM role_permissions WHERE permission_code = '{CODE}'")
    op.execute(f"DELETE FROM permissions WHERE code = '{CODE}'")
    op.drop_column("rate_group_products", "wastage_included")
    op.drop_constraint(op.f("ck_rate_groups_unit_valid"), "rate_groups", type_="check")
    op.drop_column("rate_groups", "unit")
    for table in PICKS:
        op.drop_constraint(op.f(f"fk_{table}_system_option_id_system_options"), table, type_="foreignkey")
        op.drop_column(table, "system_option_id")
    op.execute("DELETE FROM system_components WHERE option_id IS NOT NULL")
    for col in ("original_ref", "original_unit", "original_consumption", "wastage_included", "source"):
        op.drop_column("system_components", col)
    op.drop_index("ix_system_components_option_id", table_name="system_components")
    op.drop_constraint(op.f("fk_system_components_option_id_system_options"), "system_components", type_="foreignkey")
    op.drop_column("system_components", "option_id")
    op.drop_column("systems", "source")
    op.drop_index("ux_system_options_default", table_name="system_options")
    op.drop_index("ix_system_options_system_id", table_name="system_options")
    op.drop_table("system_options")
