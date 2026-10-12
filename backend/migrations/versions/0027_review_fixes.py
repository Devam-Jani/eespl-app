"""Site control review fixes: product aliases (seeded with the Bronco hybrid PU pair), the place
on each daily report line, and the director role (who also releases blocked vendor bills).

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-10 11:20:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# the director sees and decides everything; users, roles and settings stay with office_admin,
# the client portal codes with clients
DIRECTOR_EXCLUDES = (
    "admin.users",
    "admin.roles",
    "admin.settings",
    "portal.view",
    "portal.comment",
    "portal.snag",
    "portal.approve",
)


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("aliases", postgresql.ARRAY(sa.String(200)), server_default="{}", nullable=False),
    )
    # the same product under two names in the bungalow offer (Deep Vyana): one product
    op.execute(
        "INSERT INTO products (code, name, brand, unit, aliases) VALUES "
        "('BRONCO-HYBRID-PU', 'BRONCO HYBRID PU', 'Bronco', 'kg', "
        "ARRAY['BRONCO CEMSHIELD HYBRID PU']) ON CONFLICT (code) DO NOTHING"
    )
    op.create_table(
        "dpr_lines",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("dpr_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("survey_area_id", sa.BigInteger(), nullable=True),
        sa.Column("new_area_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(14, 3), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("labour_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dpr_id"], ["dprs.id"], name=op.f("fk_dpr_lines_dpr_id_dprs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["site_nodes.id"],
            name=op.f("fk_dpr_lines_node_id_site_nodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["survey_area_id"],
            ["survey_areas.id"],
            name=op.f("fk_dpr_lines_survey_area_id_survey_areas"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["new_area_id"],
            ["new_area_requests.id"],
            name=op.f("fk_dpr_lines_new_area_id_new_area_requests"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dpr_lines")),
    )
    op.create_index(op.f("ix_dpr_lines_dpr_id"), "dpr_lines", ["dpr_id"])
    op.create_index(op.f("ix_dpr_lines_node_id"), "dpr_lines", ["node_id"])
    op.create_index(op.f("ix_dpr_lines_new_area_id"), "dpr_lines", ["new_area_id"])
    op.execute(
        "INSERT INTO roles (code, name, description, is_system) VALUES ('director', 'Director', "
        "'Sees everything including costs and margins; decides who handles a won job; approves "
        "overrides (labour check, rates above contract, blocked bills).', true)"
    )
    excludes = ", ".join(f"'{c}'" for c in DIRECTOR_EXCLUDES)
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_code, scope) "
        "SELECT r.id, p.code, 'all' FROM roles r, permissions p "
        f"WHERE r.code = 'director' AND p.code NOT IN ({excludes})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM roles WHERE code = 'director'")
    op.drop_table("dpr_lines")
    op.execute("DELETE FROM products WHERE code = 'BRONCO-HYBRID-PU'")
    op.drop_column("products", "aliases")
