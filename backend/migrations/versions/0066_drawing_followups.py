# ruff: noqa: E501  (the patterns read better unwrapped)
"""Prompt 39c: a takeoff area left out on its own says why (left_out: structural tag, duplicate
copy); quotation.edit_own_draft for planning (a quotation it made, while a draft never sent); the
default system of each area type, from the systems most used in our past BOQs, filled only where
an area type has none (a default someone set is never overwritten), the second option added to
its suitable systems. Expansion and construction joints keep what they have.

The downgrade drops the column and the permission; the defaults filled stay (they are data the
team may have kept since).

Revision ID: 0066i
Revises: 0065h
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066i"
down_revision: str | None = "0065h"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE = "quotation.edit_own_draft"

# the kinds of system, read from the system's name, description and its products' names
KINDS = {
    "cem": r"cementitious|cement\s*based|polymer\s*modified|acrylic\s*polymer|elastomeric\s*cement|cem\s*coat|flexible\s*cement",
    "2k": r"two\s*-?\s*comp|\b2\s*-?\s*k\b|\b2\s*comp|bi\s*-?\s*comp|two\s*part",
    "mesh": r"mesh|fabric|fib(re|er)\s*glass|glass\s*fib",
    "pu": r"\bpu\b|polyurethane|poly\s*urethane",
    "1k": r"single\s*comp|\b1\s*-?\s*k\b|one\s*comp|mono\s*comp",
    "hdpe": r"hdpe|pre\s*-?\s*applied",
    "crystalline": r"crystal",
    "epoxy": r"epoxy",
    "potable": r"potable|hygien|food\s*grade|drinking",
}
# area type (name pattern) -> (the default, the second option); each a list of kinds, tried in order
WANT = [
    (r"terrace|roof", [("cem", "2k", "mesh"), ("cem", "2k")], [("pu", "1k"), ("pu",)]),
    (r"toilet|bath|sunk", [("cem", "2k")], []),
    (r"kitchen", [("cem", "2k")], []),
    (r"balcon", [("cem", "2k")], []),
    (r"podium|planter", [("pu",)], []),
    (r"raft|retaining|basement", [("hdpe",)], [("crystalline",)]),
    (r"water\s*tank|\btank\b", [("cem", "2k")], [("epoxy", "potable", "lining"), ("lining",)]),
]
KEEP = r"joint"  # expansion and construction joints keep what the library has


def _systems(conn) -> list[dict]:
    rows = conn.execute(sa.text(
        """SELECT s.id, s.name, coalesce(s.description, ''), s.unit, coalesce(s.spec_type, ''),
                  coalesce(string_agg(p.name, ' '), '') AS products,
                  (SELECT count(*) FROM rate_groups g WHERE g.system_id = s.id)
                + (SELECT count(*) FROM quotation_lines l WHERE l.system_id = s.id)
                + (SELECT count(*) FROM boq_lines b WHERE b.system_id = s.id) AS used
             FROM systems s
             LEFT JOIN system_components c ON c.system_id = s.id
             LEFT JOIN products p ON p.id = c.product_id
            WHERE s.is_active AND s.unit IN ('sqm', 'sqft')
            GROUP BY s.id"""
    )).all()
    out = []
    for sid, name, desc, unit, spec_type, products, used in rows:
        own = f"{name} {desc} {spec_type}".lower()
        kinds = {k for k, pat in KINDS.items() if re.search(pat, own)}
        if spec_type == "cementitious":
            kinds.add("cem")
        if spec_type in KINDS:
            kinds.add(spec_type)
        if re.search(KINDS["mesh"], products.lower()):
            kinds.add("mesh")
        if "pu" in kinds and re.search(r"polyurea", own):
            kinds.discard("pu")
        if "epoxy" in kinds and not re.search(r"coal\s*tar", own):
            kinds.add("lining")  # an epoxy that can line a water tank (a coal tar one cannot)
        out.append({"id": sid, "name": name, "unit": unit, "kinds": kinds, "used": int(used or 0)})
    return out


def _best(systems: list[dict], wants: list[tuple]) -> dict | None:
    for want in wants:
        hits = [s for s in systems if set(want) <= s["kinds"]]
        if hits:  # the most used in our past BOQs, quotations and workings; per sqm before per sq ft
            return max(hits, key=lambda s: (s["used"], s["unit"] == "sqm", -s["id"]))
    return None


def pick_defaults(conn) -> list[dict]:
    """For each area type: the system it would get, its second option, and whether it is filled
    (an area type with a default already keeps it)."""
    systems = _systems(conn)
    out = []
    for tid, name, default_id, suitable in conn.execute(sa.text("SELECT id, name, default_system_id, suitable_system_ids FROM area_types ORDER BY id")).all():
        if re.search(KEEP, name, re.I):
            out.append({"area_type_id": tid, "area_type": name, "default": None, "second": None, "note": "a joint: kept as the library has it"})
            continue
        want = next(((d, s) for pat, d, s in WANT if re.search(pat, name, re.I)), None)
        if want is None:
            out.append({"area_type_id": tid, "area_type": name, "default": None, "second": None, "note": "not in the list: left as it is"})
            continue
        best = _best(systems, want[0])
        second = _best([s for s in systems if not best or s["id"] != best["id"]], want[1]) if want[1] else None
        note = "kept: a default was set already" if default_id else ("no matching system in the library" if best is None else "filled")
        out.append({"area_type_id": tid, "area_type": name, "default": best, "second": second, "note": note, "had_default": bool(default_id), "suitable": list(suitable or [])})
    return out


def fill_defaults(conn) -> list[str]:
    """Fill each area type's default (only where it has none) and add the second option to its
    suitable systems; returns what each area type got."""
    out: list[str] = []
    for p in pick_defaults(conn):
        d, s2 = p.get("default"), p.get("second")
        if d and not p.get("had_default"):
            conn.execute(sa.text("UPDATE area_types SET default_system_id = :s WHERE id = :t AND default_system_id IS NULL"), {"s": d["id"], "t": p["area_type_id"]})
        if s2 and s2["id"] not in p.get("suitable", []):
            conn.execute(sa.text("UPDATE area_types SET suitable_system_ids = array_append(suitable_system_ids, :s) WHERE id = :t"), {"s": s2["id"], "t": p["area_type_id"]})
        shown = "its own default" if p.get("had_default") else ((d or {}).get("name") or "-")
        out.append(f"  area type {p['area_type']}: {shown} | second: {(s2 or {}).get('name') or '-'} | {p['note']}")
    return out


def upgrade() -> None:
    op.add_column("cad_areas", sa.Column("left_out", sa.String(length=12), nullable=True))
    op.create_check_constraint(op.f("ck_cad_areas_left_out_valid"), "cad_areas", "left_out IS NULL OR left_out IN ('structural', 'duplicate')")
    op.execute(f"INSERT INTO permissions (code, module, description) VALUES ('{CODE}', 'quotations', 'Change a quotation one made, while it is a draft never sent')")
    op.execute(f"INSERT INTO role_permissions (role_id, permission_code, scope) SELECT id, '{CODE}', 'own' FROM roles WHERE code = 'planning'")
    # the super admin holds every permission (it edits every quotation already: nothing changes)
    op.execute(f"INSERT INTO role_permissions (role_id, permission_code, scope) SELECT id, '{CODE}', 'all' FROM roles WHERE code = 'super_admin'")
    for line in fill_defaults(op.get_bind()):
        print(line)


def downgrade() -> None:
    op.execute(f"DELETE FROM role_permissions WHERE permission_code = '{CODE}'")
    op.execute(f"DELETE FROM permissions WHERE code = '{CODE}'")
    op.drop_constraint(op.f("ck_cad_areas_left_out_valid"), "cad_areas", type_="check")
    op.drop_column("cad_areas", "left_out")
