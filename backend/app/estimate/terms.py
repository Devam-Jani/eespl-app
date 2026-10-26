# ruff: noqa: E501
"""T&C wording on free-issue materials. Cement, sand, water and the like are supplied by the client
free of cost; a clause saying we supply them free ("provide by us at free of cost") gives them away
in writing. Such wording is flagged with the corrected text, in the T&C library and in any BOQ or
quotation before it is sent. A working's free-issue products are printed as one clause."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.masters.models import Product, TcClause

FREE = r"(?:at\s+|on\s+|as\s+)?(?:free\s+of\s+(?:cost|charges?)|free)"
US = r"(?:us|ourselves|eespl|the\s+contractor|contractor|the\s+applicator|applicator|the\s+agency|agency|our\s+side|our\s+end)"
WRONG = re.compile(
    rf"(?:provided?|supplied|supply|furnished|furnish|arranged|arrange|given)\s+by\s+(?P<who>{US})\s+{FREE}"
    rf"|{FREE}\s+by\s+(?P<who2>{US})",
    re.I,
)
MARK = "[free issue]"  # the clause the app writes for a working's free-issue products


def corrected(text: str) -> str:
    """The same clause with "the client" for whoever it said supplies free."""
    out, last = [], 0
    for m in WRONG.finditer(text):
        a, b = m.span("who" if m.group("who") else "who2")
        out += [text[last:a], "the client"]
        last = b
    return "".join([*out, text[last:]])


def check(text: str, where: str = "") -> dict | None:
    """The finding for one clause, or None when its wording is right."""
    if not text or not WRONG.search(text):
        return None
    return {"where": where, "text": text, "corrected": corrected(text),
            "warning": f"{where + ': ' if where else ''}says we supply materials free of cost; the client supplies free-issue materials"}  # fmt: skip


def check_all(items: list[tuple[str, str]]) -> list[dict]:
    return [f for f in (check(text, where) for where, text in items) if f]


def library(db: Session) -> list[dict]:
    """The T&C library's active clauses with the wrong wording."""
    out = []
    for c in db.scalars(select(TcClause).where(TcClause.status == "active").order_by(TcClause.id)):
        f = check(c.text, f"Clause {c.id} ({c.category})")
        if f:
            out.append({**f, "clause_id": c.id})
    return out


def free_issue_text(db: Session, product_ids: list[int]) -> str | None:
    names = [p.name for p in (db.get(Product, pid) for pid in product_ids) if p]
    if not names:
        return None
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{listed} shall be supplied by the client free of cost at site; they are not in our rates."
