"""Library versions: every change to a library row stores the whole row (after the change) with
who and when; restoring writes an old state back as a new version."""

from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.quotations.markup import unknown_placeholders
from app.quotations.models import (
    PLACEHOLDERS,
    Letterhead,
    LetterTemplate,
    LibraryVersion,
    OfferItem,
    OfferItemLine,
    OfferItemSpec,
    OfferLine,
    OfferPreset,
    Reference,
    SpecBlock,
)

MODELS: dict[str, type] = {
    "letterhead": Letterhead,
    "letter": LetterTemplate,
    "spec": SpecBlock,
    "line": OfferLine,
    "item": OfferItem,
    "reference": Reference,
    "preset": OfferPreset,
}
SKIP = {"id", "created_at", "updated_at", "created_by", "version"}


def _value(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "hex") and not isinstance(v, bytes | str):
        return str(v)
    return v


def snapshot(row) -> dict[str, Any]:
    """The row's editable fields as JSON (an offer item with its spec and line links)."""
    data = {
        c.key: _value(getattr(row, c.key))
        for c in inspect(row).mapper.column_attrs
        if c.key not in SKIP
    }
    if isinstance(row, OfferItem):
        data["specs"] = [
            {"spec_block_id": s.spec_block_id, "sort_order": s.sort_order} for s in row.specs
        ]
        data["lines"] = [
            {"offer_line_id": ln.offer_line_id, "option": ln.option, "sort_order": ln.sort_order}
            for ln in row.lines
        ]
    return data


def kind_of(row) -> str:
    return next(k for k, m in MODELS.items() if isinstance(row, m))


def save_version(db: Session, row, action: str, user_id, note: str | None = None) -> LibraryVersion:
    """Bump the row's version and keep its state. Call after the change, before commit."""
    db.flush()
    last = db.scalar(
        select(LibraryVersion.version)
        .where(LibraryVersion.kind == kind_of(row), LibraryVersion.entity_id == row.id)
        .order_by(LibraryVersion.version.desc())
        .limit(1)
    )
    row.version = (last or 0) + 1
    v = LibraryVersion(
        kind=kind_of(row),
        entity_id=row.id,
        version=row.version,
        action=action,
        data=snapshot(row),
        note=note,
        created_by=user_id,
    )
    db.add(v)
    db.flush()
    return v


def apply(row, data: dict[str, Any]) -> None:
    """Write a snapshot's fields onto the row (for restore and edits)."""
    cols = {c.key: c for c in inspect(type(row)).mapper.column_attrs}
    for key, value in data.items():
        if key in SKIP or key in ("specs", "lines") or key not in cols:
            continue
        setattr(row, key, value)
    if isinstance(row, OfferItem):
        if "specs" in data:
            row.specs = [
                OfferItemSpec(spec_block_id=s["spec_block_id"], sort_order=s.get("sort_order", i))
                for i, s in enumerate(data["specs"])
            ]
        if "lines" in data:
            row.lines = [
                OfferItemLine(
                    offer_line_id=ln["offer_line_id"],
                    option=ln.get("option"),
                    sort_order=ln.get("sort_order", i),
                )
                for i, ln in enumerate(data["lines"])
            ]


def check_letter(subject: str, body: str, opening: str = "") -> None:
    """Unknown placeholders are refused on save."""
    bad = sorted(
        set(unknown_placeholders(subject, PLACEHOLDERS))
        | set(unknown_placeholders(body, PLACEHOLDERS))
        | set(unknown_placeholders(opening, PLACEHOLDERS))
    )
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unknown placeholder(s): "
            + ", ".join("{" + b + "}" for b in bad)
            + ". Allowed: "
            + ", ".join("{" + p + "}" for p in PLACEHOLDERS),
        )


def restore(db: Session, kind: str, entity_id: int, version: int, user_id):
    model = MODELS[kind]
    row = db.get(model, entity_id)
    v = db.scalar(
        select(LibraryVersion).where(
            LibraryVersion.kind == kind,
            LibraryVersion.entity_id == entity_id,
            LibraryVersion.version == version,
        )
    )
    if row is None or v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    if kind == "letter":
        check_letter(v.data.get("subject", ""), v.data.get("body", ""), v.data.get("opening", ""))
    apply(row, v.data)
    save_version(db, row, "restore", user_id, note=f"restored version {version}")
    return row
