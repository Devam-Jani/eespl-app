# ruff: noqa: E501
"""The X-ray 3D: the building model of a site (floor types from the AutoCAD plans, heights,
columns, beams, cores), versioned per site, and building.edit (billing, planning, the office
admin, the director and the super admin on every site; the site engineer on their own sites).

Revision ID: 0046
Revises: 0045
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS = {"billing": "all", "planning": "all", "office_admin": "all", "director": "all", "super_admin": "all", "site_engineer": "assigned"}


def upgrade() -> None:
    op.create_table(
        "building_models",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cad_file_id", sa.Integer(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_by_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cad_file_id"], ["cad_files.id"], name=op.f("fk_building_models_cad_file_id_cad_files"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_building_models_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name=op.f("fk_building_models_site_id_sites"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_building_models")),
        sa.UniqueConstraint("site_id", "version", name=op.f("uq_building_models_site_id")),
    )
    op.create_index(op.f("ix_building_models_site_id"), "building_models", ["site_id"], unique=False)
    op.add_column("work_completions", sa.Column("image_3d_path", sa.String(length=400), nullable=True))
    op.execute("INSERT INTO permissions (code, module, description) VALUES ('building.edit', 'site', 'Build and edit the 3D building model from the drawing')")
    for role, scope in GRANTS.items():
        op.execute(f"INSERT INTO role_permissions (role_id, permission_code, scope) SELECT id, 'building.edit', '{scope}' FROM roles WHERE code = '{role}'")


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_code = 'building.edit'")
    op.execute("DELETE FROM permissions WHERE code = 'building.edit'")
    op.drop_column("work_completions", "image_3d_path")
    op.drop_index(op.f("ix_building_models_site_id"), table_name="building_models")
    op.drop_table("building_models")
