"""M6b review: Raft and Footing area types from the planning meeting (unconfirmed, like the rest):
default wastage 7 % for Raft and 15 % for Footing; a footing is treated on its sides too.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-09 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TYPES = [
    # name, upturn mm, includes walls, wastage %
    ("Raft", 0, False, 7),
    ("Footing", 0, True, 15),
]


def upgrade() -> None:
    bind = op.get_bind()
    last = bind.execute(sa.text("SELECT coalesce(max(sort_order), 0) FROM area_types")).scalar()
    for i, (name, upturn, walls, wastage) in enumerate(NEW_TYPES, 1):
        bind.execute(
            sa.text(
                "INSERT INTO area_types (name, default_upturn_mm, includes_walls, "
                "needs_sunk_depth, "
                "default_wastage_percent, sort_order, confirmed) "
                "VALUES (:n, :u, :w, false, :p, :o, false) ON CONFLICT (name) DO NOTHING"
            ),
            {"n": name, "u": upturn, "w": walls, "p": wastage, "o": last + i},
        )


def downgrade() -> None:
    names = ", ".join(f"'{n}'" for n, *_ in NEW_TYPES)
    op.execute(
        "UPDATE survey_areas SET area_type_id = NULL WHERE area_type_id IN "
        f"(SELECT id FROM area_types WHERE name IN ({names}))"
    )
    op.execute(f"DELETE FROM area_types WHERE name IN ({names})")
