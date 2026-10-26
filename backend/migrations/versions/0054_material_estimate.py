# ruff: noqa: E501
"""Material estimates from the measured drawing: the product consumption library (one coverage per
product per system, its min, max, unit and source document), wastage per product, the upturn per
system, mix designs, estimates with one area set and their material lines, the site's material
requests; the margin check's share (the director's) and a working's free-issue products.

Revision ID: 0054
Revises: 0053
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = postgresql.JSONB(astext_type=sa.Text())
EXACT = sa.Numeric(precision=24, scale=10)

NEW_PERMISSIONS = [
    ("estimate.view", "material", "View material estimates, the consumption library and mix designs"),
    ("estimate.edit", "material", "Make material estimates and their areas and lines"),
    ("coverage.edit", "material", "Edit the product consumption library and mix designs"),
    ("material_request.create", "material", "Ask for material by area and thickness from site"),
    ("material_request.approve", "material", "Approve or change a site material request into an indent"),
    ("margin.settings", "costing", "Set the share of a BOQ rate that material alone may take before the margin check warns"),
]
GRANTS = {
    "super_admin": {c: "all" for c, _m, _d in NEW_PERMISSIONS},
    "director": {c: "all" for c, _m, _d in NEW_PERMISSIONS},
    "office_admin": {"estimate.view": "all", "estimate.edit": "all", "coverage.edit": "all"},
    "planning": {"estimate.view": "all", "estimate.edit": "all", "coverage.edit": "all", "material_request.create": "all", "material_request.approve": "all"},
    "estimator": {"estimate.view": "all"},
    "billing": {"estimate.view": "all"},
    "store_purchase": {"estimate.view": "all"},
    "site_engineer": {"estimate.view": "assigned", "material_request.create": "assigned"},
    "site_supervisor": {"estimate.view": "assigned", "material_request.create": "assigned"},
}


def _tracked() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    ]


def upgrade() -> None:
    op.add_column("products", sa.Column("wastage_percent", sa.Numeric(precision=6, scale=2), server_default="0", nullable=False))
    op.add_column("systems", sa.Column("upturn_mm", sa.Numeric(precision=8, scale=2), server_default="300", nullable=False))
    op.add_column("costing_settings", sa.Column("material_share_warn_percent", sa.Numeric(precision=6, scale=3), server_default="70", nullable=False))
    op.add_column("rate_workings", sa.Column("free_issue_product_ids", JSON, server_default="[]", nullable=False))

    op.create_table(
        "coverages",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("systems.id", ondelete="CASCADE"), nullable=True),
        sa.Column("value", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("min_value", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("max_value", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("unit", sa.String(length=10), server_default="kg/sqm", nullable=False),
        sa.Column("source", sa.String(length=16), server_default="to_confirm", nullable=False),
        sa.Column("doc_path", sa.String(length=400), nullable=True),
        sa.Column("doc_name", sa.String(length=300), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False),
        *_tracked(),
        sa.CheckConstraint("unit IN ('kg/sqm', 'L/sqm', 'sqm/kg', 'sqm/L', 'kg/sqft', 'sqm/sqm')", name=op.f("ck_coverages_unit_valid")),
        sa.CheckConstraint("source IN ('tds', 'boq_spec', 'method_statement', 'site_trial', 'to_confirm')", name=op.f("ck_coverages_source_valid")),
        sa.CheckConstraint("value > 0", name=op.f("ck_coverages_value_positive")),
        sa.CheckConstraint("min_value IS NULL OR max_value IS NULL OR min_value <= max_value", name=op.f("ck_coverages_range_valid")),
    )
    op.create_index("ix_coverages_product_id", "coverages", ["product_id"])
    op.create_index("ix_coverages_system_id", "coverages", ["system_id"])
    op.create_index("ux_coverages_product_system", "coverages", ["product_id", sa.text("coalesce(system_id, 0)")], unique=True)

    op.create_table(
        "mix_designs",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False, unique=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=10), server_default="other", nullable=False),
        sa.Column("thickness_mm", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("dry_volume_factor", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("components", JSON, server_default="[]", nullable=False),
        sa.Column("admixture_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("admixture_per_bag", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("cement_bag_kg", sa.Numeric(precision=8, scale=2), server_default="50", nullable=False),
        sa.Column("round_sqft", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), server_default="to_confirm", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False),
        *_tracked(),
        sa.CheckConstraint("kind IN ('nodular', 'plaster', 'brick_bat', 'other')", name=op.f("ck_mix_designs_kind_valid")),
    )

    op.create_table(
        "estimates",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False, unique=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tender_id", sa.Integer(), sa.ForeignKey("tenders.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="draft", nullable=False),
        sa.Column("upturn_mm", sa.Numeric(precision=8, scale=2), server_default="300", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False),
        *_tracked(),
        sa.CheckConstraint("status IN ('draft', 'issued')", name=op.f("ck_estimates_status_valid")),
        sa.CheckConstraint("site_id IS NOT NULL OR tender_id IS NOT NULL", name=op.f("ck_estimates_has_parent")),
    )
    op.create_index("ix_estimates_site_id", "estimates", ["site_id"])
    op.create_index("ix_estimates_tender_id", "estimates", ["tender_id"])

    op.create_table(
        "estimate_areas",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("estimate_id", sa.Integer(), sa.ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("measure_area_id", sa.Integer(), sa.ForeignKey("measure_areas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cad_area_id", sa.BigInteger(), sa.ForeignKey("cad_areas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("estimate_areas.id", ondelete="CASCADE"), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("code", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("floor_sqm", EXACT, nullable=False),
        sa.Column("deduction_sqm", EXACT, server_default="0", nullable=False),
        sa.Column("periphery_m", EXACT, nullable=False),
        sa.Column("upturn_mm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("use_floor", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("use_upturn", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("included", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("excluded_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("source IN ('measure', 'takeoff', 'misc', 'manual')", name=op.f("ck_estimate_areas_source_valid")),
        sa.CheckConstraint("included OR excluded_reason IS NOT NULL", name=op.f("ck_estimate_areas_excluded_has_reason")),
    )
    op.create_index("ix_estimate_areas_estimate_id", "estimate_areas", ["estimate_id"])

    op.create_table(
        "estimate_lines",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("estimate_id", sa.Integer(), sa.ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("systems.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mix_design_id", sa.Integer(), sa.ForeignKey("mix_designs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("thickness_mm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("part", sa.String(length=6), server_default="both", nullable=False),
        sa.Column("area_ids", JSON, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("part IN ('both', 'floor', 'upturn')", name=op.f("ck_estimate_lines_part_valid")),
    )
    op.create_index("ix_estimate_lines_estimate_id", "estimate_lines", ["estimate_id"])

    op.create_table(
        "material_requests",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("code", sa.String(length=30), nullable=False, unique=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("estimate_id", sa.Integer(), sa.ForeignKey("estimates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("estimate_area_id", sa.Integer(), sa.ForeignKey("estimate_areas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mix_design_id", sa.Integer(), sa.ForeignKey("mix_designs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("area_sqm", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("thickness_mm", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("packs", sa.Integer(), nullable=True),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("left_before", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("over_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="requested", nullable=False),
        sa.Column("approved_qty", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indent_id", sa.Integer(), sa.ForeignKey("indents.id", ondelete="SET NULL"), nullable=True),
        *_tracked(),
        sa.CheckConstraint("status IN ('requested', 'approved', 'rejected', 'indented')", name=op.f("ck_material_requests_status_valid")),
    )
    op.create_index("ix_material_requests_site_id", "material_requests", ["site_id"])


    for code, module, description in NEW_PERMISSIONS:
        op.execute(f"INSERT INTO permissions (code, module, description) VALUES ('{code}', '{module}', '{description}')")
    for role, codes in GRANTS.items():
        for code, scope in codes.items():
            op.execute(f"INSERT INTO role_permissions (role_id, permission_code, scope) SELECT id, '{code}', '{scope}' FROM roles WHERE code = '{role}'")


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _m, _d in NEW_PERMISSIONS)
    op.execute(f"DELETE FROM role_permissions WHERE permission_code IN ({codes})")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes})")
    for t in ("material_requests", "estimate_lines", "estimate_areas", "estimates", "mix_designs", "coverages"):
        op.drop_table(t)
    op.drop_column("rate_workings", "free_issue_product_ids")
    op.drop_column("costing_settings", "material_share_warn_percent")
    op.drop_column("systems", "upturn_mm")
    op.drop_column("products", "wastage_percent")
