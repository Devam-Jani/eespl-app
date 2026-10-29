"""From the SOP bug sweep (group E): a lead's lost_reason was varchar(12), one short of
"main_job_lost" (13), so "Main job lost by the contractor" could never be saved on a lead.
Widened to 20 like the quotations' column. The downgrade maps the reason back to 'other' first.

Revision ID: 0056e
Revises: 0055
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056e"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_LINK, NEW_LINK = "/indents/{indent_id}", "/indents?open={indent_id}"


def upgrade() -> None:
    op.alter_column("leads", "lost_reason", type_=sa.String(20), existing_type=sa.String(12))
    # "Indent approved, place the PO" opened /indents/<id>, a page that does not exist (the
    # rule row is seeded once; an edited link is left alone)
    op.execute(
        f"UPDATE process_rules SET link = '{NEW_LINK}' WHERE code = 'indent_approved' AND link = '{OLD_LINK}'"  # noqa: E501
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE process_rules SET link = '{OLD_LINK}' WHERE code = 'indent_approved' AND link = '{NEW_LINK}'"  # noqa: E501
    )
    op.execute("UPDATE leads SET lost_reason = 'other' WHERE lost_reason = 'main_job_lost'")
    op.alter_column("leads", "lost_reason", type_=sa.String(12), existing_type=sa.String(20))
