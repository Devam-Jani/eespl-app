# ruff: noqa: E501
"""The close-out screens (review of Prompt 26): labour claim decisions (pay the approved quantity,
or the claimed one with the director's approval), the handover date's history (promised, moved
with the reason), and the permissions: Settings > Client roles (office admin and director) and
the director's approval of a labour claim above the approved quantity.

Revision ID: 0042
Revises: 0041
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    ("portal.roles", "portal", "Settings > Client roles: the default rights of each client role"),
    ("closeout.claim_approve", "closeout", "Approve paying a labour claim above the approved measurement"),
]
GRANTS = {
    "super_admin": {"portal.roles": "all", "closeout.claim_approve": "all"},
    "director": {"portal.roles": "all", "closeout.claim_approve": "all"},
    "office_admin": {"portal.roles": "all"},
}


def upgrade() -> None:
    op.add_column("labour_claims", sa.Column("photos", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))
    op.add_column("labour_claims", sa.Column("status", sa.String(length=10), server_default="open", nullable=False))
    op.add_column("labour_claims", sa.Column("decision", sa.String(length=10), nullable=True))
    op.add_column("labour_claims", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column("labour_claims", sa.Column("decided_by", sa.UUID(), nullable=True))
    op.add_column("labour_claims", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("labour_claims", sa.Column("director_by", sa.UUID(), nullable=True))
    op.add_column("labour_claims", sa.Column("director_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("labour_claims", sa.Column("director_reason", sa.Text(), nullable=True))
    op.add_column("labour_claims", sa.Column("pay_qty", sa.Numeric(precision=14, scale=3), nullable=True))
    op.create_foreign_key(op.f("fk_labour_claims_decided_by_users"), "labour_claims", "users", ["decided_by"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_labour_claims_director_by_users"), "labour_claims", "users", ["director_by"], ["id"], ondelete="SET NULL")
    op.create_check_constraint(op.f("ck_labour_claims_status_valid"), "labour_claims", "status IN ('open', 'director', 'decided')")
    op.add_column("site_nodes", sa.Column("handover_history", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))
    op.add_column("client_users", sa.Column("rights", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    for code, module, description in NEW_PERMISSIONS:
        op.execute(f"INSERT INTO permissions (code, module, description) VALUES ('{code}', '{module}', '{description}')")
    for role, codes in GRANTS.items():
        for code, scope in codes.items():
            op.execute(f"INSERT INTO role_permissions (role_id, permission_code, scope) SELECT id, '{code}', '{scope}' FROM roles WHERE code = '{role}'")


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _m, _d in NEW_PERMISSIONS)
    op.execute(f"DELETE FROM role_permissions WHERE permission_code IN ({codes})")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes})")
    op.drop_column("client_users", "rights")
    op.drop_column("site_nodes", "handover_history")
    op.drop_constraint(op.f("ck_labour_claims_status_valid"), "labour_claims", type_="check")
    op.drop_constraint(op.f("fk_labour_claims_director_by_users"), "labour_claims", type_="foreignkey")
    op.drop_constraint(op.f("fk_labour_claims_decided_by_users"), "labour_claims", type_="foreignkey")
    for col in ("pay_qty", "director_reason", "director_at", "director_by", "decided_at", "decided_by", "decision_reason", "decision", "status", "photos"):
        op.drop_column("labour_claims", col)
